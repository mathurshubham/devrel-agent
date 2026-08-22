"""Ingestion orchestration: token pick -> budget guard -> run -> normalize.

``ingest_campaign`` is the single entry point the Celery pollers call. It owns
the money-sensitive part of the flow: an org's monthly Apify spend is tracked
in a Redis counter and a run that would push the org over its budget is refused
*before* the actor starts, because an Apify run cannot be un-billed.

Spend is only incremented after a run succeeds, so failed runs (which Apify
generally does not bill for the full result set) do not eat the budget.
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime, timezone
from typing import Any, Iterable, Optional, Sequence

from backend.ingestion.inputs import build_actor_input
from backend.ingestion.normalize import filter_stale_posts, normalize_items
from backend.ingestion.runner import ApifyRunner
from backend.ingestion.tokens import ApifyTokenService, VaultToken

logger = logging.getLogger(__name__)


#: Actor cost in USD per 1,000 results, per platform. Env-overridable so ops can
#: re-price without a deploy when an actor changes its pricing.
DEFAULT_COST_PER_1K_USD: dict[str, float] = {
    "LINKEDIN": 5.00,
    "REDDIT": 4.04,
    "TWITTER": 0.25,
}

#: Fallback org monthly Apify budget when OrgSettings does not set one.
DEFAULT_MONTHLY_BUDGET_USD = 25.0

SPEND_KEY_PREFIX = "apify:spend"
#: Keep two extra months of counters so month-boundary reads stay correct.
SPEND_KEY_TTL_SECONDS = 60 * 60 * 24 * 90


class BudgetExceededError(RuntimeError):
    """The estimated run cost would push the org past its monthly Apify budget."""

    def __init__(self, org_id: int, estimate_usd: float, spent_usd: float, budget_usd: float):
        self.org_id = org_id
        self.estimate_usd = estimate_usd
        self.spent_usd = spent_usd
        self.budget_usd = budget_usd
        super().__init__(
            f"Org {org_id} Apify budget exceeded: ${spent_usd:.2f} spent + "
            f"${estimate_usd:.2f} estimated > ${budget_usd:.2f} monthly budget"
        )


# ---------------------------------------------------------------------------
# Cost model
# ---------------------------------------------------------------------------


def cost_per_1k(platform: str) -> float:
    """Cost per 1,000 results for a platform, honouring env overrides.

    ``APIFY_COST_PER_1K_LINKEDIN`` etc. override the built-in table.
    """
    key = (platform or "").upper()
    override = os.environ.get(f"APIFY_COST_PER_1K_{key}")
    if override:
        try:
            return float(override)
        except ValueError:
            logger.warning("Ignoring non-numeric APIFY_COST_PER_1K_%s=%r", key, override)
    return DEFAULT_COST_PER_1K_USD.get(key, 0.0)


def expected_results(campaign: Any) -> int:
    """How many results one run of this campaign is expected to return."""
    _actor_id, actor_input = build_actor_input(campaign)
    for field in ("maxItems", "limit", "maxPostsPerSource"):
        value = actor_input.get(field)
        if isinstance(value, int) and value > 0:
            return value
    return 20


def estimate_run_cost_usd(campaign: Any) -> float:
    """Estimated USD cost of a single run of ``campaign``."""
    platform = getattr(getattr(campaign, "platform", ""), "value", getattr(campaign, "platform", ""))
    return round(expected_results(campaign) * cost_per_1k(str(platform)) / 1000.0, 4)


def runs_per_month(campaign: Any) -> float:
    """Runs a campaign performs in a 30-day month at its poll frequency."""
    minutes = getattr(campaign, "poll_frequency_minutes", None) or 240
    return (30 * 24 * 60) / float(minutes)


def estimate_monthly_cost_usd(campaign: Any) -> float:
    """Estimated USD/month for a campaign at its current poll frequency."""
    return round(estimate_run_cost_usd(campaign) * runs_per_month(campaign), 2)


# ---------------------------------------------------------------------------
# Monthly spend counter
# ---------------------------------------------------------------------------


def spend_key(org_id: int, when: Optional[date] = None) -> str:
    month = (when or datetime.now(timezone.utc).date()).strftime("%Y-%m")
    return f"{SPEND_KEY_PREFIX}:{org_id}:{month}"


async def _redis_client(redis_client=None):
    if redis_client is not None:
        return redis_client
    try:
        import redis.asyncio as redis

        return redis.from_url(
            os.environ.get("REDIS_URL", "redis://redis:6379/0"), decode_responses=True
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Apify spend tracking disabled, Redis unavailable: %s", exc)
        return None


async def get_month_spend_usd(org_id: int, redis_client=None) -> float:
    r = await _redis_client(redis_client)
    if r is None:
        return 0.0
    try:
        raw = await r.get(spend_key(org_id))
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Could not read Apify spend for org %s: %s", org_id, exc)
        return 0.0
    try:
        return float(raw or 0.0)
    except (TypeError, ValueError):
        return 0.0


async def record_spend_usd(org_id: int, amount_usd: float, redis_client=None) -> float:
    """Add ``amount_usd`` to the org's month counter; returns the new total."""
    r = await _redis_client(redis_client)
    if r is None:
        return 0.0
    key = spend_key(org_id)
    try:
        total = await r.incrbyfloat(key, float(amount_usd))
        await r.expire(key, SPEND_KEY_TTL_SECONDS)
        return float(total)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Could not record Apify spend for org %s: %s", org_id, exc)
        return 0.0


def monthly_budget_usd(org_settings: Any) -> float:
    budget = getattr(org_settings, "apify_monthly_budget_usd", None)
    try:
        return float(budget) if budget is not None else DEFAULT_MONTHLY_BUDGET_USD
    except (TypeError, ValueError):
        return DEFAULT_MONTHLY_BUDGET_USD


async def check_budget(
    org_id: int, estimate_usd: float, org_settings: Any, redis_client=None
) -> float:
    """Raise :class:`BudgetExceededError` if this run would exceed the budget.

    Returns the current month-to-date spend on success.
    """
    budget = monthly_budget_usd(org_settings)
    spent = await get_month_spend_usd(org_id, redis_client)
    if spent + estimate_usd > budget:
        raise BudgetExceededError(org_id, estimate_usd, spent, budget)
    return spent


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


async def ingest_campaign(
    session: Any,
    campaign: Any,
    org_settings: Any,
    tokens: Sequence[VaultToken] | Iterable[VaultToken],
    *,
    redis_client=None,
    token_service: Optional[ApifyTokenService] = None,
    runner: Optional[ApifyRunner] = None,
) -> list[dict]:
    """Run one campaign's actor and return normalized posts.

    ``session`` is the caller's AsyncSession. It is accepted so this function
    can grow persistence later (and so callers have a single call signature);
    the current implementation is read-only and does not touch it.

    ``tokens`` are already-decrypted vault entries — decryption stays with the
    caller so this module never depends on the DB or the key material.
    """
    org_id = int(getattr(campaign, "org_id", 0) or 0)
    platform = str(
        getattr(getattr(campaign, "platform", ""), "value", getattr(campaign, "platform", ""))
    ).upper()

    # 1. Cost estimate and budget guard — before any billable work.
    estimate = estimate_run_cost_usd(campaign)
    await check_budget(org_id, estimate, org_settings, redis_client)

    # 2. Pick the vault token with the most remaining credit.
    svc = token_service or ApifyTokenService(redis_client=redis_client)
    vault_token, summary = await svc.select_best_token(tokens)
    logger.info(
        "Ingesting campaign %s (%s) with token %s ($%.2f credit left), estimate $%.4f",
        getattr(campaign, "id", "?"),
        platform,
        summary.label or summary.token_id,
        summary.remaining_usd,
        estimate,
    )

    # 3. Run the actor.
    actor_id, actor_input = build_actor_input(campaign, org_settings)
    active_runner = runner or ApifyRunner(vault_token.token)
    raw_items = await active_runner.run_actor(actor_id, actor_input)

    # 4. The run happened, so it is billable regardless of what we do next.
    await record_spend_usd(org_id, estimate, redis_client)

    # 5. Normalize, then apply the LinkedIn recency filter.
    kwargs: dict[str, Any] = {}
    if platform == "REDDIT":
        kwargs = {
            "subreddit": str(getattr(campaign, "value", "") or "").removeprefix("r/").strip("/"),
            "max_comments": actor_input.get("maxCommentsPerPost", 5),
        }
    posts = normalize_items(platform, raw_items, **kwargs)

    if platform == "LINKEDIN":
        posts, _dropped = filter_stale_posts(
            posts,
            getattr(org_settings, "linkedin_stale_days", None),
            getattr(org_settings, "linkedin_stale_min_engagement", None),
        )

    logger.info(
        "Campaign %s ingested %d post(s) from %d raw item(s)",
        getattr(campaign, "id", "?"),
        len(posts),
        len(raw_items),
    )
    return posts
