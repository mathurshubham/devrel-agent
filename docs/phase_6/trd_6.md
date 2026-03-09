# Technical Requirement Document — OSS DevRel AI Agent


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


*End of TRD v6.0 — OSS DevRel AI Agent (Sentinel / TryEval DevRel)*  
*Version 6.0 · FINAL · Approved for Development*