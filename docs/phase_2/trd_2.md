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