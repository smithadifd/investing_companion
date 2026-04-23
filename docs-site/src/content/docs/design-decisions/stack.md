---
title: Why this stack
description: The reasoning behind FastAPI, Next.js, Postgres with TimescaleDB, Celery, and Docker Compose on a NAS.
---

This page exists so the reasoning behind the major stack choices doesn't evaporate. Six months from now, when the temptation to swap a piece shows up, the tradeoffs are here in one place.

For the shape of the running system, see [/architecture/overview/](/architecture/overview/).

## FastAPI for the backend

Investing Companion's API is a lot of fan-out I/O: quote requests, historical pulls, provider fetches, AI streaming. Blocking request handlers would be a bad fit.

FastAPI was picked for three reasons that show up repeatedly in the code:

- Async-first request handling. The data provider services (Yahoo Finance, Alpha Vantage, Polygon, Claude) are all network-bound, and FastAPI lets endpoints await them without tying up a worker.
- Pydantic schemas. Request and response validation is written once and reused by the OpenAPI docs at `/docs`. The schemas live under `backend/app/schemas/` and double as the contract the frontend types against.
- Streaming responses. The AI analysis endpoint (`POST /api/v1/ai/analyze`) streams via SSE. FastAPI supports that natively.

Django and Flask aren't discussed in the source docs, so they aren't compared here. Python was the baseline because the analysis layer (technical indicators, fundamentals aggregation, position sizing math) is more at home in Python than in Node.

## Next.js as a separate frontend

The UI is its own app at `frontend/`, not server-rendered templates out of FastAPI.

The reasoning the codebase reveals:

- The dashboard is interactive. TradingView Lightweight Charts, tabbed equity detail views, inline AI chat, drag-and-drop CSV imports. That's a React app, not a set of templates.
- TypeScript across the frontend gives type safety against the Pydantic-defined API contracts. Types live under `frontend/src/types/`.
- The App Router is used for file-based routing and server components where they help; client state lives in Zustand and server state in TanStack Query.

A SPA-only frontend would have worked, but Next.js lets pages that don't need interactivity render on the server, and standalone output (`next.config.js`) makes the production Docker image small. The cost is running two processes — Next on port 3000, FastAPI on port 8000 — behind a reverse proxy. That cost is paid every deployment. It's been worth it.

## Postgres with TimescaleDB

One database, two access patterns: relational data for users, watchlists, alerts, trades; time-series data for price history and indicators.

The decision was to use Postgres for both and add the TimescaleDB extension for the time-series tables rather than run a second database.

- `price_history` is a TimescaleDB hypertable keyed on `(equity_id, timestamp)`. Bars accumulate fast across a watchlist of dozens of symbols over multi-year windows; a hypertable handles that better than a plain table.
- Everything else — `equities`, `watchlists`, `watchlist_items`, `alerts`, `trades`, `trade_pairs`, `users`, `sessions` — is ordinary relational data with foreign keys. Postgres is the right shape.
- SQLAlchemy 2.0 plus Alembic gives one ORM, one migration tool, one connection pool across both kinds of tables.

A dedicated time-series database (InfluxDB, QuestDB) isn't discussed in the source docs. The extension approach keeps operational surface area small: one database process to back up, one to monitor. SQLite also isn't discussed — the project assumes Postgres from Phase 0 forward, likely because concurrent Celery workers and the API all need to write.

## Celery with Redis

Alerts need to be evaluated on a schedule. Data needs to be refreshed on a schedule. AI jobs need to run without blocking a request. That's a task queue.

Celery plus Redis was picked because:

- Celery Beat runs the alert condition evaluator at a configurable interval. Triggered alerts fan out to the Discord webhook service. This is the pattern in Phase 4 and it's been stable.
- Workers scale independently of the API. The roadmap explicitly calls this out: "Celery workers can scale independently."
- Redis is already in the stack as a cache (quotes, rate limiting, session data). Reusing it as the Celery broker means one fewer piece of infrastructure to run.

An in-process scheduler would have been simpler but would tie background work to the API process's lifecycle — a deploy of the API would interrupt a running AI job. Separation is worth the extra container.

Lighter task runners (RQ, Dramatiq, Arq) aren't mentioned in the source docs, so they aren't compared here.

## Docker Compose on a NAS

This is a single-developer, single-household deployment. Target: a Synology NAS. The requirement is "runs, restarts, backs up," not "survives a regional outage."

Docker Compose was picked because:

- The service graph (api, frontend, worker, beat, postgres, redis, traefik) fits in one `docker-compose.prod.yml`. All services come up with one command.
- Traefik handles TLS via Let's Encrypt and path-based routing in front of the two app processes. No manual certificate work.
- The init container runs Alembic migrations before the API starts, which means schema changes deploy atomically with the image.
- pg_dump-based backup and restore scripts live alongside Compose. The production hardening pass (Phase 6.6) locked down secrets, added login rate limiting, and added security headers — all within the Compose-based deployment model.

Kubernetes would be overkill for one machine in a home rack. Bare-metal systemd units would work but would mean hand-managing process supervision, log rotation, and dependency ordering that Compose already handles.

The NAS itself was chosen because it's already running, already on a UPS, and already backed up. The tradeoff is limited horizontal scaling — but that's not a real constraint for a single-user app.
