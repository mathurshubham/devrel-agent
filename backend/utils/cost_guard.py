from datetime import date, datetime, timezone, timedelta
from typing import Optional

import redis.asyncio as redis
from sqlalchemy.ext.asyncio import AsyncSession
import litellm
from backend.models import OrgLLMConfig
from backend.utils.org_lookups import get_org_llm_config

# litellm prints a stderr banner for every model it has no pricing table
# entry for (e.g. a BYOK custom/self-hosted model behind a custom base_url,
# which is a first-class case here) -- this pipeline calls litellm on every
# scout/strategist/draft dispatch, so left at its default that banner would
# spam worker logs continuously. Cost-unknown-for-this-model is handled
# explicitly below (treated as free) so the banner adds nothing.
litellm.suppress_debug_info = True


class CostLimitExceeded(Exception):
    """Raised when an organization's LLM cost or token limit is breached."""
    pass

def midnight_utc_timestamp() -> int:
    """Returns the Unix timestamp for the next midnight UTC."""
    now = datetime.now(timezone.utc)
    midnight = (now + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return int(midnight.timestamp())


def _daily_tokens_key(org_id: int) -> str:
    return f'llm:tokens:{org_id}:{date.today().isoformat()}'


def _monthly_cost_key(org_id: int) -> str:
    return f'llm:cost_usd:{org_id}:{date.today().strftime("%Y-%m")}'


def _token_cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """USD cost of ``prompt_tokens``/``completion_tokens`` against ``model``.

    A model litellm has no pricing for (a self-hosted Ollama/custom-base-url
    model, an unrecognized provider prefix) raises rather than returning 0 --
    BYOK custom models are a first-class case here, so that must degrade to
    "cost unknown, treat as free" rather than crash the pipeline.
    """
    try:
        prompt_cost, completion_cost = litellm.cost_per_token(
            model=model, prompt_tokens=prompt_tokens, completion_tokens=completion_tokens
        )
        return prompt_cost + completion_cost
    except Exception:
        return 0.0


async def record_llm_usage(
    org_id: int,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    r: Optional[redis.Redis],
) -> float:
    """Unconditionally meter *actual* LLM usage into the org's spend counters.

    No cap enforcement here (that stays at persist_gate, per PRD V7 §5.3 --
    ``check_and_record_llm_usage`` below is the gated pre-dispatch check).
    This exists so the scout and strategist calls -- which persist_gate's
    per-draft estimate never accounted for -- still show up in the org's
    recorded daily-token / monthly-cost figures, which otherwise
    undercounted real spend by however much the scout/strategist calls
    cost. Returns the USD cost recorded (0.0 if ``r`` is None or the model
    has no known pricing).
    """
    if r is None:
        return 0.0
    total_tokens = int(prompt_tokens or 0) + int(completion_tokens or 0)
    if total_tokens <= 0:
        return 0.0
    token_cost = _token_cost_usd(model, prompt_tokens, completion_tokens)

    daily_key = _daily_tokens_key(org_id)
    month_key = _monthly_cost_key(org_id)
    pipe = r.pipeline()
    pipe.incrby(daily_key, total_tokens)
    pipe.expireat(daily_key, midnight_utc_timestamp())
    pipe.incrbyfloat(month_key, token_cost)
    await pipe.execute()
    return token_cost


async def check_and_record_llm_usage(
    org_id: int,
    estimated_tokens: int,
    model: str,
    r: redis.Redis,
    db: AsyncSession,
    llm_config: Optional[OrgLLMConfig] = None,
) -> None:
    """
    Called before every LLM dispatch in DraftGenerator (Node 5).
    Raises CostLimitExceeded if the org has hit its daily token or monthly cost limit.

    ``llm_config`` lets the caller pass an already-fetched ``OrgLLMConfig``
    (persist_gate fetches it once per run and reuses it across every draft
    in the loop) instead of this function re-querying the DB once per call
    -- a loop over N drafts used to mean N redundant identical queries.
    Passing ``None`` (the default) preserves the old fetch-every-time
    behaviour for any other caller.

    Teammate 2: Protects against runaway costs from high-volume Reddit matches.
    """
    if llm_config is None:
        llm_config = await get_org_llm_config(db, org_id)
    if not llm_config:
        return

    # Daily token check (Redis counter, resets at midnight UTC)
    daily_key = _daily_tokens_key(org_id)
    # Use await for redis-py async client
    daily_used_raw = await r.get(daily_key)
    daily_used  = int(daily_used_raw or 0)
    daily_breach = bool(
        llm_config.max_daily_llm_tokens
        and daily_used + estimated_tokens > llm_config.max_daily_llm_tokens
    )

    # Monthly USD cost check (running counter in Redis)
    month_key = _monthly_cost_key(org_id)
    month_cost_raw = await r.get(month_key)
    month_cost  = float(month_cost_raw or 0)

    # Calculate cost using litellm. Using estimated_tokens as prompt_tokens
    # since this check occurs BEFORE dispatch.
    #
    # NOTE: `litellm.completion_cost(prompt_tokens=..., completion_tokens=...)`
    # was removed from newer litellm releases (it now wants `prompt`/
    # `completion` strings or a full response object) -- `cost_per_token`
    # is litellm's token-count-based API and is what this pre-dispatch
    # estimate actually needs.
    token_cost = _token_cost_usd(model, estimated_tokens, 0)
    monthly_breach = bool(
        llm_config.max_monthly_llm_cost_usd
        and month_cost + token_cost > float(llm_config.max_monthly_llm_cost_usd)
    )

    # Record usage unconditionally, *before* raising on a breach: by the
    # time this is called the LLM call has already happened (this is a
    # pre-dispatch estimate guard, but persist_gate calls it with the
    # draft's already-generated text/tokens) -- the spend is real whether
    # or not it also trips a cap, so a tripped cap must not make the org's
    # recorded spend silently understate what was actually billed.
    pipe = r.pipeline()
    pipe.incrby(daily_key, estimated_tokens)
    pipe.expireat(daily_key, midnight_utc_timestamp())
    pipe.incrbyfloat(month_key, token_cost)
    await pipe.execute()

    if daily_breach:
        raise CostLimitExceeded(
            f'Daily LLM token limit reached ({llm_config.max_daily_llm_tokens} tokens)'
        )
    if monthly_breach:
        raise CostLimitExceeded(
            f'Monthly LLM cost limit reached (${llm_config.max_monthly_llm_cost_usd})'
        )
