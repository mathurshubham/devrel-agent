## 4. Core System Architecture

### 4.1 Backend API & Task Queue

The FastAPI backend handles CRUD via synchronous request-response cycles. All third-party I/O — Reddit scraping, LLM generation, PRAW publishing — is offloaded to Celery. Uvicorn never blocks on external I/O.

**Uvicorn launch command (corrected for reverse proxy):**

```bash
# Teammate 4: Required for Cloudflare tunnel, ngrok, and any reverse proxy.
# Without --proxy-headers, FastAPI reads the tunnel's internal IP instead of the real client IP,
# breaking CORS and user-level rate limiting.
uvicorn main:app --host 0.0.0.0 --port 8000 \
  --proxy-headers \
  --forwarded-allow-ips='*'
```

---

### 4.2 Celery Queue Topology & Worker Scaling Policy

> **⚠ WARNING:** Using a single Celery queue causes head-of-line blocking. Four isolated queues with independent worker pools are mandatory.

> **Teammate 1 — Clarification:** Nodes 3–6 of the LangGraph pipeline run **sequentially within a single `langgen` task invocation**. The LangGraph state machine manages node-to-node transitions in memory (or via its own optional checkpointing). Spawning a separate Celery task per node would introduce unacceptable Redis overhead and is explicitly prohibited.

| Queue | Task Types | Default Concurrency | Scaling Rule |
|-------|-----------|-------------------|--------------|
| `scraper` | Fetch Reddit posts, Triage Rule Tester dry-runs | 4 | 1 worker per 10 active campaigns. Max 2× CPU cores. |
| `langgen` | **Full LangGraph pipeline (Nodes 1–6 sequentially)**: Triage → Tokenize → Truncate → Draft → Score → Route | 8 | 1 worker per 5 orgs. I/O-bound — can exceed core count. Target: CPU × 2. |
| `praw_publish` | PRAW publish, Kill Switch deletions, idempotency key check | 2 | Keep low — sequential posting required. Max 4. |
| `maintenance` | Lock expiry, retention cron, counter snapshots, DLQ alerts, webhook event purge | 1 | Fixed at 1. Tasks are not idempotent-safe at concurrency > 1. |

**Scaling command:**

```bash
docker-compose up --scale worker_langgen=4 -d
```

---

### 4.3 LangGraph Pipeline — Full Node Definition

> **Teammate 1 — Confirmed:** Nodes 3–6 execute sequentially within a **single `langgen` Celery task**. LangGraph manages state transitions in memory within that worker process.

> **Teammate 3 — Keyword Matching Clarification:** Node 2 (KeywordMatcher) supports both **exact substring matching** (default) and **regex patterns** (opt-in per keyword, prefixed with `regex:`). The Campaign UI explicitly labels keyword entries with a `[regex]` badge when a regex prefix is detected. Example keywords array: `["RAG", "benchmark", "regex:eval(uation)?"]`.

| Node | Queue | Description |
|------|-------|-------------|
| **Node 1: RedditPostFetch** | `scraper` | Fetches posts from target subreddit via PRAW. Applies `comment_fetch_limit`, `include_op_context`, and `max_comment_chars`. Runs `UniqueConstraint(campaign_id, reddit_post_id)` check — skips already-processed posts. Output: `{post_id, post_url, post_title, post_text, comments[]}`. |
| **Node 2: KeywordMatcher** | `scraper` | Fast pre-filter against `campaign.keywords` JSONB array. Supports exact substring (default) and regex patterns (prefix `regex:`). Eliminates non-matches without an LLM call. Output: `{matched_keywords, pre_filter_pass: bool}`. |
| **Node 3: LLMIntentClassifier** | `langgen` | LLM classification call via LiteLLM. Assigns `confidence_score` (0.0–1.0) and `triage_reasoning`. Posts below 0.3 are discarded. Checks `SubredditSafetyProfile.require_manual_review`. |
| **Node 4: TokenizerAndTruncator** | `langgen` | Computes token budget using pre-computed `master_context_tokens` and `rulesets_token_count` (see §4.4). Progressively truncates: oldest comments first → summarize remaining → truncate Master Context tail if still over limit. Sets `truncation_applied` and `truncation_details`. |
| **Node 5: DraftGenerator** | `langgen` | Compiles final prompt payload. Checks LLM cost limits (see §4.8) before dispatch. Dispatches to LiteLLM. Persists: `ai_draft_text`, `model_used`, `model_payload_token_count`, `response_token_count`, `prompt_payload` (full JSONB), `prompt_template_version`. |
| **Node 6: ConfidenceGate** | `langgen` | Routes output: if auto-pilot eligible (confidence ≥ threshold AND Redis counter < daily_limit AND `SubredditSafetyProfile.allow_auto_pilot == true`) → dispatch to `praw_publish` queue. Otherwise → `status=PENDING` for HITL review. |

---

### 4.4 Context Window, Tokenizer & Token Budget (Model-Aware)

> **Teammate 1 — Chicken & Egg Problem:** `OrgPersona` can be saved before an LLM model is configured in `OrgLLMConfig`. Different models have different tokenizers (GPT-4o vs. Llama 3 count tokens differently). If the model changes after persona is saved, `master_context_tokens` becomes stale.

#### Solution: Model-Linked Token Counts + Redis Cache

```python
# backend/utils/tokenizer.py
from litellm import token_counter
import litellm

DEFAULT_MODEL = "gpt-4o"  # fallback if org has no LLM configured yet

def count_tokens(model: str, text: str) -> int:
    return token_counter(model=model, messages=[{'role': 'system', 'content': text}])

def update_persona_token_counts(
    persona: OrgPersona,
    model: str,           # passed from OrgLLMConfig.model_name at save time
) -> OrgPersona:
    """
    Recalculates pre-computed token counts for the given model.
    Called on: (1) persona save, (2) LLM model change.
    """
    persona.master_context_tokens = count_tokens(model, persona.master_context or '')
    persona.rulesets_token_count  = count_tokens(model, str(persona.rulesets_dos_donts or ''))
    return persona

def compute_token_budget(model: str, persona: OrgPersona, safety_reserve: int = 500) -> int:
    limit = litellm.get_max_tokens(model)
    return limit - persona.master_context_tokens - persona.rulesets_token_count - safety_reserve
```

#### LLM Model Change Trigger

```python
# PATCH /api/org/llm-config — when model_name changes, re-compute persona tokens
async def update_llm_config(payload: LLMConfigUpdate, session=Depends(get_current_session)):
    old_config = await db.get(OrgLLMConfig, session['org_id'])
    model_changed = old_config and old_config.model_name != payload.model_name

    await db.merge(OrgLLMConfig(**payload.dict(), org_id=session['org_id']))

    if model_changed:
        persona = await db.get(OrgPersona, session['org_id'])
        if persona:
            persona = update_persona_token_counts(persona, payload.model_name)
            await db.merge(persona)
            await write_audit_log(action='PERSONA_TOKENS_RECALCULATED',
                                  details={'new_model': payload.model_name})
```

> **ℹ NOTE:** If an org has no `OrgLLMConfig` yet (persona saved before model selection), token counts are calculated using the `DEFAULT_MODEL` fallback and recalculated the moment a model is configured.

#### Persona Save Validation — Node 4 Edge Case Guard

> **Teammate 4:** If `master_context_tokens + rulesets_token_count` already exceeds 80% of the model's context window before any Reddit comments are added, Node 4 will crash or produce a useless prompt with no room for thread content.

```python
# PATCH /api/org/persona — validate before saving
async def update_persona(payload: PersonaUpdate, session=Depends(get_current_session)):
    llm_config = await db.get(OrgLLMConfig, session['org_id'])
    model = llm_config.model_name if llm_config else DEFAULT_MODEL
    model_limit = litellm.get_max_tokens(model)

    ctx_tokens     = count_tokens(model, payload.master_context or '')
    ruleset_tokens = count_tokens(model, str(payload.rulesets_dos_donts or ''))
    total          = ctx_tokens + ruleset_tokens

    # Reject save if persona alone consumes > 80% of the model's context window.
    if total > model_limit * 0.80:
        raise HTTPException(
            status_code=422,
            detail=(
                f'Your Master Context + Rulesets use {total:,} tokens, which exceeds '
                f'80% of {model}\'s {model_limit:,}-token limit. '
                f'Reduce your content to leave room for Reddit thread context.'
            )
        )
    # Proceed with save and update pre-computed counts
    ...
```

---

### 4.5 Error Handling, Retries & Dead Letter Queue

| Failure Type | Retry Strategy | Final Draft State | UI Behavior |
|-------------|----------------|-------------------|-------------|
| LLM / Reddit timeout | Exponential backoff: 30s → 2m → 8m → 32m (4 attempts) | `FAILED` + `failed_reason` | Red badge; toast alert |
| Invalid API key (401/403) | No retry. Immediate DLQ. | `FAILED` + `failed_reason` | Warning on Vault page |
| Reddit 429 | Pause account queue; resume at `rate_limit_reset_at` via circuit breaker (§4.6) | Task re-queued | Yellow badge on account |
| Context window exceeded | Apply truncation (Node 4); retry once | Draft generated with truncation note | Truncation badge on draft |
| LLM cost limit exceeded | No retry. | `FAILED_COST_LIMIT` | Org-level cost alert banner |
| PRAW OAuth expired | Distributed Redis lock → one worker refreshes → others read cache | Transparent retry | None (transparent) |
| Clerk webhook failure | Exponential backoff; DLQ after 5 Clerk delivery attempts | Super Admin alerted | Super Admin dashboard |

---

### 4.6 Rate Limiting, Circuit Breaker & PRAW Distributed Lock

> **Teammate 3 — Jitter:** Add jitter to the polling fallback in the distributed lock to prevent thundering-herd when many workers wait simultaneously.

```python
# backend/utils/praw_token.py
import redis, time, random

LOCK_KEY   = 'praw:token_refresh_lock:{account_id}'
TOKEN_KEY  = 'praw:access_token:{account_id}'
LOCK_TTL   = 5_000    # 5 second lock timeout (ms)
TOKEN_TTL  = 55 * 60  # 55 minutes

def get_praw_token(account_id: int, reddit_account, r: redis.Redis) -> str:
    cached = r.get(TOKEN_KEY.format(account_id=account_id))
    if cached:
        return cached.decode()

    lock_key = LOCK_KEY.format(account_id=account_id)
    lock_acquired = r.set(lock_key, '1', nx=True, px=LOCK_TTL)

    if lock_acquired:
        try:
            new_token = _refresh_praw_token(reddit_account)
            r.setex(TOKEN_KEY.format(account_id=account_id), TOKEN_TTL, new_token)
            return new_token
        finally:
            r.delete(lock_key)
    else:
        # Polling with jitter to avoid thundering herd (Teammate 3)
        for _ in range(10):
            time.sleep(0.1 + random.uniform(0, 0.05))   # 100–150ms with jitter
            token = r.get(TOKEN_KEY.format(account_id=account_id))
            if token:
                return token.decode()
        raise RuntimeError(f'PRAW token refresh timed out for account {account_id}')
```

**Rate limiting strategy:**

- **Per-account counter (Redis):** `praw:posts:{account_id}:{YYYY-MM-DD}` — `INCR` + `EXPIREAT midnight UTC` on each publish call.
- **Global platform counter:** `praw:global_posts:{YYYY-MM-DD}` — aggregates all PRAW calls. Alert at 80% of estimated global limit.
- **Token Bucket:** `praw_publish` workers enforce 2-second minimum delay between posts from the same account via Redis sorted-set rate limiter.
- **Circuit Breaker:** After 3 consecutive 429 responses, account is paused in PostgreSQL. Circuit auto-closes at `rate_limit_reset_at`.

> **Teammate 3 — Redis Queue Priority Note:** When multiple campaigns have the same ZSET score (same next-poll timestamp), Redis returns them in lexicographic order by member ID. This is deterministic and acceptable behavior. The order does not affect correctness.

---

### 4.7 FastAPI User-Level Rate Limiting

> **Teammate 2:** The platform has no protection against users spamming expensive endpoints like `/campaigns/test-rules`, which triggers Reddit API + LLM calls on every request.

```python
# backend/main.py
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

limiter = Limiter(key_func=get_remote_address, storage_uri=os.environ['REDIS_URL'])
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
```

| Endpoint | Limit | Rationale |
|----------|-------|-----------|
| `POST /api/campaigns/{id}/test-rules` | 10 / minute / user | Triggers Reddit API + LLM calls |
| `POST /api/drafts/{id}/publish` | 20 / minute / user | Triggers PRAW API call |
| `POST /api/org/llm-config` | 5 / minute / user | Triggers token re-computation |
| `GET /api/drafts` (inbox) | 60 / minute / user | Paginated DB query |
| `POST /api/admin/promote-super-admin` | 5 / minute / user | Sensitive admin action |

---

### 4.8 LLM Cost Protection

> **Teammate 2:** Without cost guards, a campaign matching 1,000 posts in a day triggers 1,000 LLM calls. This could bankrupt a self-hoster or destabilize a SaaS tenant.

```python
# backend/utils/cost_guard.py

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
    """
    llm_config = await db.get(OrgLLMConfig, org_id)
    if not llm_config:
        return

    # Daily token check (Redis counter, resets at midnight UTC)
    daily_key   = f'llm:tokens:{org_id}:{date.today().isoformat()}'
    daily_used  = int(r.get(daily_key) or 0)

    if llm_config.max_daily_llm_tokens and \
       daily_used + estimated_tokens > llm_config.max_daily_llm_tokens:
        raise CostLimitExceeded('Daily LLM token limit reached')

    # Monthly USD cost check (running counter in Redis)
    month_key   = f'llm:cost_usd:{org_id}:{date.today().strftime("%Y-%m")}'
    month_cost  = float(r.get(month_key) or 0)
    token_cost  = litellm.completion_cost(model=model, completion_tokens=estimated_tokens)

    if llm_config.max_monthly_llm_cost_usd and \
       month_cost + token_cost > llm_config.max_monthly_llm_cost_usd:
        raise CostLimitExceeded('Monthly LLM cost limit reached')

    # Record usage atomically
    pipe = r.pipeline()
    pipe.incrby(daily_key, estimated_tokens)
    pipe.expireat(daily_key, midnight_utc_timestamp())
    pipe.incrbyfloat(month_key, token_cost)
    pipe.execute()
```

When `CostLimitExceeded` is raised in Node 5, the draft is set to status `FAILED_COST_LIMIT` and an AuditLog entry is written. The Inbox displays an org-level cost alert banner.

---

### 4.9 Redis Security & Persistence

| Concern | Requirement |
|---------|-------------|
| Authentication | `requirepass` + ACL lists. Celery worker ACL: read/write on `praw:*`, `autopilot:*`, `llm:*`, Celery queues, `campaign:scheduler`. Read-only ACL for monitoring. |
| TLS | TLS mandatory for all Redis connections in production. Same-host Docker Compose: optional. Cloud/hosted: mandatory. |
| Secrets in Redis | Only short-lived PRAW OAuth access tokens (TTL 55m) — NOT client secrets. The underlying `encrypted_secret` is **never** written to Redis. |
| Persistence | RDB snapshot every 60s. AOF enabled (`appendfsync everysec`). If Redis restarts, counters rebuild from 0 (conservative — safe for rate limiting). |
| Managed Redis | AWS ElastiCache (cluster mode) or Redis Cloud for hosted SaaS. |
| Passwords | Use Docker secrets or `chmod 600 .env` for `.env` files. `REDIS_PASSWORD` must be minimum 32 random characters. |

---

### 4.10 Campaign Polling — Redis Priority Queue

```python
# Redis Sorted Set: campaign:scheduler (key) → ZSET
# Score = Unix timestamp of next poll (float), Member = campaign_id (string)

# Enqueue a campaign when created or re-activated:
next_poll = time.time() + campaign.poll_frequency_minutes * 60
redis.zadd('campaign:scheduler', {str(campaign.id): next_poll})

# Celery Beat fires one task every 60 seconds:
def scheduler_tick():
    now     = time.time()
    due_ids = redis.zrangebyscore('campaign:scheduler', 0, now)
    if not due_ids:
        return
    redis.zrem('campaign:scheduler', *due_ids)     # remove before dispatch (no double-fire)
    for campaign_id in due_ids:
        campaign = db.get(Campaign, campaign_id)
        if campaign and campaign.status == CampaignStatus.ACTIVE:
            # Check org is_active before dispatching
            if campaign.organization.is_active:
                scraper_task.apply_async(args=[campaign_id], queue='scraper')
            next_ts = now + campaign.poll_frequency_minutes * 60
            redis.zadd('campaign:scheduler', {str(campaign_id): next_ts})

# Pausing: redis.zrem('campaign:scheduler', str(campaign_id))
# Re-activating: redis.zadd('campaign:scheduler', {str(campaign_id): time.time() + freq*60})

# NOTE (Teammate 3): When multiple campaigns share the same score, Redis returns them in
# lexicographic order by member (campaign_id string). This is deterministic and correct.
```

---

## 5. Feature Specifications

### 5.1 Security & BYOK Vaults

All vault secrets use Fernet encryption (§3.4). The UI never exposes raw secrets after initial entry. Vault pages show only provider name / Reddit username with a "Rotate Secret" action.

- **LLM Config (`OrgLLMConfig`):** `provider`, `model_name`, `custom_base_url` (plaintext), `encrypted_api_key` (Fernet, `Text` column), `encrypted_with_key_version`, `max_daily_llm_tokens`, `max_monthly_llm_cost_usd`.
- **Reddit Credentials (`RedditAccount`):** `username` + `client_id` (plaintext), `encrypted_secret` (Fernet, `Text` column — aligned with `OrgLLMConfig` per Teammate 3), `encrypted_with_key_version`, `is_shared_with_team`, `is_active`, `deleted_at` (soft delete).

---

### 5.2 Subreddit Safety Profiles

Per-org safety overrides for specific subreddits. Checked at LangGraph Node 6 (ConfidenceGate) before any auto-publish.

| Field | Type | Description |
|-------|------|-------------|
| `subreddit_name` | `String(100)` | Target subreddit (unique per org). |
| `allow_auto_pilot` | `Boolean` | If `false`, ALL drafts routed to HITL regardless of confidence. Overrides campaign-level setting. |
| `max_daily_posts` | `Integer` | Per-subreddit daily cap overriding campaign's `auto_pilot_daily_limit`. |
| `require_manual_review` | `Boolean` | Forces human review even when auto-pilot is globally enabled. |
| `notes` | `Text` | Admin explanation (e.g., "Community bans promotional accounts on first offence"). |

**Pre-populated seed suggestions:**

```python
SUGGESTED_PROFILES = [
    { 'subreddit': 'r/netsec',     'allow_auto_pilot': False, 'max_daily_posts': 1 },
    { 'subreddit': 'r/privacy',    'allow_auto_pilot': False, 'max_daily_posts': 1 },
    { 'subreddit': 'r/LLMDevs',    'allow_auto_pilot': True,  'max_daily_posts': 3 },
    { 'subreddit': 'r/LocalLLaMA', 'allow_auto_pilot': True,  'max_daily_posts': 3 },
]
```

---

### 5.3 Context Engine & Prompt Library

| Field | Type | Description |
|-------|------|-------------|
| `master_context` | `Text` | Core product knowledge: elevator pitch, problem/solution, target audience, advantages. |
| `master_context_tokens` | `Integer` | Pre-computed for current model. Recalculated on persona save and on LLM model change. |
| `rulesets_dos_donts` | `JSONB` | `{"dos": [...], "donts": [...]}` — structured for reliable LangGraph iteration. |
| `rulesets_token_count` | `Integer` | Pre-computed for current model. Recalculated on persona save and on LLM model change. |
| `tone_guidelines` | `Text` | Conversational style: e.g., "Write as a peer. Use technical jargon. Under 200 words." |

**Prompt Library Templates:**

| Template | Category | Output |
|----------|----------|--------|
| Product to Master Context | Master Context | Converts messy notes/website copy into a structured 5-part knowledge base |
| Tone & Ruleset Extractor | Rulesets | Generates Do's & Don'ts in required JSONB format |
| Subreddit Keyword Finder | Keywords | Top 5 subreddits + 10 high-intent complaint keywords |
| Competitor Analysis Context | Master Context | Extracts competitive positioning statements |

Templates carry a `version` integer. Orgs that previously copied a template see an "Update Available" banner in the Prompt Library modal.

---

### 5.4 Campaign Management & Triage Rule Tester

A Campaign defines one monitoring target: one subreddit, one keyword set, one schedule. Multiple campaigns per org (including multiple targeting the same subreddit with different keyword sets). Each Campaign requires a human-readable `name`.

**Keyword Matching:** Supports exact substring (default) and regex patterns (prefix keyword with `regex:`). Example: `["RAG", "benchmark", "regex:eval(uation)?"]`. The Campaign creation UI labels regex keywords with a `[regex]` badge.

**Triage Rule Tester response contract:**

```json
{
  "tested_at": "2025-11-01T10:00:00Z",
  "subreddit": "r/LLMDevs",
  "posts_tested": 20,
  "results": [
    {
      "post_title":       "Anyone benchmarking RAG pipelines?",
      "post_url":         "https://reddit.com/r/LLMDevs/comments/abc123",
      "matched_keywords": ["RAG", "benchmark"],
      "confidence_score": 0.91,
      "would_trigger":    true,
      "safety_override":  false,
      "triage_reasoning": "Post discusses RAG evaluation accuracy — direct intent match"
    }
  ]
}
```

---

### 5.5 Reddit Comment Depth Configuration

| Field | Default | Description |
|-------|---------|-------------|
| `comment_fetch_limit` | `10` | Maximum top-level comments to fetch (by Reddit "top" sort). |
| `include_op_context` | `true` | Always include original post author's comments, regardless of limit. |
| `max_comment_chars` | `500` | Per-comment character truncation before tokenizing. |

> **ℹ NOTE:** For models with large context windows (e.g., Gemini 1.5 Pro: 1M tokens), `comment_fetch_limit` can be safely increased. Node 4 (TokenizerAndTruncator) handles any remaining overflow.

---

### 5.6 Inbox, Concurrency & Auto-Pilot

**HITL Workflow:**

1. Draft enters `PENDING` state. Records: `ai_draft_text`, `model_used`, `confidence_score`, `triage_reasoning`, `prompt_payload`, `prompt_template_version`, token counts, `truncation_applied`.
2. DevRel opens draft in shadcn `Sheet`. Backend atomically stamps `locked_by_user_id` and `locked_at`.
3. Other users see: "Currently being reviewed by [name] — lock expires in X minutes."
4. Admin Force Takeover: `AlertDialog` confirmation. AuditLog: `action=LOCK_FORCE_TAKEN`.
5. Lock TTL: 15 minutes. Maintenance worker clears expired locks every 5 minutes.
6. DevRel edits draft, selects Reddit account, clicks Publish → optimistic UI shows "Publishing..."
7. On PRAW success: `status=PUBLISHED`, `live_reddit_url`, `published_at` set. AuditLog written.
8. On PRAW failure: `status=FAILED`, `failed_reason` stored. Toast error with retry option.

**Auto-Pilot Guardrails:**

- ADMIN role only. Requires `auto_pilot_confidence_threshold` (default: 0.95).
- Fires ONLY when: `confidence >= threshold` AND Redis `autopilot` counter `< daily_limit` AND `SubredditSafetyProfile.allow_auto_pilot == true`.
- Daily counter in Redis: `autopilot:count:{campaign_id}:{YYYY-MM-DD}` with `EXPIREAT midnight UTC`.
- `is_auto_pilot_published=true` on `DraftReply`. AuditLog `user_id=NULL` for all auto-pilot entries.

---

### 5.7 Kill Switch — Rate-Limit Aware Deletion

> **Teammate 2:** Kill Switch deletions must be routed through the `praw_publish` queue with the same 2-second inter-request delay to prevent Reddit from rate-limiting or banning the account during mass deletion.

**Kill Switch execution flow:**

1. Admin clicks Kill Switch. FastAPI immediately sets `Campaign.status=PAUSED`. AuditLog: `action=KILLSWITCH_ACTIVATED`.
2. All pending Celery tasks for this campaign are revoked (`celery.revoke(task_id, terminate=True)`).
3. If "Delete recent auto-posts" is selected: query `DraftReply WHERE campaign_id=X AND is_auto_pilot_published=true AND published_at >= NOW() - 1 hour`.
4. For each matching draft: dispatch a `praw_delete` task to the **`praw_publish` queue** — same queue, same 2-second inter-post delay and circuit-breaker logic as normal publishing.
5. Each `praw_delete` task: calls PRAW to delete Reddit comment → sets `DraftReply.status=DELETED_BY_KILLSWITCH` → writes AuditLog entry.
6. UI shows live deletion progress via `GET /api/campaigns/{id}/killswitch-status`.

---

### 5.8 TryEval Native Integration & Export Contract

**Export JSON — v1.0 Contract:**

```json
{
  "export_version":  "1.0",
  "exported_at":     "2025-11-01T12:00:00Z",
  "org_name":        "TryEval",
  "persona": {
    "master_context":    "...",
    "rulesets":          { "dos": ["..."], "donts": ["..."] },
    "tone_guidelines":   "...",
    "persona_updated_at":"2025-10-15T09:00:00Z"
  },
  "drafts": [
    {
      "draft_id":               42,
      "reddit_post_url":        "https://reddit.com/r/LLMDevs/comments/abc",
      "original_thread":        "...",
      "generated_reply":        "...",
      "model_used":             "gemini-1.5-flash",
      "prompt_template_version":"triage_v2",
      "model_payload_tokens":   2847,
      "confidence_score":       0.91,
      "truncation_applied":     false,
      "status":                 "PUBLISHED",
      "live_reddit_url":        "https://reddit.com/...",
      "is_auto_pilot":          false
    }
  ],
  "benchmark_against": ["gpt-4o", "claude-3-5-sonnet-20241022"]
}
```

> **ℹ NOTE:** `prompt_template_version` is included in the export to allow TryEval to group benchmarks by prompt version, enabling meaningful A/B comparisons across prompt iterations.

---