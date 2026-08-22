# Sentinel

DevRel teams need to show up where developers already talk — Reddit threads, LinkedIn posts, X/Twitter conversations — with useful, on-brand replies, fast enough that the conversation is still alive. Doing this manually means hours of scrolling; doing it with naive automation gets accounts banned and brands embarrassed.

Sentinel monitors the channels an org cares about, uses an LLM pipeline to select the conversations worth joining and draft replies in the org's voice, and puts every draft in front of a human. A human posts every reply — Sentinel opens the target post in a new tab with the finished draft already on the clipboard. Nothing is ever published programmatically: the unit of automation is the *draft*, not the *post*. Orgs bring their own LLM keys and Apify (scraping) tokens, which Sentinel encrypts at rest and never re-displays.

**Status:** M0 (base runnable) and M1 (Apify ingestion layer) are merged into `develop`. M2 (reply pipeline + inbox), M3 (analyst pipeline + outcomes), and M4 (hardening & release, including this CI setup) are in progress. See [`docs/PRD_V7_Sentinel.md`](docs/PRD_V7_Sentinel.md) §12 for the full milestone plan and current exit criteria.

---

## Quickstart (Docker Compose)

Requires Docker and Docker Compose.

1. Copy the env template and fill in secrets:

   ```bash
   cp .env.example .env
   ```

   At minimum, set:
   - `POSTGRES_PASSWORD`, `REDIS_PASSWORD` — any strong values.
   - `ENCRYPTION_SECRET` — exactly 64 hex chars, generate with
     `python -c "import secrets; print(secrets.token_hex(32))"`. This is the
     BYOK vault's Fernet key; back it up separately from your DB backups.
   - `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`, `CLERK_SECRET_KEY`, `CLERK_JWKS_URL` —
     from a [Clerk](https://clerk.com) application (Clerk handles auth and
     org/tenancy for Sentinel).
   - `APIFY_TOKEN` — an [Apify](https://apify.com) API token; Apify actors do
     all the Reddit/LinkedIn/X scraping, so local workers only orchestrate and
     call LLMs.
   - `OPENROUTER_API_KEY` — dev-only fallback used until an org saves its own
     LLM key in-app (Sentinel is BYOK; this key is not required once orgs have
     their own vaulted keys).

2. Bring the stack up:

   ```bash
   docker compose up -d --build
   ```

   This starts Postgres, Redis, the FastAPI backend (runs Alembic migrations
   and seeds the default prompt corpus on boot), three Celery workers
   (`scraper`, `langgen`, `maintenance`), Celery beat, and the Next.js
   frontend.

3. Open `http://localhost:3000`, sign in via Clerk, and follow the onboarding
   wizard to create your first org and campaign.

Optional observability profile (Prometheus + Grafana):

```bash
docker compose --profile metrics up -d
```

### Lite deployment (Raspberry Pi + Cloudflare tunnel)

`docker-compose.lite.yml` collapses all three Celery queues into a single
low-concurrency worker and is sized to run the full stack — API, one worker,
beat, Redis, frontend — on a Raspberry Pi 4 (4 GB). Apify carries all scraping
compute, so the Pi only orchestrates and calls LLM APIs; nothing scrapes
locally.

```bash
docker compose -f docker-compose.lite.yml up -d
```

Expose it publicly via a
[Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/)
(or Tailscale) rather than opening ports on the Pi directly. This profile is
intended for one to two active orgs; use the full `docker-compose.yml` above
for anything larger.

---

## Architecture

```
                     ┌─────────────┐
   browser  ───────► │  frontend   │  Next.js 16 (App Router, Clerk auth)
                     └──────┬──────┘
                            │ /api/* (rewritten)
                     ┌──────▼──────┐        ┌──────────────┐
                     │   backend   │◄──────►│  Postgres    │  campaigns, drafts,
                     │  (FastAPI)  │        │  (+ LangGraph│  vaults, analyst data,
                     └──────┬──────┘        │  checkpoints)│  checkpoint store
                            │ enqueue                └──────────────┘
                     ┌──────▼──────┐
                     │    Redis    │  scheduler ZSET, rate limits, Apify
                     │             │  credit cache, Celery broker
                     └──────┬──────┘
             ┌──────────────┼──────────────────┐
      ┌──────▼─────┐  ┌─────▼──────┐   ┌───────▼────────┐
      │  worker    │  │  worker    │   │    worker      │
      │  scraper   │  │  langgen   │   │  maintenance   │
      │ (Apify     │  │ (both      │   │ (lock release, │
      │  ingest)   │  │  LangGraph │   │  outcomes poll, │
      │            │  │  pipelines)│   │  retention)     │
      └──────┬─────┘  └────────────┘   └────────────────┘
             │
      ┌──────▼─────┐
      │   Apify     │  actors: Reddit / LinkedIn / X-Twitter scraping
      │  (external) │  (all scraping compute lives here, not on the host)
      └────────────┘
```

Two LangGraph `StateGraph` pipelines run in the `langgen` worker, both with
Postgres checkpointing (crash-resumable):

- **Graph #1 — Reply pipeline.** Scout (selects worth-joining conversations)
  → Strategist (drafts a reply in the org's voice, per persona/angle library)
  → finalize (formatting, safety/cost checks) → lands in the HITL inbox as a
  `PENDING` draft. A human edits if needed, clicks Open & Copy (clipboard +
  new tab to the source post), pastes it themselves, then confirms posted in
  Sentinel. Nothing is posted programmatically.
- **Graph #2 — Analyst pipeline.** Runs weekly per org: classifies posts,
  clusters topics, tracks stance/competitors, and produces an `IntelBrief`
  surfaced in `/dashboard/intel`.

See [`docs/PRD_V7_Sentinel.md`](docs/PRD_V7_Sentinel.md) for the full product
spec, and [`docs/TRD_V6_Final_Sentinel_DevRel.md`](docs/TRD_V6_Final_Sentinel_DevRel.md)
for the engineering sections it still defers to.

---

## Development

Backend (FastAPI + Celery + SQLAlchemy async, managed with
[uv](https://docs.astral.sh/uv/)):

```bash
uv sync --project backend
PYTHONPATH=. uv run --project backend pytest tests/ -q   # run from the repo root
```

Three integration tests in `tests/test_postgres_integration.py` need a real
Postgres + Redis (they exercise `ON CONFLICT`, FK cascades, and asyncpg engine
lifecycle across repeated `asyncio.run()` calls that sqlite can't reproduce
faithfully) — they're skipped automatically when those aren't reachable, and
run in CI against service containers.

Frontend (Next.js 16):

```bash
cd frontend
npm ci
npm run build
```

CI (`.github/workflows/ci.yml`) runs both on every PR into `develop`/`main`
and on every push to `develop`.
