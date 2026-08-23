import os
import time
import asyncio
from typing import Optional, Dict, Tuple

import jwt
from jwt import PyJWKClient
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models import Organization, User, OrgMembership, UserRole

# ── Clerk JWKS configuration ─────────────────────────────────────────────────
CLERK_JWKS_URL = os.getenv("CLERK_JWKS_URL")
CLERK_ISSUER = os.getenv("CLERK_ISSUER")  # optional, stricter verification

_jwks_client: Optional[PyJWKClient] = None
if CLERK_JWKS_URL:
    # cache_keys/cache_jwk_set + lifespan avoid refetching the JWKS document
    # on every request; PyJWKClient handles this internally with an in-memory
    # cache keyed by URL.
    _jwks_client = PyJWKClient(CLERK_JWKS_URL, cache_keys=True, cache_jwk_set=True, lifespan=3600)

security = HTTPBearer()

# ── In-process clerk_id -> internal int id cache (TTL) ──────────────────────
# Keeps JIT-provisioning cheap for repeat requests from the same org/user
# without hitting Postgres on every call. Not shared across processes —
# a cache miss just falls through to the DB (or a fresh JIT insert).
_ID_CACHE_TTL_SECONDS = 300
# Simple size cap so a flood of distinct clerk ids (or a misbehaving client)
# can't grow these dicts unbounded for the life of the process.
_ID_CACHE_MAX_SIZE = 10_000
_org_id_cache: Dict[str, Tuple[int, float]] = {}
_user_id_cache: Dict[str, Tuple[int, float]] = {}


def _cache_get(cache: Dict[str, Tuple[int, float]], key: str) -> Optional[int]:
    entry = cache.get(key)
    if not entry:
        return None
    value, cached_at = entry
    if time.time() - cached_at > _ID_CACHE_TTL_SECONDS:
        cache.pop(key, None)
        return None
    return value


def _cache_set(cache: Dict[str, Tuple[int, float]], key: str, value: int) -> None:
    if len(cache) >= _ID_CACHE_MAX_SIZE and key not in cache:
        # Cheap eviction: drop the oldest entry rather than growing forever.
        # This isn't a strict LRU -- just a bound -- which is all a
        # JIT-provisioning cache needs.
        oldest_key = min(cache, key=lambda k: cache[k][1])
        cache.pop(oldest_key, None)
    cache[key] = (value, time.time())


def _map_clerk_role(claims: dict) -> UserRole:
    """Best-effort mapping of Clerk org-role claims to our UserRole. Never
    grants SUPER_ADMIN from a Clerk claim — that is only assigned in our DB
    via api/admin.py's promote endpoint."""
    org_claim = claims.get("o") or {}
    role_str = (org_claim.get("rol") or claims.get("org_role") or "").replace("org:", "")
    if role_str == "admin":
        return UserRole.ADMIN
    return UserRole.MEMBER


def _decode_token_sync(token: str) -> dict:
    """Blocking JWKS lookup + JWT verification. Always invoked via a threadpool."""
    if not _jwks_client:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="CLERK_JWKS_URL not configured",
        )
    signing_key = _jwks_client.get_signing_key_from_jwt(token)
    # Clerk session tokens may carry an `aud` claim we have no configured
    # audience to check against; PyJWT 2.13 hard-fails decode() if `aud` is
    # present and audience verification is left on with no `audience=`
    # passed in. We verify `iss` ourselves (below, when CLERK_ISSUER is set)
    # instead of relying on PyJWT's audience check.
    decode_kwargs = {"algorithms": ["RS256"], "options": {"verify_aud": False}}
    if CLERK_ISSUER:
        decode_kwargs["issuer"] = CLERK_ISSUER
    return jwt.decode(token, signing_key.key, **decode_kwargs)


# ── JIT provisioning ──────────────────────────────────────────────────────────

async def _get_or_create_organization(
    db: AsyncSession, clerk_org_id: str, name: Optional[str] = None
) -> Organization:
    cached_id = _cache_get(_org_id_cache, clerk_org_id)
    if cached_id is not None:
        org = await db.get(Organization, cached_id)
        # Guard against a stale/corrupted cache entry pointing at a row that
        # no longer matches the clerk_org_id it was cached under -- fall
        # through to the DB lookup below rather than trusting it blindly.
        if org is not None and org.clerk_org_id == clerk_org_id:
            return org
        _org_id_cache.pop(clerk_org_id, None)

    result = await db.execute(select(Organization).where(Organization.clerk_org_id == clerk_org_id))
    org = result.scalar_one_or_none()
    if org is not None:
        _cache_set(_org_id_cache, clerk_org_id, org.id)
        return org

    stmt = (
        pg_insert(Organization)
        .values(clerk_org_id=clerk_org_id, name=name or clerk_org_id, is_active=True)
        .on_conflict_do_nothing(index_elements=["clerk_org_id"])
        .returning(Organization.id)
    )
    result = await db.execute(stmt)
    row = result.first()
    if row is None:
        # Lost a create race to a concurrent request — re-fetch the winner's row.
        result = await db.execute(select(Organization).where(Organization.clerk_org_id == clerk_org_id))
        org = result.scalar_one()
    else:
        org = await db.get(Organization, row[0])

    _cache_set(_org_id_cache, clerk_org_id, org.id)
    return org


async def _get_or_create_user(
    db: AsyncSession, clerk_user_id: str, email: str, role: UserRole
) -> User:
    cached_id = _cache_get(_user_id_cache, clerk_user_id)
    if cached_id is not None:
        user = await db.get(User, cached_id)
        if user is not None:
            return user

    result = await db.execute(select(User).where(User.clerk_user_id == clerk_user_id))
    user = result.scalar_one_or_none()
    if user is not None:
        _cache_set(_user_id_cache, clerk_user_id, user.id)
        return user

    stmt = (
        pg_insert(User)
        .values(clerk_user_id=clerk_user_id, email=email or "", role=role)
        .on_conflict_do_nothing(index_elements=["clerk_user_id"])
        .returning(User.id)
    )
    result = await db.execute(stmt)
    row = result.first()
    if row is None:
        result = await db.execute(select(User).where(User.clerk_user_id == clerk_user_id))
        user = result.scalar_one()
    else:
        user = await db.get(User, row[0])

    _cache_set(_user_id_cache, clerk_user_id, user.id)
    return user


async def _get_or_create_membership(
    db: AsyncSession, org_id: int, user_id: int, role: str
) -> OrgMembership:
    result = await db.execute(
        select(OrgMembership).where(OrgMembership.org_id == org_id, OrgMembership.user_id == user_id)
    )
    membership = result.scalar_one_or_none()
    if membership is not None:
        return membership

    stmt = (
        pg_insert(OrgMembership)
        .values(org_id=org_id, user_id=user_id, role=role)
        .on_conflict_do_nothing(index_elements=["org_id", "user_id"])
        .returning(OrgMembership.id)
    )
    result = await db.execute(stmt)
    row = result.first()
    if row is None:
        result = await db.execute(
            select(OrgMembership).where(OrgMembership.org_id == org_id, OrgMembership.user_id == user_id)
        )
        membership = result.scalar_one()
    else:
        membership = await db.get(OrgMembership, row[0])

    return membership


async def get_current_session(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Validates the Clerk JWT via JWKS, then JIT-provisions (get-or-create) the
    Organization, User, and OrgMembership rows referenced by the token's
    claims. Returns a session dict with internal integer IDs — every router
    downstream should scope queries by session["org_id"] / session["user_id"],
    never by the raw Clerk string IDs.
    """
    token = credentials.credentials

    try:
        claims = await asyncio.to_thread(_decode_token_sync, token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {str(e)}")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=401, detail="Authentication failed")

    clerk_user_id = claims.get("sub")
    org_claim = claims.get("o") or {}
    clerk_org_id = org_claim.get("id") or claims.get("org_id")

    if not clerk_user_id:
        raise HTTPException(status_code=401, detail="Token missing subject claim")
    if not clerk_org_id:
        raise HTTPException(status_code=403, detail="No organization selected in session")

    org_name = org_claim.get("slg") or claims.get("org_slug")
    role = _map_clerk_role(claims)
    email = claims.get("email") or ""

    organization = await _get_or_create_organization(db, clerk_org_id, name=org_name)
    if not organization.is_active:
        raise HTTPException(status_code=403, detail="Organization is deactivated")

    user = await _get_or_create_user(db, clerk_user_id, email=email, role=role)
    membership = await _get_or_create_membership(db, organization.id, user.id, role=role.value)
    await db.commit()

    # Rate-limit by authenticated user rather than by (possibly shared/NATed)
    # remote address; backend/limiter.py's key_func reads this off the
    # request when present and falls back to remote address otherwise.
    request.state.rate_key = user.clerk_user_id

    return {
        "org_id": organization.id,
        "user_id": user.id,
        "clerk_org_id": organization.clerk_org_id,
        "clerk_user_id": user.clerk_user_id,
        "role": membership.role,
    }
