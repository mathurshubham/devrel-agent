from datetime import date, datetime, timezone, timedelta
import redis.asyncio as redis
from sqlalchemy.ext.asyncio import AsyncSession
import litellm
from backend.models import OrgLLMConfig
from backend.utils.org_lookups import get_org_llm_config

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

async def check_and_record_llm_usage(
    org_id: int,
    estimated_tokens: int,
    model: str,
    r: redis.Redis,
    db: AsyncSession,
) -> None:
    """
    Called before every LLM dispatch in DraftGenerator (Node 5).
    Raises CostLimitExceeded if the org has hit its daily token or monthly cost limit.
    
    Teammate 2: Protects against runaway costs from high-volume Reddit matches.
    """
    llm_config = await get_org_llm_config(db, org_id)
    if not llm_config:
        return

    # Daily token check (Redis counter, resets at midnight UTC)
    daily_key   = f'llm:tokens:{org_id}:{date.today().isoformat()}'
    # Use await for redis-py async client
    daily_used_raw = await r.get(daily_key)
    daily_used  = int(daily_used_raw or 0)

    if llm_config.max_daily_llm_tokens and \
       daily_used + estimated_tokens > llm_config.max_daily_llm_tokens:
        raise CostLimitExceeded(
            f'Daily LLM token limit reached ({llm_config.max_daily_llm_tokens} tokens)'
        )

    # Monthly USD cost check (running counter in Redis)
    month_key   = f'llm:cost_usd:{org_id}:{date.today().strftime("%Y-%m")}'
    month_cost_raw = await r.get(month_key)
    month_cost  = float(month_cost_raw or 0)
    
    # Calculate cost using litellm. Using estimated_tokens as prompt_tokens
    # since this check occurs BEFORE dispatch.
    #
    # NOTE: `litellm.completion_cost(prompt_tokens=..., completion_tokens=...)`
    # was removed from newer litellm releases (it now wants `prompt`/
    # `completion` strings or a full response object) -- `cost_per_token`
    # is litellm's token-count-based API and is what this pre-dispatch
    # estimate actually needs. A model litellm has no pricing for (a
    # self-hosted Ollama/custom-base-url model, an unrecognized provider
    # prefix) raises rather than returning 0 -- BYOK custom models are a
    # first-class case here, so that must degrade to "cost unknown, treat
    # as free" rather than crash the pipeline's persist_gate.
    try:
        prompt_cost, completion_cost = litellm.cost_per_token(
            model=model, prompt_tokens=estimated_tokens, completion_tokens=0
        )
        token_cost = prompt_cost + completion_cost
    except Exception:
        token_cost = 0.0

    if llm_config.max_monthly_llm_cost_usd and \
       month_cost + token_cost > float(llm_config.max_monthly_llm_cost_usd):
        raise CostLimitExceeded(
            f'Monthly LLM cost limit reached (${llm_config.max_monthly_llm_cost_usd})'
        )

    # Record usage atomically
    pipe = r.pipeline()
    pipe.incrby(daily_key, estimated_tokens)
    pipe.expireat(daily_key, midnight_utc_timestamp())
    pipe.incrbyfloat(month_key, token_cost)
    await pipe.execute()
