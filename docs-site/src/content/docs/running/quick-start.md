---
title: Quick start (Docker)
description: Get Investing Companion running locally with Docker Compose in a few minutes.
---

This page covers the shortest path from a fresh clone to a working local instance. All services — API, frontend, database, cache, and background workers — run in Docker, so you don't need Python or Node installed on your machine.

## Prerequisites

- **Docker Engine 20.10+** and **Docker Compose v2.0+** (`docker compose`, not `docker-compose`)
- ~10 GB free disk space for images and database growth

## 1. Clone and configure

```bash
git clone https://github.com/smithadifd/investing_companion.git
cd investing_companion
cp .env.example .env
```

Open `.env` and set the two values you must change before the app will start properly:

```env
SECRET_KEY=your-secret-key-here
POSTGRES_PASSWORD=your-secure-password-here
```

Generate a suitable `SECRET_KEY` with:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

Everything else has a working default for local development. The external API keys (`ALPHA_VANTAGE_API_KEY`, `FINNHUB_API_KEY`, `DISCORD_WEBHOOK_URL`, `CLAUDE_API_KEY`) are all optional — leave them blank to start and add them later.

## 2. Start the services

```bash
docker compose up -d
```

This starts six services: `db` (PostgreSQL + TimescaleDB), `redis`, `api` (FastAPI), `celery_worker`, `celery_beat`, and `frontend` (Next.js). The `db` and `redis` healthchecks must pass before the API and workers come up, so the first start takes about 30 seconds.

## 3. Run migrations

```bash
docker compose exec api alembic upgrade head
```

The database is empty until you run this. It applies all schema migrations via Alembic against the running `db` container.

## 4. Seed reference data

```bash
docker exec investing_api python -m scripts.seed_demo_data
```

This populates default financial ratio definitions and the macro economic events calendar (FOMC, CPI, NFP, GDP dates). The app works without it, but the calendar and ratio comparison views will be empty.

## 5. Create your account

Navigate to `http://localhost:3000`. Registration is enabled by default — create an account on the login page and you're in.

The API docs are at `http://localhost:8000/docs` if you want to explore the backend directly.

## What's next

- **Configure data sources and alerts** — see [Configuration](/running/configuration/) for the full environment variable reference, including how to add your Alpha Vantage key and Discord webhook.
- **Explore the features** — the [Equity dashboard](/features/equity-dashboard/) walkthrough covers search, charting, and watchlists.
