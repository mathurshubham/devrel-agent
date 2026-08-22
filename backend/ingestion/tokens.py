"""Multi-token Apify vault service (PRD V7 §5.2).

An org stores N Apify tokens (``OrgApifyToken``). Each token carries its own
``plan_cap_usd`` (Apify's free tier is $5/month, paid plans differ). Before a
run we ask Apify what each token has already burned this cycle, keep the ones
with credit left, and pick the one with the most headroom.

Credit summaries are cached in Redis for 10 minutes keyed by a hash of the
token — the usage endpoint is slow and we may consult the vault many times per
polling cycle. A 401/403 invalidates that token's cache entry immediately so a
rotated/revoked token is not remembered as usable.

Callers pass tokens in **decrypted**; decryption is the caller's job (see
``backend.utils.encryption``). This module never touches the database.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import asdict, dataclass
from typing import Iterable, Optional, Sequence

import httpx

logger = logging.getLogger(__name__)

APIFY_USAGE_URL = "https://api.apify.com/v2/users/me/usage/monthly"

TOKEN_PREFIX = "apify_api_"
#: Apify free-tier monthly credit allowance, used when a token has no explicit cap.
DEFAULT_PLAN_CAP_USD = 5.0
#: Below this much remaining credit a token cannot realistically finish a run.
MIN_USABLE_REMAINING_USD = 0.01

CREDIT_CACHE_TTL_SECONDS = 600  # 10 minutes
CREDIT_CACHE_PREFIX = "apify:credits:"


class NoUsableTokenError(RuntimeError):
    """Every token in the vault is invalid, unreachable, or out of credit."""

    def __init__(self, summaries: Sequence["ApifyCreditSummary"] | None = None):
        self.summaries = list(summaries or [])
        detail = "; ".join(
            f"{s.label or s.token_id}: {s.error or f'${s.remaining_usd:.2f} left'}"
            for s in self.summaries
        )
        super().__init__(
            "No Apify token with usable credit"
            + (f" ({detail})" if detail else "")
        )


def is_valid_apify_token(token: Optional[str]) -> bool:
    """Apify personal API tokens are prefixed ``apify_api_``."""
    return bool(token and token.strip().startswith(TOKEN_PREFIX))


def token_fingerprint(token: str) -> str:
    """Stable, non-reversible cache key component for a token."""
    return hashlib.sha256(token.strip().encode()).hexdigest()[:32]


def mask_token(token: str) -> str:
    """Render a token for display: never echo the secret back to a client."""
    clean = (token or "").strip()
    return f"••••{clean[-4:]}" if len(clean) >= 4 else "••••"


@dataclass
class ApifyCreditSummary:
    """What one token has left this billing cycle."""

    token_id: Optional[int]
    label: Optional[str]
    used_usd: float
    max_usd: float
    remaining_usd: float
    pct_used: float
    usage_cycle_start: Optional[str]
    usage_cycle_end: Optional[str]
    is_usable: bool
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class VaultToken:
    """A decrypted token handed to the service by the caller."""

    token: str
    token_id: Optional[int] = None
    label: Optional[str] = None
    plan_cap_usd: float = DEFAULT_PLAN_CAP_USD


def dev_fallback_token() -> Optional[VaultToken]:
    """``APIFY_TOKEN`` from the environment, for orgs with an empty vault.

    Intended for local development and the single-tenant bootstrap case; in
    production every org supplies its own vault entries.
    """
    raw = os.environ.get("APIFY_TOKEN")
    if not is_valid_apify_token(raw):
        return None
    return VaultToken(token=raw.strip(), token_id=None, label="env:APIFY_TOKEN")


def _unusable(
    vault_token: VaultToken, error: str, cap: float
) -> ApifyCreditSummary:
    return ApifyCreditSummary(
        token_id=vault_token.token_id,
        label=vault_token.label,
        used_usd=0.0,
        max_usd=round(cap, 2),
        remaining_usd=0.0,
        pct_used=0.0,
        usage_cycle_start=None,
        usage_cycle_end=None,
        is_usable=False,
        error=error,
    )


class ApifyTokenService:
    """Fetches, caches and ranks per-token Apify credit summaries."""

    def __init__(self, redis_client=None, http_client: Optional[httpx.AsyncClient] = None):
        self._redis = redis_client
        self._redis_resolved = redis_client is not None
        self._http_client = http_client

    # -- Redis -----------------------------------------------------------

    async def _get_redis(self):
        """Lazily connect to Redis; a Redis outage degrades to no caching."""
        if self._redis_resolved:
            return self._redis
        self._redis_resolved = True
        try:
            import redis.asyncio as redis  # imported lazily: tests run without it

            url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
            self._redis = redis.from_url(url, decode_responses=True)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Apify credit cache disabled, Redis unavailable: %s", exc)
            self._redis = None
        return self._redis

    @staticmethod
    def _cache_key(token: str) -> str:
        return f"{CREDIT_CACHE_PREFIX}{token_fingerprint(token)}"

    async def _cache_read(self, token: str) -> Optional[dict]:
        r = await self._get_redis()
        if r is None:
            return None
        try:
            raw = await r.get(self._cache_key(token))
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Apify credit cache read failed: %s", exc)
            return None
        if not raw:
            return None
        try:
            return json.loads(raw if isinstance(raw, str) else raw.decode())
        except (ValueError, AttributeError):
            return None

    async def _cache_write(self, token: str, payload: dict) -> None:
        r = await self._get_redis()
        if r is None:
            return
        try:
            await r.set(
                self._cache_key(token), json.dumps(payload), ex=CREDIT_CACHE_TTL_SECONDS
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Apify credit cache write failed: %s", exc)

    async def invalidate(self, token: str) -> None:
        """Drop a token's cached summary (called on 401/403)."""
        r = await self._get_redis()
        if r is None:
            return
        try:
            await r.delete(self._cache_key(token))
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Apify credit cache invalidation failed: %s", exc)

    # -- Credit summaries -------------------------------------------------

    async def fetch_credit_summary(
        self,
        vault_token: VaultToken,
        *,
        client: Optional[httpx.AsyncClient] = None,
        use_cache: bool = True,
    ) -> ApifyCreditSummary:
        """Remaining credit for one token: ``plan_cap_usd - used``."""
        cap = float(vault_token.plan_cap_usd or DEFAULT_PLAN_CAP_USD)

        if not is_valid_apify_token(vault_token.token):
            return _unusable(vault_token, "Token does not look like an Apify API token", cap)

        if use_cache:
            cached = await self._cache_read(vault_token.token)
            if cached is not None:
                # The cap lives on our row, not Apify's — re-derive against the
                # current cap so a cap edit takes effect without a cache miss.
                return self._summary_from_usage(vault_token, cached, cap)

        own_client = client is None and self._http_client is None
        http = client or self._http_client or httpx.AsyncClient(timeout=15.0)
        try:
            resp = await http.get(
                APIFY_USAGE_URL,
                headers={"Authorization": f"Bearer {vault_token.token}"},
            )
            resp.raise_for_status()
            usage = resp.json()["data"]
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code if exc.response is not None else None
            if status in (401, 403):
                await self.invalidate(vault_token.token)
                return _unusable(vault_token, "Apify token is invalid or unauthorized", cap)
            return _unusable(vault_token, f"Failed to fetch Apify credits (HTTP {status})", cap)
        except httpx.RequestError:
            return _unusable(vault_token, "Could not reach the Apify API", cap)
        except (KeyError, ValueError):
            return _unusable(vault_token, "Unexpected response from the Apify API", cap)
        finally:
            if own_client:
                await http.aclose()

        if use_cache:
            await self._cache_write(vault_token.token, usage)
        return self._summary_from_usage(vault_token, usage, cap)

    @staticmethod
    def _summary_from_usage(
        vault_token: VaultToken, usage: dict, cap: float
    ) -> ApifyCreditSummary:
        used = float(usage.get("totalUsageCreditsUsdAfterVolumeDiscount") or 0.0)
        remaining = max(0.0, cap - used)
        cycle = usage.get("usageCycle") or {}
        return ApifyCreditSummary(
            token_id=vault_token.token_id,
            label=vault_token.label,
            used_usd=round(used, 4),
            max_usd=round(cap, 2),
            remaining_usd=round(remaining, 4),
            pct_used=round(min(100.0, (used / cap) * 100.0), 2) if cap else 100.0,
            usage_cycle_start=cycle.get("startAt"),
            usage_cycle_end=cycle.get("endAt"),
            is_usable=remaining >= MIN_USABLE_REMAINING_USD,
            error=None,
        )

    async def fetch_credit_summaries(
        self, vault_tokens: Iterable[VaultToken], *, use_cache: bool = True
    ) -> list[ApifyCreditSummary]:
        tokens = list(vault_tokens)
        if not tokens:
            return []
        async with httpx.AsyncClient(timeout=15.0) as client:
            return [
                await self.fetch_credit_summary(t, client=client, use_cache=use_cache)
                for t in tokens
            ]

    # -- Selection ---------------------------------------------------------

    async def select_best_token(
        self, vault_tokens: Iterable[VaultToken], *, allow_env_fallback: bool = True
    ) -> tuple[VaultToken, ApifyCreditSummary]:
        """Return the usable token with the most remaining credit.

        Falls back to ``APIFY_TOKEN`` from the environment when the org's vault
        is empty. Raises :class:`NoUsableTokenError` when nothing has credit.
        """
        tokens = list(vault_tokens)
        if not tokens and allow_env_fallback:
            fallback = dev_fallback_token()
            if fallback:
                logger.info("Apify vault empty; using the APIFY_TOKEN dev fallback")
                tokens = [fallback]

        summaries = await self.fetch_credit_summaries(tokens)
        ranked = [
            (token, summary)
            for token, summary in zip(tokens, summaries)
            if summary.is_usable and not summary.error
        ]
        if not ranked:
            raise NoUsableTokenError(summaries)
        ranked.sort(key=lambda pair: pair[1].remaining_usd, reverse=True)
        return ranked[0]
