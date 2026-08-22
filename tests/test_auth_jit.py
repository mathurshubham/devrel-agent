"""
Tests for backend/utils/auth.py's JIT-provisioning helpers.

The "not found -> insert" branch of _get_or_create_organization/_user/
_membership uses a Postgres-specific `INSERT ... ON CONFLICT DO NOTHING`
(sqlalchemy.dialects.postgresql.insert) — that construct does not compile
under SQLite, so it isn't exercised here (it was validated against a real
Postgres instance during development: see the migration upgrade/downgrade
cycle and backend/seed.py's idempotent-upsert runs). What IS dialect-
agnostic, and covered below against aiosqlite, is the "found -> return
existing row" branch, which is the hit path taken on every request after
the first for a given org/user — plus the pure in-process cache logic and
Clerk role-claim mapping, which have no DB dependency at all.
"""
import time

import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from backend.models import Base, Organization, User, OrgMembership, UserRole
from backend.utils.auth import (
    _get_or_create_organization,
    _get_or_create_user,
    _get_or_create_membership,
    _map_clerk_role,
    _cache_get,
    _cache_set,
    _org_id_cache,
    _user_id_cache,
    _ID_CACHE_TTL_SECONDS,
)


@pytest.fixture
async def sqlite_session():
    """
    In-memory aiosqlite session with only the non-JSONB tables created
    (Organization/User/OrgMembership carry no JSONB columns or Postgres-only
    index options, so they're fully portable).
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(
            Base.metadata.create_all,
            tables=[Organization.__table__, User.__table__, OrgMembership.__table__],
        )

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    await engine.dispose()


async def test_get_or_create_organization_returns_existing_row(sqlite_session):
    _org_id_cache.clear()

    org = Organization(clerk_org_id="org_existing", name="Acme Inc")
    sqlite_session.add(org)
    await sqlite_session.commit()

    fetched = await _get_or_create_organization(sqlite_session, "org_existing")

    assert fetched.id == org.id
    assert fetched.name == "Acme Inc"
    # The hit path should have warmed the cache for next time.
    assert _cache_get(_org_id_cache, "org_existing") == org.id


async def test_get_or_create_user_returns_existing_row(sqlite_session):
    _user_id_cache.clear()

    user = User(clerk_user_id="user_existing", email="a@example.com", role=UserRole.MEMBER)
    sqlite_session.add(user)
    await sqlite_session.commit()

    fetched = await _get_or_create_user(
        sqlite_session, "user_existing", email="a@example.com", role=UserRole.MEMBER
    )

    assert fetched.id == user.id
    assert _cache_get(_user_id_cache, "user_existing") == user.id


async def test_get_or_create_membership_returns_existing_row(sqlite_session):
    org = Organization(clerk_org_id="org_m", name="Org M")
    user = User(clerk_user_id="user_m", email="m@example.com", role=UserRole.ADMIN)
    sqlite_session.add_all([org, user])
    await sqlite_session.flush()

    membership = OrgMembership(org_id=org.id, user_id=user.id, role="ADMIN")
    sqlite_session.add(membership)
    await sqlite_session.commit()

    fetched = await _get_or_create_membership(sqlite_session, org.id, user.id, role="ADMIN")

    assert fetched.id == membership.id
    assert fetched.role == "ADMIN"


def test_cache_get_set_roundtrip():
    cache = {}
    _cache_set(cache, "k", 42)
    assert _cache_get(cache, "k") == 42


def test_cache_get_expires_after_ttl(monkeypatch):
    cache = {}
    base_time = 1_000_000.0
    monkeypatch.setattr(time, "time", lambda: base_time)
    _cache_set(cache, "k", 42)

    monkeypatch.setattr(time, "time", lambda: base_time + _ID_CACHE_TTL_SECONDS + 1)
    assert _cache_get(cache, "k") is None
    assert "k" not in cache  # expired entries are evicted on read


def test_map_clerk_role_admin_claim():
    assert _map_clerk_role({"o": {"rol": "admin"}}) == UserRole.ADMIN
    assert _map_clerk_role({"org_role": "org:admin"}) == UserRole.ADMIN


def test_map_clerk_role_defaults_to_member():
    assert _map_clerk_role({}) == UserRole.MEMBER
    assert _map_clerk_role({"o": {"rol": "basic_member"}}) == UserRole.MEMBER


def test_map_clerk_role_never_yields_super_admin():
    # SUPER_ADMIN can only be granted via api/admin.py's promote endpoint —
    # never derived from a Clerk-supplied claim.
    for claims in [{"o": {"rol": "admin"}}, {"o": {"rol": "owner"}}, {"org_role": "org:super_admin"}]:
        assert _map_clerk_role(claims) != UserRole.SUPER_ADMIN
