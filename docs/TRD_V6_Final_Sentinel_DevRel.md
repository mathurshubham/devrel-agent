# Technical Requirement Document — OSS DevRel AI Agent
## Version 6.0 · FINAL · Code Name: Sentinel / TryEval DevRel

> **Status:** APPROVED — READY FOR DEVELOPMENT  
> **Classification:** Confidential — Internal Development Use Only  
> **This document supersedes all prior versions (V1–V5) and is the single source of truth for the development team.**

---

## Changelog

| Version | Key Changes | Status |
|---------|-------------|--------|
| 1.0 | Initial concepts and basic schema | Superseded |
| 2.0 | Auth spec, BYOK vaults, Auto-Pilot, schema overhaul | Superseded |
| 3.0 | Clerk integration, Docker spec, TryEval contract | Superseded |
| 4.0 | Observability, GDPR, Celery topology, GIN indexes, draft metadata, Fernet, prompt provenance, contract tests | Superseded |
| 5.0 | Subreddit Safety Profiles, LangGraph node map, comment-depth config, worker scaling, Super Admin API, Kill Switch rate-limit queue, ENCRYPTION_SECRET validation, master_context_tokens, PRAW distributed lock, Redis priority scheduler | Superseded |
| **6.0** | **Tokenizer chicken-and-egg fix + Redis cache strategy; ENABLE_METRICS observability toggle; LangGraph/Celery boundary clarification; LLM cost protection (max_daily_llm_tokens); FastAPI rate limiting (slowapi); Celery publish idempotency key; prompt_template_version on DraftReply; FTS index on draft text; webhook replay-attack timestamp guard; docker-compose.lite.yml; Uvicorn proxy headers; Node 4 persona-save validation; keyword matching clarification; RedditAccount.encrypted_secret → Text; startup validation test; Redis security note; confidence explanation UI** | **FINAL** |

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Technology Stack](#2-technology-stack)
3. [Authentication & Authorization — Clerk](#3-authentication--authorization--clerk)
   - 3.1 Clerk Architecture & Middleware
   - 3.2 Session, Token & Revocation Strategy
   - 3.3 RBAC Role Mapping
   - 3.4 Encryption Implementation — Fernet + Startup Validation
   - 3.5 Encryption Key Lifecycle & KMS Guidance
   - 3.6 Super Admin Layer — UI & Promotion API
4. [Core System Architecture](#4-core-system-architecture)
   - 4.1 Backend API & Task Queue
   - 4.2 Celery Queue Topology & Worker Scaling Policy
   - 4.3 LangGraph Pipeline — Full Node Definition
   - 4.4 Context Window, Tokenizer & Token Budget (Model-Aware)
   - 4.5 Error Handling, Retries & Dead Letter Queue
   - 4.6 Rate Limiting, Circuit Breaker & PRAW Distributed Lock
   - 4.7 FastAPI User-Level Rate Limiting
   - 4.8 LLM Cost Protection
   - 4.9 Redis Security & Persistence
   - 4.10 Campaign Polling — Redis Priority Queue
5. [Feature Specifications](#5-feature-specifications)
   - 5.1 Security & BYOK Vaults
   - 5.2 Subreddit Safety Profiles
   - 5.3 Context Engine & Prompt Library
   - 5.4 Campaign Management & Triage Rule Tester
   - 5.5 Reddit Comment Depth Configuration
   - 5.6 Inbox, Concurrency & Auto-Pilot
   - 5.7 Kill Switch — Rate-Limit Aware Deletion
   - 5.8 TryEval Native Integration & Export Contract
6. [Security Specification](#6-security-specification)
7. [Observability & Monitoring](#7-observability--monitoring)
8. [Compliance, GDPR & Data Governance](#8-compliance-gdpr--data-governance)
9. [Non-Functional Requirements](#9-non-functional-requirements)
10. [Open-Source & Docker Self-Hosting](#10-open-source--docker-self-hosting)
11. [Frontend UX Specifications](#11-frontend-ux-specifications)
12. [SQLAlchemy V6 Schema — Final](#12-sqlalchemy-v6-schema--final)
13. [Test Plan, CI/CD & Contract Tests](#13-test-plan-cicd--contract-tests)

---

## 1. Executive Summary

This document defines the complete, authoritative architecture for the OSS DevRel AI Agent — a self-hostable, multi-tenant platform that automates Developer Relations on Reddit using AI. It uses LangGraph to monitor communities, triage relevant discussions, and draft contextual replies governed by organization-specific brand rulesets. Human-in-the-Loop (HITL) approval is the default publishing mode.

The platform serves simultaneously as a productivity tool for DevRel teams and as TryEval's primary distribution channel within the developer community. Users who configure the platform and see its output can seamlessly export drafts to TryEval for LLM benchmarking — embedding TryEval's value proposition directly into the workflow.

**V6.0 resolves all remaining open issues** raised across four teammate reviews:

- **Tokenizer chicken-and-egg**: token counts now invalidated and recalculated when the org's LLM model changes; Redis cache fallback for model-aware counts without blocking persona saves.
- **LLM cost protection**: hard daily token and monthly cost limits on `OrgLLMConfig` with a new `FAILED_COST_LIMIT` draft status.
- **FastAPI user-level rate limiting**: `slowapi` middleware protecting high-cost endpoints.
- **Celery publish idempotency**: Redis lock key `praw_publish:{draft_id}` prevents double-posting on task retry.
- **Prompt version tracking**: `prompt_template_version` field on `DraftReply` for TryEval benchmarking.
- **Full-text search**: GIN tsvector index on `ai_draft_text` and `original_text`.
- **Webhook replay attack guard**: `svix-timestamp` checked before DB idempotency lookup; requests older than 5 minutes rejected.
- **Docker Compose Lite**: `docker-compose.lite.yml` for low-resource self-hosting (single combined worker, 2 concurrency).
- **Uvicorn proxy headers**: `--proxy-headers --forwarded-allow-ips='*'` for Cloudflare tunnel and ngrok compatibility.
- **Node 4 persona save validation**: persona save rejected if Master Context + Rulesets > 80% of model's context window.
- **Observability toggle**: `ENABLE_METRICS=true/false` makes Prometheus/Grafana optional for lightweight OSS deployments.
- **Keyword matching clarified**: supports substring and regex patterns; documented in UI.

---

## 2. Technology Stack

| Layer | Technology | Version / Notes |
|-------|------------|-----------------|
| Frontend | Next.js (App Router), React, TailwindCSS, shadcn/ui, TanStack Table, React Query | Next.js 15+. Optimistic UI for publish actions. |
| Auth | Clerk (`@clerk/nextjs`) | Full lifecycle: sessions, RBAC, MFA, invitations, password reset, org management. |
| Backend | FastAPI (Python 3.11+), Uvicorn | Async-native. `--proxy-headers --forwarded-allow-ips='*'` for reverse proxy support. |
| Rate Limiting | `slowapi` (FastAPI middleware) | Per-user, per-endpoint rate limits backed by Redis. |
| Database | PostgreSQL 15 (JSONB + GIN + FTS indexes) | Relational integrity + queryable JSON + full-text search on draft content. |
| Cache / Queue | Redis 7 (TLS + AUTH + ACLs + AOF) | Celery broker, counters, PRAW token cache, circuit-breaker state, priority scheduler, FTS fallback. |
| ORM + Migrations | SQLAlchemy 2.0 (Async) + Alembic | Alembic auto-runs on container start. |
| AI Abstraction | LiteLLM + `tiktoken` / LiteLLM `token_counter` | Single interface for all providers. Token counting before every dispatch. |
| Agentic Framework | LangGraph | 6-node pipeline. Nodes 3–6 execute sequentially inside a single `langgen` Celery task. |
| Workers | Celery — 4 isolated queues | `scraper`, `langgen`, `praw_publish`, `maintenance`. |
| Scheduler | Celery Beat + Redis Sorted Set | Drift-free campaign scheduling via ZSET priority queue. |
| Reddit API | PRAW | OAuth2 tokens cached in Redis (55-min TTL). Refresh protected by distributed lock. |
| Encryption | `cryptography` — Fernet | AES-128-CBC + HMAC-SHA256. Startup validation enforces 64-hex-char secret. |
| Observability | Prometheus + Grafana + Sentry + Structured JSON Logging | Prometheus/Grafana optional via `ENABLE_METRICS` toggle. Structured logs mandatory. |
| Infrastructure | Docker + Docker Compose v2 | Full stack (`docker-compose.yml`) and lite (`docker-compose.lite.yml`) variants. |

---

## 3. Authentication & Authorization — Clerk

### 3.1 Clerk Architecture & Middleware

Authentication is fully delegated to Clerk. The platform does **not** implement custom JWT issuance, password hashing, or invitation token generation. Clerk is the identity source of truth; PostgreSQL mirrors it via signed webhook events.

```typescript
// middleware.ts
import { clerkMiddleware, createRouteMatcher } from '@clerk/nextjs/server';

const isProtected  = createRouteMatcher(['/dashboard(.*)']);
const isAdminRoute = createRouteMatcher(['/dashboard/settings(.*)', '/admin(.*)']);

export default clerkMiddleware(async (auth, req) => {
  const { orgId, orgRole } = await auth();
  if (isProtected(req)) {
    await auth.protect();
    if (!orgId) return Response.redirect(new URL('/select-org', req.url));
  }
  if (isAdminRoute(req) && orgRole !== 'org:admin')
    return Response.redirect(new URL('/dashboard', req.url));
});

export const config = {
  matcher: [
    '/((?!_next|.*\\.(?:html?|css|js(?!on)|png|gif|svg|ico)).*)',
    '/(api|trpc)(.*)',
  ],
};
```

#### Webhook Sync, Idempotency & Replay Attack Guard

> **⚠ WARNING — Teammate 4:** The `ProcessedWebhookEvent` table is purged after 30 days. A replay attack replaying a captured payload after 30 days would bypass idempotency. The `svix-timestamp` header must be checked **before** the DB lookup and requests older than 5 minutes must be rejected.

```typescript
// app/api/webhooks/clerk/route.ts
import { Webhook } from 'svix';

export async function POST(req: Request) {
  const WEBHOOK_SECRET = process.env.CLERK_WEBHOOK_SECRET!;
  const hdrs = await headers();

  // ── Replay attack guard (Teammate 4) ──────────────────────────────────────
  const svixTimestamp = hdrs.get('svix-timestamp');
  if (!svixTimestamp) return Response.json({ error: 'Missing timestamp' }, { status: 400 });
  const ageMs = Date.now() - Number(svixTimestamp) * 1000;
  if (ageMs > 5 * 60 * 1000) {
    return Response.json({ error: 'Webhook timestamp too old — replay rejected' }, { status: 400 });
  }

  // ── HMAC signature verification ───────────────────────────────────────────
  const wh = new Webhook(WEBHOOK_SECRET);
  let evt;
  try {
    evt = wh.verify(await req.text(), {
      'svix-id':        hdrs.get('svix-id')!,
      'svix-timestamp': svixTimestamp,
      'svix-signature': hdrs.get('svix-signature')!,
    });
  } catch {
    return Response.json({ error: 'Invalid signature' }, { status: 400 });
  }

  // ── Idempotency (Teammate 3: use upsert / on_conflict_do_nothing) ─────────
  // Use INSERT ... ON CONFLICT DO NOTHING to avoid catching generic exceptions.
  const eventId = hdrs.get('svix-id')!;
  const inserted = await db.$executeRaw`
    INSERT INTO processed_webhook_events (event_id, event_type, processed_at)
    VALUES (${eventId}, ${evt.type}, NOW())
    ON CONFLICT (event_id) DO NOTHING
  `;
  if (inserted === 0) {
    return Response.json({ ok: true, skipped: 'duplicate' });
  }

  switch (evt.type) {
    case 'user.created':         await syncUser(evt.data);       break;
    case 'user.updated':         await updateUser(evt.data);     break;
    case 'user.deleted':         await deactivateUser(evt.data); break;
    case 'organization.created': await syncOrg(evt.data);        break;
    case 'organizationMembership.created': await linkUserToOrg(evt.data); break;
    case 'organization.deleted': await deactivateOrg(evt.data);  break;
  }
  return Response.json({ received: true });
}
```

| Clerk Event | DB Action | Notes |
|-------------|-----------|-------|
| `user.created` | `INSERT users (clerk_id, email, role=MEMBER)` | Triggers onboarding |
| `user.updated` | `UPDATE users SET email, last_login_at` | Syncs email changes |
| `user.deleted` | `UPDATE users SET is_active=false` | Soft delete |
| `organization.created` | `INSERT organizations (clerk_org_id, name)` | Triggers onboarding wizard |
| `organizationMembership.created` | `UPDATE users SET org_id, role` | Links user to org |
| `organization.deleted` | `UPDATE organizations SET is_active=false` | Cascades to suspend campaigns |

---

### 3.2 Session, Token & Revocation Strategy

| Concern | Strategy |
|---------|----------|
| Access Token Expiry | Short-lived Clerk JWTs (~60 seconds). FastAPI caches Clerk JWKS with 5-minute TTL. |
| Token Refresh | Silent refresh handled by Clerk frontend SDK. No custom implementation required. |
| Revocation on Offboarding | Admin deactivates user → `clerk.sessions.revoke_session(session_id)` → active session invalidated immediately. |
| Client Storage | Clerk uses **HttpOnly cookies** by default. `localStorage` token storage is **explicitly prohibited**. |
| MFA | Enforced for `org:admin` via Clerk Dashboard policy. Recommended for `org:member`. |
| Invitations | `organization.inviteMember({ emailAddress, role })` from `useOrganization()`. Revocation via `clerkClient().invitations.revokeInvitation(inv_id)`. |
| Password Reset | Clerk's built-in `<SignIn />` component includes "Forgot password?" — no custom implementation required. |

---

### 3.3 RBAC Role Mapping

| Clerk Role / Metadata | App Enum | Permitted Actions |
|-----------------------|----------|-------------------|
| `org:admin` | `ADMIN` | Edit persona, manage vaults, manage team, activate/pause/archive campaigns, audit logs, Kill Switch, Auto-Pilot config, TryEval export, Super Admin promotion (if self is SUPER_ADMIN) |
| `org:member` | `MEMBER` | Review/edit/publish pending drafts via shared Reddit accounts, view campaigns, copy prompt templates, TryEval export |
| `publicMetadata.role: SUPER_ADMIN` | `SUPER_ADMIN` | Platform level: view all tenants, suspend orgs, promote users to SUPER_ADMIN, monitor workers, global rate-limit dashboard, cross-org audit log |

---

### 3.4 Encryption Implementation — Fernet + Startup Validation

> **✓ Teammate 3:** Fernet + startup validation is a great safeguard. The `ValueError` at startup makes misconfiguration immediately visible.

```python
# backend/utils/encryption.py
import os, base64
from cryptography.fernet import Fernet

def _validate_and_get_fernet() -> Fernet:
    secret_hex = os.environ.get('ENCRYPTION_SECRET', '')
    # Startup guard: fail fast before any request is served.
    # Developers often confuse "32 hex chars" (16 bytes) with "32 bytes" (64 hex chars).
    if len(secret_hex) != 64:
        raise ValueError(
            f'ENCRYPTION_SECRET must be exactly 64 hex characters (32 bytes). '
            f'Got {len(secret_hex)} characters. '
            f'Generate with: python -c "import secrets; print(secrets.token_hex(32))"'
        )
    key_bytes  = bytes.fromhex(secret_hex)
    fernet_key = base64.urlsafe_b64encode(key_bytes)
    return Fernet(fernet_key)

# Instantiated once at module import — validates on startup.
_fernet = _validate_and_get_fernet()

def encrypt(plaintext: str) -> str:
    return _fernet.encrypt(plaintext.encode()).decode()

def decrypt(token: str) -> str:
    # Raises cryptography.fernet.InvalidToken if key is wrong or data is tampered.
    return _fernet.decrypt(token.encode()).decode()
```

> **ℹ NOTE:** The startup validation means a misconfigured `ENCRYPTION_SECRET` causes the Docker container to exit immediately with a clear error message before serving any traffic.

---

### 3.5 Encryption Key Lifecycle & KMS Guidance

- **OSS/Dev:** `ENCRYPTION_SECRET` as env var in `.env`. 64 hex chars. Never committed to VCS.
- **Hosted/Prod (REQUIRED):** Use AWS KMS, GCP Cloud KMS, Azure Key Vault, or HashiCorp Vault. Application fetches data encryption key (DEK) from KMS at startup. DEK held in memory — never written to database.
- **Key Version Tracking:** `encrypted_with_key_version` column on `OrgLLMConfig` and `RedditAccount`. Allows rotation without re-encrypting all rows simultaneously.
- **Rotation Script:** `backend/scripts/rotate_encryption_key.py` — reads with old key, re-encrypts with new Fernet key, updates `encrypted_with_key_version` in single DB transaction. AuditLog: `action=ENCRYPTION_KEY_ROTATED`.

> **ℹ NOTE (Teammate 3):** For production self-hosting, replace the Redis `--requirepass` flag with Docker secrets or an environment file with restricted file permissions (`chmod 600 .env`). The `REDIS_PASSWORD` must be strong (minimum 32 random characters) and randomly generated.

---

### 3.6 Super Admin Layer — UI & Promotion API

> **Teammate 2:** Early stage: Clerk Dashboard is sufficient. Production: an internal UI backed by an API is required so Super Admins can promote users without touching the Clerk Dashboard.

```python
# POST /api/admin/promote-super-admin
# Requires: caller must already be SUPER_ADMIN (verified via FastAPI dependency)

async def promote_to_super_admin(
    target_user_id: str,
    session = Depends(require_super_admin),
):
    client = await clerkClient()
    # Update Clerk publicMetadata
    await client.users.update_user(
        target_user_id,
        public_metadata={ 'role': 'SUPER_ADMIN' }
    )
    # Mirror in PostgreSQL for audit trail
    await db.execute(
        update(User).where(User.clerk_id == target_user_id)
                   .values(role=UserRole.SUPER_ADMIN)
    )
    await write_audit_log(
        action='SUPER_ADMIN_PROMOTED',
        details={'promoted_user_id': target_user_id, 'promoted_by': session['user_id']}
    )
    return {'status': 'promoted'}

# DELETE /api/admin/revoke-super-admin (same pattern — sets role back to MEMBER)
```

**Super Admin Dashboard Features:**

| Feature | Specification |
|---------|---------------|
| Tenant Overview | Paginated table of all Organizations: `clerk_org_id`, name, member count, campaign count, `is_active`. Sortable and filterable. |
| Suspend Tenant | Toggle `Organization.is_active=false`. Celery workers check this flag before processing. Suspended users see an interstitial page. |
| Promote / Revoke SUPER_ADMIN | Search Clerk users by email. One-click promotion via `POST /api/admin/promote-super-admin`. Confirmation `AlertDialog`. AuditLog entry written. |
| Worker Health | Live Celery worker status per queue. Active, reserved, and failed task counts from Redis. |
| Global Rate Limit | `praw:posts:{account_id}:{date}` counters across all orgs. Color-coded: green (<70%), yellow (70–90%), red (>90%). |
| Cross-Org Audit Log | Read-only. Filterable by org, action, user, date range. JSONB `details` searchable via GIN index. |

---

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

## 6. Security Specification

| Control | Requirement | Severity |
|---------|-------------|----------|
| Clerk Token Verification | Server-side Clerk SDK on every FastAPI request. JWKS cached 5 min. Client claims never trusted. | 🔴 CRITICAL |
| Webhook Replay Attack Guard | `svix-timestamp` header checked before idempotency DB lookup. Requests older than 5 minutes rejected with 400. | 🔴 CRITICAL |
| Webhook HMAC + Idempotency | `svix-signature` HMAC verified on all Clerk webhooks. `svix-id` persisted via `ON CONFLICT DO NOTHING` (not raw try/except). | 🔴 CRITICAL |
| ENCRYPTION_SECRET Startup Validation | Must be exactly 64 hex characters. Application refuses to start if invalid. | 🔴 CRITICAL |
| Fernet Encryption at Rest | All secrets encrypted with Fernet. KMS mandatory for hosted/prod. | 🔴 CRITICAL |
| Redis TLS + AUTH + ACLs | TLS mandatory for hosted deployments. ACL users restrict Celery workers to specific key patterns. | 🔴 CRITICAL |
| PRAW Token Refresh Lock + Jitter | Redis `nx=True` distributed lock. Polling fallback uses 100–150ms jitter to prevent thundering herd. | 🔴 CRITICAL |
| LLM Cost Protection | `max_daily_llm_tokens` and `max_monthly_llm_cost_usd` on `OrgLLMConfig`. `FAILED_COST_LIMIT` status on draft when exceeded. | 🟡 HIGH |
| FastAPI User Rate Limiting | `slowapi` middleware. Test-rules: 10/min/user. Publish: 20/min/user. | 🟡 HIGH |
| Celery Publish Idempotency | Redis key `praw_publish:{draft_id}` (TTL 5 min) prevents double-publish on task retry. `DraftReply.status == PUBLISHED` check before dispatch. | 🟡 HIGH |
| Kill Switch Rate Limiting | Kill Switch deletions routed through `praw_publish` queue with 2-second delay. | 🟡 HIGH |
| Subreddit Safety Profiles | Per-subreddit auto-pilot override. Checked at ConfidenceGate before any auto-publish. | 🟡 HIGH |
| Persona Save Validation | Reject persona save if `master_context_tokens + rulesets_token_count > 80%` of model limit. | 🟡 HIGH |
| Uvicorn Proxy Headers | `--proxy-headers --forwarded-allow-ips='*'` for correct client IP parsing behind reverse proxies. | 🟡 HIGH |
| SQL Injection Prevention | SQLAlchemy ORM with parameterized queries. No raw string SQL. | 🟡 HIGH |
| CORS Policy | `allow_origins` restricted to `NEXT_PUBLIC_APP_URL`. Wildcard `*` prohibited. | 🟡 HIGH |
| Dependency SCA | Dependabot + `pip-audit` in CI. HIGH/CRITICAL CVEs patched within 7 days. | 🟡 HIGH |
| Secret Scanning | GitHub Secret Scanning + `gitleaks` pre-commit hook. | 🟡 HIGH |

---

## 7. Observability & Monitoring

> **Teammate 1:** Running a full Prometheus + Grafana stack is too heavy for a developer self-hosting on a $5/mo VPS. Prometheus/Grafana are optional via `ENABLE_METRICS` toggle. Structured JSON logging is **mandatory** for all deployments.

### Structured JSON Logging (Mandatory — All Deployments)

All Celery workers and FastAPI handlers emit structured JSON logs using `structlog`. Every entry includes: `timestamp`, `level`, `service`, `task_id`, `org_id`, `campaign_id`, `draft_id`, `model`, `tokens_used`, `confidence`, and `message`.

```json
{
  "timestamp":   "2025-11-01T10:23:45.123Z",
  "level":       "info",
  "service":     "worker_langgen",
  "task_id":     "celery-abc-123",
  "org_id":      42,
  "campaign_id": 7,
  "draft_id":    101,
  "model":       "gemini-1.5-flash",
  "tokens_used": 2847,
  "confidence":  0.91,
  "message":     "Draft generated successfully"
}
```

### Prometheus Metrics (Optional — `ENABLE_METRICS=true`)

| Metric | Type | Labels | Purpose |
|--------|------|--------|---------|
| `llm_generation_total` | Counter | `model, provider, org_id, status` | LLM success/failure rate |
| `llm_generation_latency_seconds` | Histogram | `model, provider` | Draft generation P50/P95 |
| `llm_tokens_total` | Counter | `model, org_id, type` | Token usage + cost tracking |
| `llm_cost_limit_hits_total` | Counter | `org_id` | Cost limit breach count |
| `praw_publish_total` | Counter | `account_id, org_id, status` | Publish success/failure |
| `praw_429_total` | Counter | `account_id` | Rate limit hits |
| `autopilot_publish_total` | Counter | `campaign_id, org_id` | Auto-pilot volume |
| `autopilot_precision_ratio` | Gauge | `campaign_id` | Auto-publish / (auto-publish + manual-reject) |
| `celery_queue_depth` | Gauge | `queue_name` | Pending tasks per queue |
| `draft_inbox_latency_seconds` | Histogram | `org_id` | Inbox P95 — SLO target < 500ms |
| `clerk_webhook_processed_total` | Counter | `event_type, status` | Webhook sync health |
| `scheduler_campaigns_due_total` | Counter | — | Campaigns dispatched per Beat tick |

### Alerting Playbook

| Alert | Condition | Response |
|-------|-----------|----------|
| Reddit 429 Spike | `praw_429_total` > 5 in 10 min for any account | PagerDuty + Slack alert. Check auto-pilot daily limit. |
| LLM Failure Rate | Failed / total > 10% over 15 min | Check BYOK API key validity. Check LiteLLM provider status. |
| Cost Limit Breaches | `llm_cost_limit_hits_total` > 0 | Review org's `max_daily_llm_tokens` configuration. |
| Celery Queue Depth | Any queue > 100 tasks for > 5 min | Scale worker replicas. Check DLQ. |
| Inbox Latency SLO | P95 > 500ms | Check DB query plan. Verify GIN and compound indexes are present. |
| DLQ Depth | > 10 tasks | Super Admin reviews failed task payloads. |

### Sentry Integration

All unhandled exceptions in FastAPI handlers and Celery tasks captured by Sentry with full stack traces and release tracking. `SENTRY_DSN` is a required env var for production deployments.

---

## 8. Compliance, GDPR & Data Governance

### Data Privacy — Reddit Content

- **Stored:** `reddit_post_id`, `reddit_post_url`, `original_text` (post body + fetched comments up to `comment_fetch_limit`). Subject to 7-day retention for `REJECTED`/`FAILED` drafts.
- **Not stored:** Reddit usernames, user profile data, karma scores, account ages, or any profile metadata. PRAW fetches are scoped to post content only.
- **Retention for `PUBLISHED`:** `original_text` retained indefinitely for audit compliance.

### Data Retention Schedule

| Record Type | Retention Policy |
|-------------|-----------------|
| `DraftReply` (REJECTED, FAILED, FAILED_COST_LIMIT) | Hard-deleted after 7 days by daily maintenance cron. |
| `DraftReply` (PUBLISHED, DELETED_BY_KILLSWITCH) | Retained indefinitely for compliance. |
| `DraftReply` (PENDING, APPROVED) | Retained until status change or 30 days, whichever is first. |
| `AuditLog` | Retained 2 years minimum. Anonymized (not deleted) on org deletion. |
| `ProcessedWebhookEvent` | Purged after 30 days by maintenance cron. |
| `OrgPersona`, `OrgLLMConfig`, `Campaigns` | Hard-deleted within 30 days of GDPR erasure soft-delete. |

### Right to Erasure (GDPR Article 17)

1. Soft-delete: `Organization.is_active=false`, all Campaigns paused immediately.
2. Schedule hard-delete within 30 days in dependency order: `DraftReply` → `Campaign` → `OrgPersona` → `OrgLLMConfig` → `RedditAccount` → `SubredditSafetyProfile` → `AuditLog` (anonymized) → `Organization`.
3. Reddit posts published by the org are **not** deleted from Reddit (public third-party content).
4. Deletion confirmation email sent to Admin's Clerk-registered email.

---

## 9. Non-Functional Requirements

| Category | Requirement | Target |
|----------|-------------|--------|
| Performance | Paginated draft inbox (50 drafts/page) | < 500ms P95 |
| Performance | Celery `langgen` worker throughput | 50 drafts/hour/org (1 worker per 5 orgs) |
| Performance | Triage Rule Tester (20 posts, dry-run) | < 30 seconds end-to-end |
| Performance | Token budget computation (per draft) | < 10ms (pre-computed `master_context_tokens`) |
| Idempotency | No duplicate replies per campaign per post | `UniqueConstraint(campaign_id, reddit_post_id)` + EXISTS check |
| Idempotency | No duplicate PRAW publishes on task retry | Redis key `praw_publish:{draft_id}` (TTL 5 min) + `status == PUBLISHED` check |
| Idempotency | Webhook duplicate prevention | `ProcessedWebhookEvent` + `ON CONFLICT DO NOTHING` |
| Concurrency | Draft lock TTL | 15 minutes. Auto-release every 5 min via maintenance worker. |
| Concurrency | PRAW token refresh | Redis distributed lock (jitter 100–150ms). Max 1 refresh per account at any time. |
| Security | Webhook replay attack window | Reject `svix-timestamp` older than 5 minutes. |
| Security | Persona save validation | Reject if `master_context_tokens + rulesets_token_count > 80%` of model limit. |
| Cost Safety | LLM cost guard | `FAILED_COST_LIMIT` status when `max_daily_llm_tokens` or `max_monthly_llm_cost_usd` exceeded. |
| Availability | Hosted SaaS uptime | 99.5% monthly (excluding planned maintenance). |
| Scheduler | Campaign polling drift | < 60 seconds from scheduled time (Redis ZSET priority queue). |
| Data Retention | REJECTED/FAILED draft cleanup | Hard-deleted within 24h of 7-day threshold. |
| Compliance | GDPR erasure fulfilment | Soft-delete immediate; hard-delete within 30 days. |
| Security | HIGH/CRITICAL CVE patch window | 7 days from Dependabot alert. |

---

## 10. Open-Source & Docker Self-Hosting

> **⚠ WARNING — Teammate 4:** Spinning up 4 distinct Celery worker containers + Beat + FastAPI + Next.js + Postgres + Redis on a Raspberry Pi 4 (4GB RAM) will cause OOM crashes. A `docker-compose.lite.yml` is required for low-resource self-hosting.

### docker-compose.yml (Full — Production / Cloud)

```yaml
services:
  db:
    image: postgres:15-alpine
    environment:
      POSTGRES_DB: ${POSTGRES_DB:-sentinel}
      POSTGRES_USER: ${POSTGRES_USER:-sentinel}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes: [postgres_data:/var/lib/postgresql/data]
    healthcheck:
      test: ['CMD', 'pg_isready', '-U', '${POSTGRES_USER:-sentinel}']
      interval: 5s
      start_period: 10s
      retries: 5

  redis:
    image: redis:7-alpine
    # Security: use --requirepass. For production, prefer Docker secrets over env vars.
    command: redis-server --requirepass ${REDIS_PASSWORD} --appendonly yes --save 60 1000
    volumes: [redis_data:/data]

  backend:
    build: ./backend
    # Alembic runs migrations + seed before Uvicorn starts — idempotent on every restart.
    # --proxy-headers and --forwarded-allow-ips required for Cloudflare tunnel / ngrok / nginx.
    command: >
      sh -c 'alembic upgrade head &&
             python seed.py &&
             uvicorn main:app --host 0.0.0.0 --port 8000
               --proxy-headers --forwarded-allow-ips="*"'
    env_file: .env
    depends_on:
      db: { condition: service_healthy }
      redis: { condition: service_started }

  worker_scraper:
    build: ./backend
    command: celery -A tasks worker -Q scraper --concurrency=4 --loglevel=info
    env_file: .env
    depends_on: [backend]

  worker_langgen:
    build: ./backend
    command: celery -A tasks worker -Q langgen --concurrency=8 --loglevel=info
    env_file: .env
    depends_on: [backend]

  worker_publish:
    build: ./backend
    command: celery -A tasks worker -Q praw_publish --concurrency=2 --loglevel=info
    env_file: .env
    depends_on: [backend]

  worker_maintenance:
    build: ./backend
    command: celery -A tasks worker -Q maintenance --concurrency=1 --loglevel=info
    env_file: .env
    depends_on: [backend]

  beat:
    build: ./backend
    command: celery -A tasks beat --loglevel=info
    env_file: .env
    depends_on: [worker_maintenance]

  # Optional observability stack — controlled by ENABLE_METRICS env var.
  # To include: docker-compose --profile metrics up -d
  prometheus:
    image: prom/prometheus:latest
    profiles: [metrics]
    volumes: [./prometheus.yml:/etc/prometheus/prometheus.yml]
    ports: ['9090:9090']

  grafana:
    image: grafana/grafana:latest
    profiles: [metrics]
    ports: ['3001:3000']
    environment: { GF_SECURITY_ADMIN_PASSWORD: ${GRAFANA_PASSWORD} }

  frontend:
    build: ./frontend
    environment:
      NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY: ${NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY}
      CLERK_SECRET_KEY: ${CLERK_SECRET_KEY}
      NEXT_PUBLIC_API_URL: http://backend:8000
    ports: ['3000:3000']
    depends_on: [backend]

volumes:
  postgres_data:
  redis_data:
```

**Scale `langgen` workers:** `docker-compose up --scale worker_langgen=4 -d`  
**Enable observability:** `docker-compose --profile metrics up -d`

---

### docker-compose.lite.yml (Low-Resource — Hobbyist / Raspberry Pi)

> **Teammate 4:** Collapses all Celery queues into a single worker process. Sacrifices throughput for memory efficiency. Suitable for personal use, learning, and low-volume deployments.

```yaml
# docker-compose.lite.yml
# Launch: docker-compose -f docker-compose.lite.yml up -d
# Note: All Celery queues run in one process (concurrency=2). Not suitable for > 2 active orgs.
services:
  db:
    image: postgres:15-alpine
    environment:
      POSTGRES_DB: ${POSTGRES_DB:-sentinel}
      POSTGRES_USER: ${POSTGRES_USER:-sentinel}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes: [postgres_data:/var/lib/postgresql/data]
    healthcheck:
      test: ['CMD', 'pg_isready', '-U', 'sentinel']
      interval: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    command: redis-server --requirepass ${REDIS_PASSWORD}

  backend:
    build: ./backend
    command: >
      sh -c 'alembic upgrade head &&
             python seed.py &&
             uvicorn main:app --host 0.0.0.0 --port 8000
               --proxy-headers --forwarded-allow-ips="*"'
    env_file: .env
    depends_on:
      db: { condition: service_healthy }
      redis: { condition: service_started }

  # Single combined worker — all queues, low concurrency
  worker_all:
    build: ./backend
    command: >
      celery -A tasks worker
        -Q scraper,langgen,praw_publish,maintenance
        --concurrency=2
        --loglevel=info
    env_file: .env
    depends_on: [backend]

  beat:
    build: ./backend
    command: celery -A tasks beat --loglevel=info
    env_file: .env
    depends_on: [worker_all]

  frontend:
    build: ./frontend
    environment:
      NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY: ${NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY}
      CLERK_SECRET_KEY: ${CLERK_SECRET_KEY}
      NEXT_PUBLIC_API_URL: http://backend:8000
    ports: ['3000:3000']
    depends_on: [backend]

volumes:
  postgres_data:
```

---

### Required Environment Variables (.env.example)

```bash
# ── Clerk (required) ──────────────────────────────────────────────────────────
NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=pk_test_...   # Clerk Dashboard → API Keys
CLERK_SECRET_KEY=sk_test_...                    # Server-side only. Never expose to browser.
CLERK_WEBHOOK_SECRET=whsec_...                  # Clerk Dashboard → Webhooks

# ── Database ──────────────────────────────────────────────────────────────────
DATABASE_URL=postgresql+asyncpg://sentinel:password@db:5432/sentinel
POSTGRES_PASSWORD=change_me_strong_password

# ── Redis ─────────────────────────────────────────────────────────────────────
REDIS_URL=redis://:password@redis:6379/0
REDIS_PASSWORD=change_me_strong_password    # Min 32 random chars. Use: openssl rand -hex 24

# ── Encryption (CRITICAL) ─────────────────────────────────────────────────────
# Must be EXACTLY 64 hex characters (32 bytes). App refuses to start otherwise.
# Generate: python -c "import secrets; print(secrets.token_hex(32))"
# NEVER commit a real value. Back up separately from the database backup.
ENCRYPTION_SECRET=
ENCRYPTION_KEY_VERSION=1

# ── Observability ─────────────────────────────────────────────────────────────
SENTRY_DSN=                                     # Required for production
ENABLE_METRICS=false                            # Set to 'true' to enable Prometheus/Grafana

# ── App ───────────────────────────────────────────────────────────────────────
NEXT_PUBLIC_APP_URL=http://localhost:3000       # Used for CORS policy
```

---

## 11. Frontend UX Specifications

> **Teammate 3:** The Command (`⌘K`) palette must work globally — from any page, not just the dashboard. Implement via a client-side provider at the root layout level with a router integration for navigation actions.

| Feature | shadcn Component | Specification |
|---------|-----------------|---------------|
| Draft inbox table | `DataTable` (TanStack Table) | Server-side pagination (50/page). Sort: `created_at`, `confidence_score`, `status`, `subreddit`. Filter: status (multi), subreddit, `is_auto_pilot`. Bulk select for TryEval export. Full-text search via `/api/drafts?q=` (uses PostgreSQL FTS index). |
| Draft review | `Sheet` | Slide-out panel. Reddit thread left, editable draft right. Shows `model_used`, confidence badge, `prompt_template_version`, truncation indicator. "Preview compiled system prompt" button. |
| Confidence explanation | `Popover` + `Badge` | Confidence score badge is clickable. Popover shows `triage_reasoning` broken into bullet points. Example: "Confidence: 0.91 — Mentions RAG • Benchmarking context • Evaluation intent" |
| Async feedback | `Toast` (Sonner) | 3-state publish: "Queued" → "Publishing…" → "Published ✓ / Failed ✗". Bottom-right. Max 3 toasts. |
| Loading states | `Skeleton` | Inbox rows and draft card while React Query fetches. |
| Destructive actions | `AlertDialog` | Kill Switch, Force Lock Takeover, Campaign Archive, Org deletion, Super Admin promotion. |
| Navigation | `Command` (⌘K) | **Global** — mounted at root layout. Jump to campaigns, subreddits, settings, audit log. Works from any page. |
| Role-gated UI | Clerk `<Protect>` | Wraps Admin-only: Kill Switch, Vault management, Auto-Pilot config, Safety Profiles, Super Admin promotion. |
| Org switching | `OrganizationSwitcher` | `hidePersonal={true}`. Redirects to `/onboarding` on new org creation. |
| Confidence display | `Badge` + `Progress` | Green (>0.85), Yellow (0.5–0.85), Red (<0.5). Shown in inbox row and draft `Sheet`. Clickable → confidence explanation popover. |
| Safety Profile status | `Badge` + `Tooltip` | "Safety Override" badge on drafts from restricted subreddits. Tooltip explains which profile rule blocked auto-pilot. |
| Cost limit alert | `Alert` (destructive) | Org-level banner when `FAILED_COST_LIMIT` drafts detected. Links to LLM Config vault to adjust limits. |
| Keyword type indicator | `Badge` | `[regex]` badge on keyword entries that start with `regex:` prefix in Campaign configuration UI. |

**Accessibility:**
- Keyboard shortcuts when `Sheet` is open: `A` = Approve, `R` = Reject, `E` = Edit, `P` = Publish. Documented in a `<KeyboardShortcutHelper />` tooltip.
- All interactive components have correct `aria-label`, `aria-describedby`, `role`. shadcn/ui provides these — do not override.
- Dark Mode is the default. Theme toggle in `UserButton` dropdown. System preference respected on first load.
- Minimum contrast ratio 4.5:1 for all body text (WCAG AA).

---

## 12. SQLAlchemy V6 Schema — Final

> This is the authoritative schema. All V1–V5 changes are preserved. V6 additions: `FAILED_COST_LIMIT` status; `max_daily_llm_tokens` and `max_monthly_llm_cost_usd` on `OrgLLMConfig`; `prompt_template_version` on `DraftReply`; FTS GIN index on `DraftReply`; additional partial indexes; `RedditAccount.encrypted_secret` → `Text`; explicit `prompt_payload` and `truncation_details` in `DraftReply`; `token_count` fields confirmed present.

```python
import enum
from datetime import datetime, timezone
from typing import List, Optional
from sqlalchemy import (String, Boolean, Integer, ForeignKey, DateTime,
                        Text, Float, UniqueConstraint, Index, Numeric)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

class Base(DeclarativeBase):
    pass

def now_utc():
    return datetime.now(timezone.utc)


# ── Enums ─────────────────────────────────────────────────────────────────────

class UserRole(str, enum.Enum):
    SUPER_ADMIN = "SUPER_ADMIN"           # Platform-level operator
    ADMIN       = "ADMIN"                 # Org-level admin
    MEMBER      = "MEMBER"                # Org-level member

class DraftStatus(str, enum.Enum):
    PENDING               = "PENDING"
    APPROVED              = "APPROVED"
    REJECTED              = "REJECTED"
    PUBLISHED             = "PUBLISHED"
    FAILED                = "FAILED"
    DELETED_BY_KILLSWITCH = "DELETED_BY_KILLSWITCH"
    FAILED_COST_LIMIT     = "FAILED_COST_LIMIT"      # NEW V6: LLM cost limit exceeded

class CampaignStatus(str, enum.Enum):
    ACTIVE   = "ACTIVE"
    PAUSED   = "PAUSED"
    ARCHIVED = "ARCHIVED"


# ── ProcessedWebhookEvent ─────────────────────────────────────────────────────

class ProcessedWebhookEvent(Base):
    """
    Clerk webhook idempotency table.
    - ON CONFLICT DO NOTHING used instead of raw try/except (Teammate 3).
    - Rows purged after 30 days by maintenance cron.
    - Replay attack guard is applied BEFORE this lookup (svix-timestamp > 5 min → reject).
    """
    __tablename__ = "processed_webhook_events"

    id           : Mapped[int]      = mapped_column(primary_key=True)
    event_id     : Mapped[str]      = mapped_column(String(255), unique=True, index=True)
    event_type   : Mapped[str]      = mapped_column(String(100))
    processed_at : Mapped[datetime] = mapped_column(default=now_utc)


# ── Organization ──────────────────────────────────────────────────────────────

class Organization(Base):
    __tablename__ = "organizations"

    id           : Mapped[int]      = mapped_column(primary_key=True)
    clerk_org_id : Mapped[str]      = mapped_column(String(255), unique=True, index=True)
    name         : Mapped[str]      = mapped_column(String(255), nullable=False)
    is_active    : Mapped[bool]     = mapped_column(Boolean, default=True)
    created_at   : Mapped[datetime] = mapped_column(default=now_utc)

    users           : Mapped[List["User"]]                   = relationship(back_populates="organization")
    reddit_accounts : Mapped[List["RedditAccount"]]          = relationship(back_populates="organization")
    campaigns       : Mapped[List["Campaign"]]               = relationship(back_populates="organization")
    safety_profiles : Mapped[List["SubredditSafetyProfile"]] = relationship(back_populates="organization")
    llm_config      : Mapped[Optional["OrgLLMConfig"]]       = relationship(back_populates="organization")
    persona         : Mapped[Optional["OrgPersona"]]         = relationship(back_populates="organization")
    audit_logs      : Mapped[List["AuditLog"]]               = relationship(back_populates="organization")


# ── OrgLLMConfig — BYOK LLM Vault ────────────────────────────────────────────

class OrgLLMConfig(Base):
    """BYOK vault for LLM credentials. One record per org."""
    __tablename__ = "org_llm_configs"

    id     : Mapped[int] = mapped_column(primary_key=True)
    org_id : Mapped[int] = mapped_column(ForeignKey("organizations.id"), unique=True)

    provider                   : Mapped[str]           = mapped_column(String(50))     # 'openai','anthropic','gemini','ollama'
    model_name                 : Mapped[str]           = mapped_column(String(100))    # 'gpt-4o','claude-3-5-sonnet-20241022'
    custom_base_url            : Mapped[Optional[str]] = mapped_column(String(500))    # Ollama/vLLM base URL
    encrypted_api_key          : Mapped[Optional[str]] = mapped_column(Text)           # Fernet token — Text avoids truncation
    encrypted_with_key_version : Mapped[int]           = mapped_column(Integer, default=1)

    # Cost protection (NEW V6)
    max_daily_llm_tokens      : Mapped[Optional[int]]   = mapped_column(Integer)       # Daily token cap across all drafts
    max_monthly_llm_cost_usd  : Mapped[Optional[float]] = mapped_column(Numeric(10,4)) # Monthly USD cost cap

    organization: Mapped["Organization"] = relationship(back_populates="llm_config")


# ── OrgPersona — Context Engine ───────────────────────────────────────────────

class OrgPersona(Base):
    """
    Structured brand identity.
    Pre-computed token counts are model-specific (Teammate 1).
    They are recalculated:
      (1) When the persona is saved.
      (2) When OrgLLMConfig.model_name changes.
    If no LLM is configured yet, counts use DEFAULT_MODEL ('gpt-4o') as fallback.
    """
    __tablename__ = "org_personas"

    id     : Mapped[int] = mapped_column(primary_key=True)
    org_id : Mapped[int] = mapped_column(ForeignKey("organizations.id"), unique=True)

    master_context        : Mapped[Optional[str]]  = mapped_column(Text)
    master_context_tokens : Mapped[int]            = mapped_column(Integer, default=0)   # Pre-computed, model-specific
    rulesets_dos_donts    : Mapped[Optional[dict]] = mapped_column(JSONB)                # {"dos":[...],"donts":[...]}
    rulesets_token_count  : Mapped[int]            = mapped_column(Integer, default=0)   # Pre-computed, model-specific
    tone_guidelines       : Mapped[Optional[str]]  = mapped_column(Text)

    updated_at: Mapped[datetime] = mapped_column(default=now_utc, onupdate=now_utc)

    organization: Mapped["Organization"] = relationship(back_populates="persona")

    __table_args__ = (
        Index("idx_orgpersona_rulesets_gin", "rulesets_dos_donts", postgresql_using="gin"),
    )


# ── User — Clerk-synced ───────────────────────────────────────────────────────

class User(Base):
    """
    No hashed_password. No UserInvitation table.
    Auth is fully managed by Clerk.
    Invitations managed via Clerk organization.inviteMember() API.
    """
    __tablename__ = "users"

    id                 : Mapped[int]               = mapped_column(primary_key=True)
    clerk_id           : Mapped[str]               = mapped_column(String(255), unique=True, index=True)
    email              : Mapped[str]               = mapped_column(String(255), unique=True, index=True)
    role               : Mapped[UserRole]          = mapped_column(default=UserRole.MEMBER)
    is_active          : Mapped[bool]              = mapped_column(Boolean, default=True)
    created_at         : Mapped[datetime]          = mapped_column(default=now_utc)
    last_login_at      : Mapped[Optional[datetime]]= mapped_column(DateTime(timezone=True))
    invited_by_user_id : Mapped[Optional[int]]     = mapped_column(ForeignKey("users.id"))

    org_id      : Mapped[int]            = mapped_column(ForeignKey("organizations.id"))
    organization: Mapped["Organization"] = relationship(back_populates="users")


# ── RedditAccount — PRAW Vault ────────────────────────────────────────────────

class RedditAccount(Base):
    """
    PRAW credentials vault.
    encrypted_secret is Text (Teammate 3: aligned with OrgLLMConfig.encrypted_api_key).
    Live rate-limit counter in Redis: praw:posts:{id}:{YYYY-MM-DD} TTL=86400s.
    """
    __tablename__ = "reddit_accounts"

    id               : Mapped[int] = mapped_column(primary_key=True)
    org_id           : Mapped[int] = mapped_column(ForeignKey("organizations.id"))
    added_by_user_id : Mapped[int] = mapped_column(ForeignKey("users.id"))

    username                   : Mapped[str]  = mapped_column(String(100), nullable=False)
    client_id                  : Mapped[str]  = mapped_column(String(255), nullable=False)
    encrypted_secret           : Mapped[str]  = mapped_column(Text, nullable=False)         # Text — not String(500)
    encrypted_with_key_version : Mapped[int]  = mapped_column(Integer, default=1)

    is_shared_with_team : Mapped[bool]              = mapped_column(Boolean, default=True)
    is_active           : Mapped[bool]              = mapped_column(Boolean, default=True)
    deleted_at          : Mapped[Optional[datetime]]= mapped_column(DateTime(timezone=True)) # Soft delete

    # Rate limiting display state (live counter is in Redis)
    last_used_at        : Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    rate_limit_reset_at : Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    organization: Mapped["Organization"] = relationship(back_populates="reddit_accounts")

    __table_args__ = (
        # Partial index: only active accounts (Teammate 2)
        Index("idx_reddit_account_active", "org_id",
              postgresql_where="is_active = true AND deleted_at IS NULL"),
    )


# ── SubredditSafetyProfile ────────────────────────────────────────────────────

class SubredditSafetyProfile(Base):
    """Per-org safety overrides. Checked at LangGraph ConfidenceGate (Node 6)."""
    __tablename__ = "subreddit_safety_profiles"

    id             : Mapped[int]          = mapped_column(primary_key=True)
    org_id         : Mapped[int]          = mapped_column(ForeignKey("organizations.id"))
    subreddit_name : Mapped[str]          = mapped_column(String(100), nullable=False)

    allow_auto_pilot      : Mapped[bool]          = mapped_column(Boolean, default=True)
    max_daily_posts       : Mapped[int]           = mapped_column(Integer, default=3)
    require_manual_review : Mapped[bool]          = mapped_column(Boolean, default=False)
    notes                 : Mapped[Optional[str]] = mapped_column(Text)

    organization: Mapped["Organization"] = relationship(back_populates="safety_profiles")

    __table_args__ = (
        UniqueConstraint("org_id", "subreddit_name", name="uq_org_subreddit_safety"),
    )


# ── Campaign ──────────────────────────────────────────────────────────────────

class Campaign(Base):
    __tablename__ = "campaigns"

    id     : Mapped[int] = mapped_column(primary_key=True)
    org_id : Mapped[int] = mapped_column(ForeignKey("organizations.id"))

    name           : Mapped[str]  = mapped_column(String(255), nullable=False)
    subreddit_name : Mapped[str]  = mapped_column(String(100), index=True)
    # Keywords support exact substring (default) and regex (prefix with "regex:") (Teammate 3)
    keywords       : Mapped[list] = mapped_column(JSONB, nullable=False)

    status     : Mapped[CampaignStatus] = mapped_column(default=CampaignStatus.ACTIVE, index=True)
    created_at : Mapped[datetime]       = mapped_column(default=now_utc)

    # Scheduling — actual dispatch managed by Redis ZSET priority queue (§4.10)
    poll_frequency_minutes : Mapped[int]               = mapped_column(Integer, default=240)
    last_polled_at         : Mapped[Optional[datetime]]= mapped_column(DateTime(timezone=True))

    # Comment depth configuration
    comment_fetch_limit : Mapped[int]  = mapped_column(Integer, default=10)
    include_op_context  : Mapped[bool] = mapped_column(Boolean, default=True)
    max_comment_chars   : Mapped[int]  = mapped_column(Integer, default=500)

    # Auto-Pilot guardrails
    is_auto_pilot_enabled           : Mapped[bool]  = mapped_column(Boolean, default=False)
    auto_pilot_confidence_threshold : Mapped[float] = mapped_column(Float, default=0.95)
    auto_pilot_daily_limit          : Mapped[int]   = mapped_column(Integer, default=3)
    # Live counter in Redis: autopilot:count:{id}:{YYYY-MM-DD} EXPIREAT midnight UTC
    last_auto_post_at : Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    organization : Mapped["Organization"]    = relationship(back_populates="campaigns")
    drafts       : Mapped[List["DraftReply"]]= relationship(back_populates="campaign")

    __table_args__ = (
        Index("idx_campaign_keywords_gin", "keywords", postgresql_using="gin"),
        # Partial index: only active campaigns (Teammate 2)
        Index("idx_campaign_active", "org_id",
              postgresql_where="status = 'ACTIVE'"),
    )


# ── DraftReply — Complete V6 ──────────────────────────────────────────────────

class DraftReply(Base):
    """
    Central workflow record. Includes full provenance fields for debugging,
    TryEval export, cost tracking, and compliance.
    """
    __tablename__ = "draft_replies"

    id          : Mapped[int] = mapped_column(primary_key=True)
    campaign_id : Mapped[int] = mapped_column(ForeignKey("campaigns.id"))

    # Timestamps
    created_at   : Mapped[datetime]            = mapped_column(default=now_utc, index=True)
    updated_at   : Mapped[datetime]            = mapped_column(default=now_utc, onupdate=now_utc)
    published_at : Mapped[Optional[datetime]]  = mapped_column(DateTime(timezone=True))

    # Reddit Context
    reddit_post_id  : Mapped[str] = mapped_column(String(50), index=True)
    reddit_post_url : Mapped[str] = mapped_column(String(500), nullable=False)
    original_text   : Mapped[str] = mapped_column(Text)

    # AI Output & Provenance
    ai_draft_text             : Mapped[str]            = mapped_column(Text)
    confidence_score          : Mapped[float]          = mapped_column(Float)
    model_used                : Mapped[Optional[str]]  = mapped_column(String(100))     # 'gemini-1.5-flash'
    prompt_template_version   : Mapped[Optional[str]]  = mapped_column(String(100))     # NEW V6: e.g. 'triage_v2'
    model_payload_token_count : Mapped[Optional[int]]  = mapped_column(Integer)         # Tokens sent to LLM
    response_token_count      : Mapped[Optional[int]]  = mapped_column(Integer)         # Tokens returned
    truncation_applied        : Mapped[bool]           = mapped_column(Boolean, default=False)
    truncation_details        : Mapped[Optional[dict]] = mapped_column(JSONB)            # {removed_count, summarized_count}
    prompt_payload            : Mapped[Optional[dict]] = mapped_column(JSONB)            # Full compiled prompt + metadata

    # Failure tracking
    failed_reason : Mapped[Optional[str]] = mapped_column(String(1000))

    # Workflow State
    status            : Mapped[DraftStatus]        = mapped_column(default=DraftStatus.PENDING, index=True)
    locked_by_user_id : Mapped[Optional[int]]      = mapped_column(ForeignKey("users.id"))
    locked_at         : Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    # Publishing Execution
    approved_by_user_id    : Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    published_by_account_id: Mapped[Optional[int]] = mapped_column(ForeignKey("reddit_accounts.id"))
    live_reddit_url        : Mapped[Optional[str]] = mapped_column(String(500))
    is_auto_pilot_published: Mapped[bool]          = mapped_column(Boolean, default=False)

    # Prompt template reference
    prompt_template_id : Mapped[Optional[int]] = mapped_column(ForeignKey("prompt_templates.id"))

    campaign: Mapped["Campaign"] = relationship(back_populates="drafts")

    __table_args__ = (
        # Idempotency: one reply per campaign per Reddit post
        UniqueConstraint("campaign_id", "reddit_post_id", name="uq_draft_campaign_post"),
        # Primary inbox query: campaign + status + time
        Index("idx_draft_campaign_status_created", "campaign_id", "status", "created_at"),
        # Cross-org status queries (Teammate 2)
        Index("idx_draft_status_org", "campaign_id", "status"),
        # Full-text search on draft content (NEW V6 — Teammate 2)
        Index("idx_draftreply_ai_text_fts", "ai_draft_text",
              postgresql_using="gin",
              postgresql_ops={"ai_draft_text": "gin_trgm_ops"}),
        # Full-text search on original Reddit thread text (NEW V6)
        Index("idx_draftreply_original_text_fts", "original_text",
              postgresql_using="gin",
              postgresql_ops={"original_text": "gin_trgm_ops"}),
    )


# ── PromptTemplate ────────────────────────────────────────────────────────────

class PromptTemplate(Base):
    __tablename__ = "prompt_templates"

    id                : Mapped[int]           = mapped_column(primary_key=True)
    title             : Mapped[str]           = mapped_column(String(255), nullable=False)
    description       : Mapped[str]           = mapped_column(Text)
    category          : Mapped[str]           = mapped_column(String(100))       # 'Master Context','Tone','Keywords'
    prompt_body       : Mapped[str]           = mapped_column(Text, nullable=False)
    version           : Mapped[int]           = mapped_column(Integer, default=1) # Increment on system updates
    is_system_default : Mapped[bool]          = mapped_column(Boolean, default=True)
    org_id            : Mapped[Optional[int]] = mapped_column(ForeignKey("organizations.id"))
    # org_id=NULL → system default; org_id set → org custom template

    __table_args__ = (
        UniqueConstraint("org_id", "title", name="uq_org_prompt_title"),
    )


# ── AuditLog ──────────────────────────────────────────────────────────────────

class AuditLog(Base):
    """
    Immutable. Never updated after insert.
    Anonymized (org_id→NULL, details PII stripped) on org erasure — not deleted.

    action examples:
        DRAFT_PUBLISHED, AUTO_PUBLISHED, KILLSWITCH_ACTIVATED, KILLSWITCH_POST_DELETED,
        LOCK_FORCE_TAKEN, API_RATE_LIMIT_HIT, ENCRYPTION_KEY_ROTATED, SUPER_ADMIN_PROMOTED,
        CAMPAIGN_ARCHIVED, SAFETY_PROFILE_CREATED, PERSONA_TOKENS_RECALCULATED,
        COST_LIMIT_EXCEEDED, ORG_DATA_EXPORT_REQUESTED, ORG_DATA_DELETED
    """
    __tablename__ = "audit_logs"

    id      : Mapped[int]           = mapped_column(primary_key=True)
    org_id  : Mapped[Optional[int]] = mapped_column(ForeignKey("organizations.id"), index=True)
    user_id : Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))     # NULL = Auto-Pilot

    action    : Mapped[str]      = mapped_column(String(100))
    details   : Mapped[dict]     = mapped_column(JSONB)
    timestamp : Mapped[datetime] = mapped_column(default=now_utc, index=True)

    organization: Mapped[Optional["Organization"]] = relationship(back_populates="audit_logs")

    __table_args__ = (
        Index("ix_audit_org_time", "org_id", "timestamp"),
        Index("idx_audit_details_gin", "details", postgresql_using="gin"),
    )
```

---

## 13. Test Plan, CI/CD & Contract Tests

| Test Type | Scope | Tool | Coverage Target |
|-----------|-------|------|-----------------|
| Unit | Fernet encrypt/decrypt, startup validation (64-char check **and** missing value), tokenizer budget, truncation logic, PRAW distributed lock + jitter, Redis ZSET scheduler, cost guard logic, persona save validation (80% limit) | pytest | 100% of `utils/` |
| Integration | FastAPI endpoints with test PostgreSQL DB, Celery task dispatch, `SubredditSafetyProfile` enforcement, cost limit enforcement, rate-limit middleware (slowapi) | pytest + httpx | > 80% API routes |
| E2E — HITL | Webhook sync → Campaign create → Scraper → Draft (LangGraph mocked) → Human approve → PRAW publish | pytest | Full happy path |
| E2E — Auto-Pilot | High-confidence draft → Safety Profile check → auto-publish → AuditLog → Kill Switch (rate-aware, praw_publish queue) → `DELETED_BY_KILLSWITCH` | pytest | Full flow |
| E2E — Cost Limit | Draft generation when `max_daily_llm_tokens` is exceeded → `FAILED_COST_LIMIT` status + AuditLog | pytest | Cost guard enforced |
| E2E — Publish Idempotency | Celery task retried after simulated worker crash → second execution skips PRAW call (Redis key `praw_publish:{draft_id}` prevents double-post) | pytest | Idempotency confirmed |
| E2E — Safety Profile | Draft from restricted subreddit (`allow_auto_pilot=false`) routed to HITL despite confidence > 0.95 | pytest | Override confirmed |
| E2E — Concurrency | Two workers try PRAW token refresh simultaneously → one refreshes, others read cached value (with jitter). Draft lock TTL expiry auto-releases. | pytest | Both scenarios |
| E2E — Webhook Replay | Webhook with `svix-timestamp` older than 5 minutes → rejected with 400. Valid webhook with same `svix-id` delivered twice → exactly one DB write. | pytest | Both rejection + idempotency |
| E2E — Persona Validation | Persona save with `master_context_tokens + rulesets_token_count > 80%` of model limit → 422 error returned | pytest | Validation enforced |
| Contract — TryEval | Export endpoint JSON matches v1.0 schema (jsonschema) for all `DraftStatus` values. Includes `prompt_template_version`. | pytest + jsonschema | All statuses |
| Security | MEMBER cannot access ADMIN routes. Invalid `ENCRYPTION_SECRET` (< 64 chars AND missing) → startup exit. CORS rejects wildcard origin. Rate limiter returns 429 on limit breach. | pytest | All RBAC + startup |
| Frontend E2E | Publish 3-state UI, Sheet lock display + Force Takeover, Safety Profile badge, confidence explanation popover, ⌘K global nav, bulk TryEval export, cost limit banner | Playwright | Critical journeys |

### CI Pipeline (GitHub Actions)

```yaml
# .github/workflows/ci.yml
on: [push, pull_request]
jobs:
  backend:
    runs-on: ubuntu-latest
    services:
      postgres: { image: postgres:15, env: { POSTGRES_PASSWORD: test } }
      redis:    { image: redis:7 }
    env:
      ENCRYPTION_SECRET: "0000000000000000000000000000000000000000000000000000000000000000"  # Test-only 64-char value
    steps:
      - uses: actions/checkout@v4
      - run: pip install -r requirements-dev.txt
      - run: alembic upgrade head
      - run: pytest --cov=backend --cov-fail-under=80 -v
      - run: bandit -r backend/          # Security linting
      - run: pip-audit                   # CVE scan

  frontend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: npm ci && npm run build
      - run: npx playwright test

  contract:
    runs-on: ubuntu-latest
    steps:
      - run: pytest tests/contract/ -v   # TryEval schema + webhook idempotency + replay guard
```

> **Teammate 3:** The CI pipeline injects a valid 64-character test `ENCRYPTION_SECRET` so the startup validation passes in CI without requiring a real secret. A separate test case asserts that the application **exits** when given an invalid (non-64-char) value.

---

*End of TRD v6.0 — OSS DevRel AI Agent (Sentinel / TryEval DevRel)*  
*Version 6.0 · FINAL · Approved for Development*
