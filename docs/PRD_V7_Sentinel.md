# PRD V7 — Sentinel

**Status:** Draft for review
**Date:** 2026-08-22
**Supersedes:** TRD V6 product scope (see §10 for the section-by-section disposition) and the `docs/phase_1..6` folders (replaced by §12 milestone plan).
**Companion:** `docs/TRD_V6_Final_Sentinel_DevRel.md` remains the engineering reference for the sections §10 marks as KEEP.

---

## 1. Problem & product

DevRel teams need to show up where developers already talk — Reddit threads, LinkedIn posts, X/Twitter conversations — with useful, on-brand replies, fast enough that the conversation is still alive. Doing this manually means hours of scrolling; doing it with naive automation gets accounts banned and brands embarrassed.

**Sentinel** monitors the channels an org cares about, uses an LLM pipeline to select the conversations worth joining and draft replies in the org's voice, and puts every draft in front of a human. **A human posts every reply** — Sentinel opens the target post in a new tab with the finished draft already on the clipboard. Nothing is ever published programmatically.

### What changed since TRD V6 (decision log)

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | **Ingestion via Apify actors**, not PRAW/direct APIs | PRAW-based scraping no longer works. The social-agent MVP has run Apify ingestion for Reddit, LinkedIn, and Twitter in production (Raspberry Pi + Cloudflare tunnel) since March. |
| D2 | **Platforms at V1: Reddit, LinkedIn, X/Twitter** — all through Apify | Proven in the MVP. HN and Mastodon ingestion code ports over but ships behind a config flag, off by default. |
| D3 | **Copy-paste-only publishing** | One click copies the final draft to the clipboard and opens the source post in a new tab; the user pastes and submits on the platform, then confirms in Sentinel. Removes all programmatic posting: no PRAW publish, no tweepy, no Auto-Pilot, no shared Reddit account vault. Best possible ToS posture — every post is a human action from the human's own logged-in session. |
| D4 | **Weekly Analyst pipeline is in V1 scope** | Working today in the MVP; ports onto a second LangGraph graph. |
| D5 | **LangGraph becomes real** | V6 specced LangGraph but the dependency was never installed. V7 rebuilds both pipelines as actual `StateGraph`s with Postgres checkpointing (replaces the MVP's hand-rolled crash-resume cache tables). |
| D6 | **LiteLLM stays** as the model abstraction; keys passed per-call | Both codebases already use it. The MVP's `os.environ` key injection is a multi-tenant blocker and is removed. |
| D7 | **Multi-tenant (Clerk) from day one** | Already built in devrel-agent; the MVP's single-tenant assumptions (singleton settings, global run state, env-var keys) do not port. |
| D8 | **Monetization deferred** | V1 targets self-hosters and internal use. Billing/plans are an explicit open decision (§13), not silently absent. |

---

## 2. Users

| Persona | Description | Primary flows |
|---|---|---|
| **Org Admin** (DevRel lead) | Owns brand voice and risk. Small team (1–5). | Onboarding, persona & angle library, campaigns, Apify/LLM key vaults, safety profiles, budget caps, kill switch, team management, audit log. |
| **Org Member** (DevRel engineer) | Reviews and posts replies daily. | Inbox triage, edit drafts, one-click open-and-copy, mark posted, view analytics. |
| **Super Admin** (platform operator) | Runs a hosted instance. | Cross-org overview, suspend org, worker health. |
| **Self-hoster** | Solo founder / OSS user on a Pi or small VPS. | Everything above, single org, `docker-compose.lite.yml`, Cloudflare tunnel. |

---

## 3. Product principles

1. **Human posts everything.** Sentinel never holds platform posting credentials. The unit of automation is the *draft*, not the *post*.
2. **BYOK.** Orgs supply their own LLM keys and Apify tokens. Sentinel encrypts them (Fernet, versioned keys) and never re-displays them.
3. **Pi-grade.** The lite deployment must run on a Raspberry Pi 4 (4 GB) behind a Cloudflare tunnel. Apify carries all scraping compute; local workers only orchestrate and call LLMs.
4. **Spend is visible and capped.** Both LLM spend and Apify credit are metered, displayed, and enforced before dispatch — a run that would exceed budget is skipped, not truncated mid-way.
5. **The prompt corpus is the product.** Platform voice rules (Reddit safety filter, LinkedIn tone limits, angle libraries) are versioned content, seeded as system defaults, and editable per org.

---

## 4. Success metrics (V1 targets)

| Metric | Definition | Target |
|---|---|---|
| Draft freshness | P50 time from source post creation → draft PENDING in inbox | ≤ campaign poll interval + 10 min |
| Acceptance rate | drafts marked POSTED ÷ drafts generated | ≥ 40% by week 4 of org usage |
| Edit burden | share of posted drafts edited >30% (char diff) before posting | < 30% |
| Reply performance | posted replies receiving ≥1 response/reaction within 72 h (`got_response`) | ≥ 25% |
| Cost discipline | orgs exceeding their own Apify/LLM budget caps | 0 (enforcement, not aspiration) |
| Account safety | platform warnings/bans attributable to Sentinel-drafted content | 0 |
| Analyst adoption | weekly briefs opened within 48 h of generation | ≥ 75% |

Instrumentation: freshness and cost from pipeline telemetry; acceptance/edit from `DraftReply` status + edit history; reply performance from the outcomes poller (§5.7).

---

## 5. Feature specification

### 5.1 Campaigns (unified targets)

A **campaign** is one monitored source: `platform` (REDDIT | LINKEDIN | TWITTER) + `value` + per-platform filters. This merges V6's `Campaign` with the MVP's `Target`.

- **Reddit:** value = subreddit. Filters: sort (`top`/`new`), time window (`day`/`week`), max posts per poll (default 15), max comments per post (default 5).
- **LinkedIn:** value = keyword, profile URL, or company URL (mode auto-detected from the value, as in the MVP). Filters: result limit (default 30 keyword / 10 profile-company), sort (`date_posted`/`relevance`), date filter, exact-match quoting; keyword mode supports company/industry/job-title URN filters. Stale-post filter: drop posts older than `stale_days` **and** below `stale_min_engagement` (both org-configurable, null = off).
- **Twitter:** value = search term. Filters: query type (`Latest`/`Top`), max items (default ≥20), language, since-time, min retweets/faves/replies, verified/engagement/media flags.
- Common: name (required), status ACTIVE/PAUSED/ARCHIVED, poll frequency (default 240 min), optional keyword prefilter list (substring + `regex:` prefix — regex compiled with a timeout guard and case-insensitive by default).

**User stories & acceptance criteria**
- *As an Admin, I create a campaign in one form that adapts to the chosen platform.* AC: create → campaign is enqueued in the scheduler within one beat tick (≤60 s); pause → removed from schedule; the V6 bug where campaigns were never enqueued is a regression test.
- *As an Admin, I can dry-run a campaign.* AC: "Test rules" fetches one Apify run (counted against budget, labeled as a test) and shows which posts the prefilter and Scout would select, without creating drafts.
- *AI target suggestions (ported from MVP):* Admin describes their product in plain English → LLM proposes campaigns per platform → Admin accepts/edits. AC: suggestions are drafts, never auto-created.

Quotas: ≤20 campaigns/org, ≤25 prefilter keywords/campaign (Super Admin can raise per org).

### 5.2 Apify ingestion & multi-token vault

**Runner.** One generic async Apify runner (ported from the MVP's REST engine, replacing its parallel SDK path): start run (`POST /v2/acts/{actor~id}/runs`) → poll every 5 s, 120 s deadline → fetch dataset items. One retry with backoff on run-start; run status FAILED/ABORTED/TIMED-OUT → task failure with the run URL in the error. Actor output is schema-validated before normalization (new — the MVP parsed blindly); items failing validation are logged and skipped, never crash the run.

**Actor registry.** Platform defaults, overridable per org:
| Platform / mode | Default actor |
|---|---|
| Reddit | `automation-lab/reddit-scraper` |
| LinkedIn keyword | `apimaestro/linkedin-posts-search-scraper-no-cookies` |
| LinkedIn profile | `apimaestro/linkedin-profile-posts` |
| LinkedIn company | `scraper-engine/linkedin-company-post-scraper` |
| Twitter | `kaitoeasyapi/twitter-x-data-tweet-scraper-pay-per-result-cheapest` |

**Normalization.** Every ingester emits the shared post contract (the seam into the LLM layer): `{platform, post_id, author, author_name, author_headline, author_profile_url, title, content, url, top_comments[], reactions, comments, shares, engagement_score, posted_at}`. Dedup against prior drafts and posted history per org.

**Multi-token management** (ported from `apify_tokens.py`, upgraded):
- Org-scoped token vault: up to 10 tokens/org, **Fernet-encrypted** (MVP stored plaintext — fixed in the port), masked on read (`••••{last4}`), masked-value round-trip on save so plaintext never re-renders.
- Per-token live credit: `GET /v2/users/me/usage/monthly`, remaining = `plan_cap_usd − usage`. `plan_cap_usd` is **per token** (default 5.00 for free tier; paid plans set their real cap). Summaries cached in Redis (10 min TTL; invalidated on auth failure) instead of the MVP's N live calls before every run.
- Selection: usable tokens (remaining ≥ $0.01, not invalid/unreachable) → pick max remaining. No usable token → the run is **skipped before any actor starts**, surfaced as a `SKIPPED_BUDGET` event in the activity log and a dashboard banner.
- UI: Settings → Apify Keys — token list with credit meters (used/cap/%, cycle dates), add/remove/validate (`apify_api_` prefix check + a live usage call on save).
- **Policy:** stacking free-tier tokens is acceptable for self-hosting at personal scale; the hosted offering runs on paid Apify plans. Stated in docs; not silently encouraged.

**Cost model.** Per-actor $/1K-results table (seeded: LinkedIn 5.00, Reddit 4.04, Twitter 0.25) is **configurable per deployment**, drives the pre-run estimate and the org's monthly Apify budget meter (`apify_monthly_budget_usd`). Budget check runs at dispatch: estimated run cost + month-to-date > budget → skip with `SKIPPED_BUDGET`.

**Idempotency / no double-billing.** Ingested raw posts persist as the LangGraph checkpoint for the run; any retry of downstream stages resumes from the checkpoint and never re-calls Apify. AC: kill a worker mid-strategist → restart → drafts complete with zero additional actor runs.

### 5.3 Reply pipeline (LangGraph graph #1)

One `StateGraph` per campaign poll, executed inside a Celery `langgen` task, checkpointed to Postgres (`langgraph-checkpoint-postgres`):

```
ingest(Apify) → prefilter → scout → token_budget → strategist → finalize → persist_gate
```

1. **ingest** — §5.2 runner; emits normalized posts.
2. **prefilter** — zero-LLM-cost filters: keyword/regex prefilter (if configured), LinkedIn stale filter, dedup, org quota checks. Everything dropped here is logged with a reason.
3. **scout** — one structured LLM call per platform batch (ports the MVP's Scout, absorbing V6's separate keyword-matcher + intent-classifier). Output per selected post: `{post_id, angle_name, reply_type: NEW_COMMENT | REPLY_TO_COMMENT, target_comment_id?, confidence, reasoning}`. Prompt = platform scout template (system-seeded, org-overridable) + injected **top-performing-angles hint** from the outcomes loop (§5.7). Structured output via LiteLLM `response_format` + Pydantic validation with one fallback retry — no regex JSON scraping.
4. **token_budget** — kept from V6/devrel-agent: model-aware budget, progressive truncation (oldest comments first), persona recount on model change. The V6 "summarize remaining comments" step is **dropped** (unspecced extra LLM call; truncation only).
5. **strategist** — drafts replies. Batched 4 posts/call, 2 batches concurrent, per-post fallback call for any post missing from a batch response; **fresh DB session per concurrent batch** (the MVP's concurrency lesson, pinned by a ported regression test). Prompt = platform master context + selected angle template + post (+ target comment). Records `model_used`, prompt/response token counts, `prompt_template_version`, full `prompt_payload` (for auditability).
6. **finalize** — `draft_format.py` ported as-is: markdown stripped, model-invented CTAs removed, org's **reply hook** appended idempotently (presets: Banner / Soft / custom / none; single source of truth on the backend — the MVP's frontend duplication is fixed).
7. **persist_gate** — cost guard (LLM daily-token / monthly-cost caps, `FAILED_COST_LIMIT` — kept from V6) and safety profile checks (§5.8); surviving drafts persist as `PENDING` with confidence, angle, and signal tier (§5.7).

**Confidence** now ranks the inbox (badge + default sort) — it no longer gates any automatic action, because there is none.

### 5.4 HITL Inbox & copy-paste publishing

The core daily surface. Multi-platform inbox: platform badge, author + headline, signal tier, engagement counts, angle, confidence, draft preview. Filters: platform, campaign, status, signal tier; full-text search over source + draft (`pg_trgm`); pagination 50/page; A/R/E keyboard shortcuts and draft locking (15-min TTL, admin force-takeover, auto-release) kept from V6.

**The publish flow (D3):**
- *As a Member, I click **"Open & Copy"** on a draft.* AC: in that single click, (a) the finalized draft (hook included) is written to the clipboard, (b) the reply target opens in a new tab — the post URL, or the **specific comment permalink** when `reply_type = REPLY_TO_COMMENT`. I paste (Ctrl+V) into the platform's reply box in my own logged-in session and submit.
- Back in Sentinel the draft card is in `AWAITING_CONFIRM` state with **"I posted it"** / **"Didn't post"** actions. "I posted it" → status `POSTED`, optional live-URL paste field, row added to posted-history dedup ledger, outcomes polling scheduled (§5.7). "Didn't post" → back to `PENDING`.
- Clipboard write must survive the popup: copy executes synchronously in the click handler before `window.open` (no async-then-copy, which browsers block).
- *Edit before posting:* inline edit persists via PATCH **before** Open & Copy; the clipboard always carries the latest saved text. (V6 bug — edits discarded on approve — becomes a regression test.)
- *Reject:* requires a reason chip (`off-tone` / `wrong thread` / `factual` / `other+note`) — feeds acceptance analytics and future prompt tuning.

Draft statuses: `PENDING → AWAITING_CONFIRM → POSTED | PENDING`, plus `REJECTED`, `IGNORED`, `FAILED`, `FAILED_COST_LIMIT`. Removed from V6: `PUBLISHED`, `APPROVED`, `DELETED_BY_KILLSWITCH`, publish-failure states.

### 5.5 Persona, angle library & prompt system

- **Org persona** (kept from V6): master context, dos/don'ts, tone guidelines; token-budget validation (≤80% of context after overheads) with precomputed counts.
- **Angle library** (ported): per-platform master context + ~10–14 named angle templates each, seeded from the MVP's `prompts/*_v3.md` corpus — including the Reddit practitioner-voice safety filter, LinkedIn 30–80-word/no-hashtag-filler rules, Twitter decision-maker heuristics, and the shared war-story bank. Seeder parses the markdown convention (`{PLATFORM}-MASTER_CONTEXT`, `{PLATFORM}-ANGLE-{N}: {name}`) into `PromptTemplate` rows: `org_id = NULL` system defaults, copy-on-customize per org, integer versioning with an "update available" banner when a system default advances.
- **This seeding is `seed.py`** — the file V6's compose invoked but never existed. Seed is idempotent (upsert by name + version).
- Scout prompt and reply hook are org-editable settings with system defaults.
- Onboarding wizard (ported): brand intake form → LLM generates draft master contexts + angles → Admin reviews → apply upserts org templates. AC: nothing is applied without explicit review; wizard completable in <10 min.

### 5.6 Analyst pipeline (LangGraph graph #2)

Weekly per-org run (Celery beat, Mon 06:00 UTC, org-gated by `analyst_enabled`), plus on-demand trigger. Ports the MVP's chain as graph nodes with per-post fan-out:

```
ingest(keywords + tracked authors + competitors) → triage → cluster → stance → quotes → aggregate → render_brief
```

- **triage:** PROCESS_FULL / PROCESS_LIGHT / SKIP + relevance & signal scores + buyer-persona tag + watch-list tier.
- **cluster:** primary/secondary pillar from the org's pillar taxonomy (seeded with the MVP's default 10-pillar set; **org-editable** — the MVP hardcoded it).
- **stance:** PROBLEM_PRESENT / PROBLEM_CRITIQUED / NEUTRAL + confidence + evidence quote.
- **quotes:** quote-worthy claims (PROCESS_FULL only).
- Each node degrades gracefully to defaults rather than dropping the post; concurrency ≤5; cross-week dedup against prior classifications.
- **render_brief:** Python aggregation (pillar counts, week-over-week momentum, competitor activity) + one LLM call → markdown **Intel Brief** (exec summary, clusters, stance table, quotes, content gaps, recommended actions). Stored unique per org+week; UI: brief list, stats, 4-week pillar-momentum forecast, download.
- Watch-list names, buyer personas, competitors: org-scoped tables (MVP hardcoded Tier-1 names in code — moved to data).

### 5.7 Engagement outcomes & analytics

- Outcomes poller (maintenance queue, every 6 h): for `POSTED` drafts with a live URL, re-scrape metrics at +24 h and +72 h — Reddit via free `.json` endpoint, LinkedIn via Apify metric re-scrape, Twitter via the search actor. Records reactions/replies/reposts + `got_response`.
- **Feedback loop:** top-performing angles per platform (last 30 days) are injected as a hint into the Scout prompt — measurably the MVP's differentiator; kept verbatim.
- **Signal tiers:** HIGH/MEDIUM computed at draft time from watch-list authors, buyer-persona headline match + engagement ≥10, or engagement ≥50 (thresholds org-configurable).
- Analytics page: angle leaderboard, platform performance, acceptance & edit rates (§4 metrics), Apify + LLM spend meters.

### 5.8 Safety & compliance

- **Posture:** copy-paste-only publishing means every post is a human action from the human's own session — Sentinel never automates a platform account. This resolves V6's largest open risk (automated posting vs Reddit bot/spam policy) by construction. Remaining obligations:
  - **Disclosure:** org-level setting — disclosure line appended to drafts (default **on** for Reddit: e.g. "(I work on &lt;product&gt;)" where the draft references the product; the Reddit angle corpus already enforces product silence in most angles). Admin-configurable per platform.
  - **Volume:** per-subreddit safety profiles (kept from V6): `max_daily_drafts`, `require_manual_review` (now always true by construction), notes. Extended to LinkedIn/Twitter as per-campaign daily draft caps. Conservative defaults (≤3 drafts/subreddit/day).
  - **Scraping ToS:** ingestion happens through Apify's actors under Apify's terms; the deployment README states the residual risk plainly and requires orgs to accept it at onboarding. Hosted tier: paid Apify plans only (§5.2 policy).
- **Kill switch** (scoped down): one click pauses all org campaigns and revokes queued pipeline tasks. No post deletion — Sentinel never posted anything. AC: after kill switch, zero new drafts appear; audit-logged.
- **GDPR:** V6 retention schedule kept (REJECTED/FAILED purged at 7 days, webhook events at 30, audit logs 2 years) with one change: source-post content for `POSTED` drafts is retained 12 months then reduced to URL + metrics (V6's "indefinite" was unjustified). Erasure flow kept.
- **Data minimization:** author display fields are stored for review context (name/headline/profile URL — needed for signal tiers); documented in the privacy note. No platform credentials of any kind are stored.

### 5.9 Auth, tenancy & admin

Kept from V6/devrel-agent with the known defects fixed (M0, §12): Clerk (JWT, orgs, webhook sync with svix + idempotency), RBAC (ADMIN/MEMBER/SUPER_ADMIN), org-scoped everything.
- **Fix:** Clerk org/user IDs mapped to internal integer IDs at the auth dependency (one lookup, cached) — V6's string-vs-int mismatch is M0's first item.
- **Fix:** every frontend hook attaches the Clerk JWT (the `useApi` client becomes the only transport).
- Webhook handler lives in **FastAPI** (single implementation; the Next.js stub is deleted — resolves the V6 contradiction).
- `/admin` requires platform `SUPER_ADMIN` (not org-admin); all admin endpoints authenticated (V6 shipped two world-readable ones).
- Rate limiting keyed per Clerk user ID (falls back to IP for unauthenticated routes).
- Multi-org users: supported to Clerk's extent — org context comes from the active-org claim in the JWT per request; the `users.org_id` single-FK column is replaced by an org-membership relation.

---

## 6. Non-functional requirements

| Area | Requirement |
|---|---|
| Reference hardware | `docker-compose.lite.yml` runs the full stack (API, 1 worker concurrency 2, beat, Redis, frontend) on a Raspberry Pi 4 / 4 GB; Postgres local or external (Neon supported — `pool_pre_ping`, `pool_recycle=300`, SSL args honored). |
| Scale envelope (V1) | ≤25 orgs/instance (hosted), ≤20 campaigns/org, ≤2,000 drafts/org/month, ≤10 Apify tokens/org. Lite: 1–2 active orgs. |
| Latency | Inbox list P95 < 500 ms at 10k drafts/org; Open & Copy click-to-clipboard < 100 ms. |
| Freshness SLO | §4 row 1; scheduler tick ≤60 s. |
| Reliability | Pipeline runs resumable from checkpoint after worker death (§5.2 AC). Redis loss degrades gracefully: credit summaries re-fetch, schedules re-enqueue on next tick, quota counters rebuild conservatively (a lost daily-draft counter resets caps to safe defaults, never to unlimited). |
| Backups | Documented `pg_dump` schedule (self-host) / provider PITR (Neon). `ENCRYPTION_SECRET` backed up separately; documented restore drill. |
| Observability | structlog JSON (kept from V6), in-app activity log (SystemLog, ported), optional Prometheus/Grafana profile. Sentry required for hosted. |
| Security | Fernet-encrypted secrets w/ key versioning + rotation script (kept); no plaintext secrets in DB (MVP regression fixed); CORS restricted to the deployed frontend origin; Cloudflare tunnel / Tailscale supported deployment paths. |
| Testing | Ported regression tests: session-per-batch concurrency, draft formatting, LinkedIn normalization + stale filter. New required suites: auth ID-mapping, scheduler enqueue, Apify runner (mocked), token selection, copy-paste state machine. CI runs tests (the MVP's CI only built images). Coverage gate ≥80% on `api/` + `utils/`. |

---

## 7. Out of scope for V1

- Any programmatic posting (PRAW, tweepy, LinkedIn API) and Auto-Pilot mode.
- HN & Mastodon (code present behind `ENABLE_EXTRA_PLATFORMS`, default off, unsupported).
- Billing, plans, payments (§13).
- Conversation continuation (replies to the org's posted replies are surfaced via outcomes metrics only — no threaded follow-up drafting).
- Prompt-optimization tooling (`optimize_prompts.py` stays a dev script).
- i18n, mobile.

---

## 8. Data model delta (vs TRD V6 §12)

**New tables:** `OrgApifyToken` (org_id, label, encrypted_token, key_version, plan_cap_usd, is_active); `PostedHistory` (org_id, platform, post_id — dedup ledger, composite unique); `EngagementOutcome`; `AnalystRun`, `PostClassification`, `TopicCluster`, `StanceObservation`, `QuoteWorthyClaim`, `IntelBrief` (unique org+week); `TargetAuthor`, `Competitor`; `OrgMembership` (replaces `users.org_id` FK); `SystemLog` (org-scoped activity feed).

**Changed:** `Campaign` gains `platform`, per-platform filter columns (§5.1), loses auto-pilot fields. `DraftReply` gains `platform`, `angle_name`, `reply_type`, `reply_target_url`, `target_comment_id/content`, `signal_tier`, `author_name/headline/profile_url`, `reactions/comments/shares`, `posted_at_source`, `live_url`, `reject_reason`; status enum per §5.4; loses `is_auto_pilot_published` + publish-attempt fields. `PromptTemplate` gains `platform` + `type` (MASTER_CONTEXT/ANGLE/SCOUT/ANALYST_*).

**Removed:** `RedditAccount` (no posting credentials), auto-pilot Redis counters, `praw_publish` queue and its idempotency keys.

**Kept:** `Organization`, `User`, `OrgLLMConfig`, `OrgPersona`, `SubredditSafetyProfile` (extended per §5.8), `AuditLog`, `ProcessedWebhookEvent`.

Celery queues: `scraper` (Apify ingest), `langgen` (both graphs), `maintenance` (locks, outcomes poller, retention purges, webhook purge — now actually on the beat schedule). `praw_publish` deleted.

---

## 9. Source-of-truth for the port

| Ported from `social-agent` | Into | Notes |
|---|---|---|
| `services/apify_tokens.py` | Apify vault service | + Fernet, + Redis cache, + per-token cap |
| `services/linkedin_ingestion.py` REST engine + normalizer + stale filter | Generic Apify runner + LinkedIn ingester | Reddit/Twitter rewritten onto same engine |
| `routers/pipeline.py::build_actor_input`, `build_twitter_input` | Ingestion input builders | Lifted out of router |
| `services/llm.py` Scout/Strategist bodies | Graph #1 nodes | Structured outputs replace regex parsing |
| `services/analyst.py` chain | Graph #2 nodes | Taxonomy/watch-list → org data |
| `services/draft_format.py` (+ tests) | `finalize` node | As-is; hook config org-scoped |
| `services/outcomes.py` | Outcomes poller | Org-scoped |
| `backend/prompts/*_v3.md` + `scripts/init_db.py` parsers | `seed.py` + system PromptTemplates | The missing V6 seeder |
| Onboarding generate/apply endpoints | Onboarding wizard | Review-before-apply kept |
| Keys/credit-meter UI, cost page, activity page, intel pages | devrel-agent dashboard | Restyled to existing shadcn theme |
| `test_pipeline_concurrency.py`, formatting & normalization tests | test suite | Regression pins |

**Not ported:** APScheduler (→ Celery beat), `PIPELINE_STATUS` global (→ task state), `RawPost`/`ScoutSelection` cache (→ LangGraph checkpoints), `AppSettings` singleton (→ org config), env-var key injection, tweepy/Twitter posting, `codegrab-output.md`.

---

## 10. TRD V6 disposition

| TRD V6 section | Disposition |
|---|---|
| §2 Stack | KEEP + add `langgraph`, `langgraph-checkpoint-postgres`, `apify` cost table; remove `praw` from scraping role |
| §3 Auth/Clerk/encryption | KEEP with §5.9 fixes (ID mapping, webhook owner = FastAPI, /admin gating, per-user rate keys) |
| §4.3 Nodes 1–2 (PRAW fetch, keyword matcher) | **SUPERSEDED** by §5.2 ingest + prefilter |
| §4.3 Node 3 (intent classifier) | **SUPERSEDED** by Scout |
| §4.3 Node 4 (token budget) | KEEP (drop comment-summarize step) |
| §4.3 Node 5 (generator) | RESHAPED into batched Strategist + finalize |
| §4.3 Node 6 (confidence gate) | REPURPOSED: ranks inbox; no auto-action |
| §4.5–4.6 Reddit rate limits, PRAW token mgmt | **REMOVED** (no PRAW) |
| §4.7 API rate limits | KEEP (per-user keying fix) |
| §4.8 Cost guard | KEEP + Apify budget (§5.2) |
| §4.10 Scheduler (ZSET + beat) | KEEP; wire `enqueue_campaign` (M0) |
| §5.6 Auto-Pilot | **REMOVED** |
| §5.7 Kill switch | SCOPED DOWN to pause-only |
| §5.8 TryEval export | **REMOVED** (TryEval integration dropped in V7) |
| §7 Observability, §8 GDPR, §9 NFR | KEEP with §5.8/§6 amendments |
| §10 Infra/compose | KEEP minus `praw_publish` worker |
| §11 Frontend UX | AMENDED per §5.4 (Open & Copy flow, multi-platform inbox) |
| §12 Schema | AMENDED per §8 |
| §13 Test plan | KEEP; publishing E2E rows replaced by copy-paste state-machine tests |
| `docs/phase_1..6` | **DELETED** (phase_3 ≡ phase_4 byte-identical; superseded by §12 below) |

---

## 11. Frontend surface (V1)

`/dashboard` (pending count, pipeline state, budget meters, activity feed — replaces the mock page) · `/dashboard/inbox` (multi-platform, Open & Copy) · `/dashboard/campaigns` (unified, platform-aware, AI suggestions) · `/dashboard/prompts` (persona + angle library + scout prompt + reply hook) · `/dashboard/intel` (Analyst briefs + forecast) · `/dashboard/analytics` (leaderboards, acceptance, spend) · `/dashboard/safety` · `/dashboard/settings` (LLM vault, **Apify Keys w/ credit meters**, team, audit, kill switch — wired) · `/onboarding` · `/admin` · `/select-org` (currently a 404 the middleware redirects to — must exist).

---

## 12. Milestone plan (replaces phase folders)

**M0 — Make the base runnable (unblockers).** Real initial migration (V6's is empty), `seed.py` (=prompt seeder), missing deps (`langgraph`, `svix`, `PyJWT`), package layout fix, Clerk↔internal ID mapping, JWT on all frontend hooks, wire `enqueue_campaign`, delete dead PRAW publish path, authenticated admin endpoints, `/select-org` page. *Exit: fresh `docker compose up` → onboard an org → create a campaign → scheduler ticks (ingest may still be stubbed).*

**M1 — Apify layer.** Runner + actor registry, token vault + credit caching + Settings UI, per-platform ingesters + normalization + validation, cost estimate + budget gating, campaign form platform variants. *Exit: a campaign produces normalized posts in the checkpoint store on real Apify runs, within budget gates, on the Pi profile.*

**M2 — Reply pipeline + inbox.** Graph #1 with Postgres checkpointing, prompt corpus seeded, Scout/Strategist/finalize ported with structured outputs, cost guard + safety caps wired, inbox multi-platform UI, Open & Copy state machine, reject reasons, edit-before-copy. *Exit: §4 freshness + acceptance metrics measurable end-to-end; kill-a-worker resume test passes.*

**M3 — Analyst + outcomes.** Graph #2, org taxonomies/watch-lists/competitors, intel UI, outcomes poller, top-angles feedback into Scout, analytics page. *Exit: weekly brief generates for a real org; angle hint visibly changes Scout selections.*

**M4 — Hardening & release.** Quotas, retention/purge jobs on beat, compliance defaults + onboarding acceptance, backup/restore docs, Pi + Cloudflare tunnel verification, CI with tests + coverage gate, OSS license decision executed, README/self-host guide. *Exit: tagged V1, one external self-hoster deploys from docs alone.*

---

## 13. Open decisions

| # | Decision | Owner | Default if unresolved |
|---|---|---|---|
| O1 | Monetization: plans/quotas/payment provider for hosted tier | Shubham | V1 ships self-host + invite-only hosted, no billing |
| O2 | OSS license (product is called OSS throughout) | Shubham | Apache-2.0 |
| O3 | Disclosure default per platform (§5.8) — exact copy | Shubham | On for Reddit product-mentions; off elsewhere |
| O5 | Hosted-tier Apify account model: platform-owned pooled tokens vs strict BYOK | Shubham | Strict BYOK |
| O6 | Actor version pinning policy (actors mutate under fixed IDs) | Eng | Pin via org override + weekly canary dry-run alert |
