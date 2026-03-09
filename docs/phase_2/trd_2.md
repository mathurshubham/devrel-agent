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
