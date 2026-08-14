# AGENTS.md — Investing Companion

Canonical, tool-agnostic, self-contained context for this repo. `CLAUDE.md` imports this file; don't
duplicate its content there. Anything volatile, personal, or deploy-specific lives in the gitignored
`CLAUDE.local.md` (see `CLAUDE.local.md.example`), not here.

## What Investing Companion is

Self-hosted, dual-stack equity-analysis dashboard: FastAPI backend + Next.js frontend. It provides
watchlists, fundamental/ratio analysis, market overviews, AI-powered insights, price alerts (Discord),
trade tracking, and an earnings/macro calendar. Data is pulled by scheduled Celery tasks and stored in
TimescaleDB; the frontend reads only from the API, never from external sources directly.

- **Deployment posture**: single-user, self-hosted via Docker Compose. Andrew's prod is a Synology NAS
  behind Caddy; a separate public **demo** runs on EC2 at `invest.smithadifd.com`.
- **Non-goals**: multi-tenant SaaS; a brokerage/order-execution system (Schwab is read-only quotes);
  storing anyone else's credentials. Not a general-purpose charting platform.

## Tech stack

| Layer | Technology |
|-------|------------|
| Backend | Python 3.11+ (CI runs 3.12) / FastAPI / SQLAlchemy 2.0 async |
| Frontend | Next.js 16 (App Router) / React 19 / TypeScript 6 (strict) |
| Database | PostgreSQL 15 + TimescaleDB hypertables |
| Cache / broker | Redis |
| Task queue | Celery (worker + beat), Redis broker |
| Charts | TradingView Lightweight Charts |
| Frontend state | Zustand (client) + TanStack Query (server) |
| AI | Claude API (user-provided key) |
| Notifications | Discord webhooks |
| Deployment | Docker Compose (local / prod / demo) |

## Commands

```bash
# --- Full stack (Docker) ---
docker compose up -d                          # start all services
docker compose exec api alembic upgrade head  # run migrations (hits the running DB)

# --- Backend (local, hot reload) ---
cd backend && python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000     # API at :8000, docs at /docs
pytest --cov=app                              # tests (~286 backend test fns)
ruff check backend/                           # lint (CI gate)
alembic revision --autogenerate -m "msg"      # new migration
alembic upgrade head                          # apply migrations

# --- Frontend (local) ---
cd frontend && npm install
npm run dev                                   # :3000
npm run type-check                            # tsc --noEmit (CI gate)
npm run lint                                  # eslint src/ (CI gate)
npm test                                      # vitest run
```

Live-service flags: `alembic upgrade head` mutates whatever DB `DATABASE_URL` points at. Yahoo/Alpha
Vantage/Schwab calls hit real providers. Deploy scripts under `scripts/` touch prod/demo hosts — do not
run them as part of ordinary code work.

## Repo map

```
backend/app/
  api/v1/endpoints/   route handlers: account, ai, alert, auth, dashboard, equity,
                      event, export, lesson, market, news, ratio, schwab, settings,
                      trade, trigger, watchlist
  core/               config (config.py), security
  db/models/          SQLAlchemy models (account, alert, economic_event, equity,
                      fundamentals, handoff, lesson, price_history, ratio, session,
                      trade, trigger, user, user_settings, watchlist)
  schemas/            Pydantic schemas (incl. context_pack.py — advisor contract versions)
  services/           business logic (analysis/, data_providers/, notifications/, context_pack.py …)
  tasks/              Celery: celery_app.py, alerts, events, export, price_history, schwab, utils
  utils/
backend/tests/        pytest suite
backend/alembic/      migrations
backend/scripts/      seed_demo_users.py, seed_demo_data.py, seed_macro_events.py, seed_trades.py, premarket_pulse.py
frontend/src/
  app/                App Router pages: alerts, calendar, equity, login, market, news,
                      playbook, ratios, settings, trades, watchlists
  components/         React components grouped by domain (ai, alert, charts, trade, trigger, ui, …)
  lib/                api/ (client), hooks/, contexts/, utils/
  types/              TypeScript types
docker/               Dockerfile.{backend,frontend}[.prod]
docs/                 architecture, api contracts, advisor-starter-kit, ROADMAP, issues/ (sessions/ & plans/ gitignored)
docs-site/            standalone docs site (own CI, path-ignored by main CI)
scripts/              deploy-synology.sh, deploy-demo.sh, backup.sh, restore.sh, test-build.sh
```

## Architecture in brief

Browser → Caddy → {Next.js frontend, FastAPI backend}. Backend layering is **endpoints → services →
models** — endpoints stay thin; business logic lives in `services/`. Celery tasks pull from providers on
a schedule, normalize, and write to TimescaleDB; the frontend never calls external data sources directly.

**Data providers** are pluggable in `backend/app/services/data_providers/` behind the
`MarketDataProvider` ABC (`base.py`) — each provider declares its `capabilities`
(quote/history/fundamentals/search). The **resilience layer** (`resilience.py`) wraps a
provider in retry + exponential backoff + a circuit-breaker (`ResilientProvider`) and chains
providers with health-based failover (`FailoverQuoteProvider`): when the primary's breaker is
open or it returns no data, the call falls through to a fallback and the quote is stamped
`stale`/`source` so the UI can flag degraded data. `get_quote_provider()` (`__init__.py`)
builds the chain — the sibling of `get_extended_quote_provider` (extended-hours selection).

| Provider | Role | Usage | Notes |
|----------|------|-------|-------|
| Yahoo Finance | Primary | Quotes, fundamentals, history, search; `^VIX` and other index/forex/futures | Unofficial — be gentle; may break; now retry/backoff/breaker-wrapped |
| Stooq | Fallback | Quotes + daily history (`stooq.py`) | **No key**; US equities/ETFs; always active |
| Alpha Vantage | Fallback (opt-in) | Quotes (`alpha_vantage.py`) | Free key `ALPHA_VANTAGE_API_KEY`, ~5 req/min; key-gated, inert without it |
| Massive (Polygon.io) | Fallback (opt-in) | History, fundamentals, search + delayed quotes (`massive.py`) | Paid key `POLYGON_API_KEY`; quotes are 15-min delayed (`delayed_quotes=True`) so they rank below every live source. Per-product entitlements declared in `MASSIVE_ENTITLEMENTS` |
| Schwab | Extended-hours | Real-time + pre/post-market quotes for briefings | Opt-in OAuth; tokens expire every 7 days |

**AI advisor contract** — an external Claude advisor reads a versioned context pack and writes changes
back through a handoff loop. The single source of truth is `docs/api/handoff-schema.md` (pack shape,
`SCHEMA_VERSION`) and `docs/api/advisor-actions.md` (write vocab, `ADVISOR_ACTIONS_VERSION`); both
versions live in `backend/app/schemas/context_pack.py`, and `UNSUPPORTED_FEATURES` in
`backend/app/services/context_pack.py` is the live authority on capability. See § Conventions for the
sync rule. The operational handoff-execution API reference (how Andrew applies pasted handoff blocks) is
in `CLAUDE.local.md`, not here — it's operational, not a repo fact.

## Database / storage

- PostgreSQL 15 + **TimescaleDB** (hypertables for time-series, e.g. price history). The extension is
  required — a vanilla Postgres won't start the app cleanly.
- Schema source of truth = SQLAlchemy models in `backend/app/db/models/`. Migrations via **Alembic**
  (`alembic revision --autogenerate` → review → `alembic upgrade head`). Never hand-edit the DB to match
  a model; write a migration.
- Encrypted secrets (Claude API key, `SCHWAB_TOKEN`) are stored per-user in the `user_settings` table,
  not in env or plaintext.

## Conventions

**Python (backend)** — type hints everywhere; Pydantic for all request/response schemas; SQLAlchemy 2.0
style (`mapped_column`); async for I/O; service-layer pattern; ruff-clean. Meaningful names, comments
only for non-obvious logic.

**TypeScript (frontend)** — strict, no `any`; functional components + hooks; TanStack Query for server
state, Zustand for client state; component files `ComponentName.tsx`, hooks `useHookName.ts`.

**General** — Conventional Commits (`feat:`, `fix:`, `docs:`, …). Public repo with branch protection:
work on a feature branch → PR → CI green → squash-merge.

**Advisor-contract sync (cross-cutting — same PR, not a follow-up):** when a change touches what the app
**exports** or the actions the executor **supports**, update the contract in the same PR:

| Change | Update | Rule |
|--------|--------|------|
| Context pack adds/renames a field | `docs/api/handoff-schema.md` + `SCHEMA_VERSION` | Bump per its MAJOR.MINOR rule, add changelog row, update the `(vX.Y)` header stamp |
| New/changed/removed action, field, or enum | `docs/api/advisor-actions.md` + `ADVISOR_ACTIONS_VERSION` | Bump (MINOR=additive, MAJOR=rename/removal); write-side version, independent of the pack's `schema_version` |
| A feature removes a limitation | `UNSUPPORTED_FEATURES` in `services/context_pack.py` | Shrink the live list; never hardcode bug lists in the contract docs |

The `docs/advisor-starter-kit/` points at the two `docs/api/*` contracts, so ordinary feature work needs
no kit edits — only touch the kit when the loop's mechanics or the kit's own structure change.

## Testing strategy

- **Backend**: pytest — service/unit tests, API integration tests against a test DB, ruff as a lint gate.
  CI spins up TimescaleDB + Redis service containers on Python 3.12.
- **Frontend**: vitest — hooks (`useAlert`, `useTrade`) with a mocked API client, modal/component tests
  with `user-event`, page-level integration with mocked hooks. `type-check` and `lint` are CI gates.
  E2E (Playwright) is future work.
- CI (`.github/workflows/ci.yml`) runs backend + frontend + a Docker build; it **path-ignores** `docs/`,
  `docs-site/`, and `**/*.md`, so pure-docs PRs skip the heavy jobs (a root file like `.editorconfig`
  still triggers a full run).

## Demo mode

Public demo at `invest.smithadifd.com`, gated by `DEMO_MODE=true` (backend) / `NEXT_PUBLIC_DEMO_MODE`
(frontend):

- `require_not_demo` FastAPI dependency returns **403** on all trade/watchlist/alert/event/settings/AI
  mutations; registration is disabled; a `DemoBanner` shows on every page with the shared login
  (`demo@example.com` / `demo1234!`).
- Celery Beat: alert-checking and notification schedules are disabled; event refresh stays active.
- Seeds: `backend/scripts/seed_demo_users.py` (user + watchlists + synthetic trades/alerts) and
  `seed_demo_data.py` (ratios + macro events). Live Yahoo data via Celery, no API key.
- Deployment is EC2 + Caddy with cron auto-deploy on `main` and a weekly Sunday re-seed. Details and host
  specifics live in `CLAUDE.local.md` / `scripts/deploy-demo.sh`, not here.

## Environment

Config is read via `backend/app/core/config.py`; see `.env.example` and `.env.production.example` for the
full shape. Never commit real values — prod env lives in gitignored `.env.production` / `.env.demo` on
the hosts.

| Var | Purpose |
|-----|---------|
| `DATABASE_URL` | `postgresql+asyncpg://…` (TimescaleDB) |
| `REDIS_URL` | Cache + Celery broker |
| `SECRET_KEY` | JWT signing |
| `CLAUDE_API_KEY` | Optional; users provide their own (stored encrypted per-user) |
| `DISCORD_WEBHOOK_URL` | Alert notifications |
| `ALPHA_VANTAGE_API_KEY` / `POLYGON_API_KEY` | Optional providers |
| `MASSIVE_ENTITLEMENTS` | Which Massive products the key holds (`quote,history,fundamentals,search`); unset/blank = all. A surface left off routes to the next provider |
| `SCHWAB_APP_KEY` / `SCHWAB_APP_SECRET` / `SCHWAB_CALLBACK_URL` / `FRONTEND_URL` | Schwab OAuth (see gotchas) |
| `NEXT_PUBLIC_API_URL` | Frontend → API base |
| `DEMO_MODE` / `NEXT_PUBLIC_DEMO_MODE` | Demo restrictions / banner |

## Critical gotchas

- **Schwab OAuth is weekly, tailnet-only.** Tokens expire every 7 days — re-auth is a one-click
  Settings → API Keys → Connect Schwab flow; the callback is served on the tailnet, and
  `SCHWAB_CALLBACK_URL` must exactly match the Schwab developer-portal registration. Missing/expired
  token silently falls back to Yahoo by design.
- **`^VIX` and other indices/forex/futures don't come from Schwab** — they delegate per-symbol to Yahoo.
  Don't "fix" a missing Schwab quote for these; the fallback is intentional.
- **TimescaleDB is mandatory** (see § Database) — a plain Postgres image is not a drop-in.
- **Advisor contract drift**: skipping the § Conventions sync-table on an export/action change ships a
  pack whose version stamps lie to the advisor. Treat it as part of the change, not a follow-up.
- **A stored value without its timestamp is indistinguishable from a fresh one.** `alerts.last_checked_value`
  is written only by the scheduled check loop, and only for *active* alerts — so it freezes silently the
  moment an alert is deactivated, and for three weeks read as a confident "2.78% away" on a rung price had
  long since left (#259). Anything derived from a persisted observation must carry, and check, its
  `*_at` companion; `AlertService._mark_checked` is the single writer that keeps the pair together.
  The read side treats unknown age as stale, never as current.
- **`docs/issues/017` (Schwab OAuth callback) is off-limits to routine edits** — it tracks a deliberate
  blocked-state decision.
- **The macro calendar does not update itself, and deploying does not fix it.** `FRED_API_KEY` is unset
  in prod, so `FredCalendarProvider.is_configured` is False, the daily `events.refresh_macro_calendar`
  Celery task no-ops, and the hand-maintained date lists in `backend/scripts/seed_macro_events.py` are
  the *only* thing that populates CPI/NFP/GDP/PCE/PPI/retail sales. Correcting a date is therefore two steps: ship
  the list change, then run `python -m scripts.seed_macro_events --all` against prod. A re-run
  self-cleans (rows update in place by recurrence key; entries dropped from a list are retired), so
  `--clear` is not needed. Adding a series the live FRED feed doesn't cover also means adding it to
  `seed_only_specs`, or it silently vanishes the moment a FRED key is ever set.
