---
title: Architecture overview
description: How the services fit together, what each one does, and why the system is split the way it is.
---

Investing Companion is a dual-stack application: a Python/FastAPI backend handles data ingestion, analysis, and scheduling; a Next.js frontend provides the interactive dashboard. Six services run under Docker Compose and talk to each other over an internal network, with a reverse proxy in front.

## System diagram

```text
                    +-----------+
                    |  Browser  |
                    +-----+-----+
                          |
                    +-----+-----+
                    |   Caddy   |  (reverse proxy)
                    +--+-----+--+
                       |     |
              +--------+     +--------+
              |                       |
        +-----+------+         +------+-----+
        | Next.js 16 |         |  FastAPI   |
        |  :3000     |         |  :8000     |
        +-----+------+         +--+--+--+---+
              |                    |  |  |
              +--------+-----------+  |  |
                       |              |  |
                 +-----+------+       |  |
                 | PostgreSQL |       |  |
                 | TimescaleDB|   +---+  +---+
                 +------------+   |          |
                              +---+--+  +----+----+
                              | Redis|  | Celery  |
                              +------+  +---------+
```

The frontend never calls external data providers directly. All external data goes through the backend, which normalizes it and writes it to the database. The frontend reads from the API only.

## Services

**FastAPI backend** (`backend/app/main.py`, port 8000) is the core of the system. It mounts routers for auth, equity, watchlists, trades, events, market data, news, ratios, AI analysis, alerts, and settings — all under `/api/v1/`. It also exposes a `/health` endpoint with an optional `?detailed=true` flag that pings the database, Redis, and Celery workers. In production, the interactive docs at `/docs` and `/redoc` are disabled.

**Next.js frontend** (port 3000) is a TypeScript app using the App Router. It renders the dashboard, equity detail pages, watchlists, the ratio comparator, the alert manager, and the trade tracker. Charts use TradingView Lightweight Charts. Client state lives in Zustand; server state is managed by TanStack Query. The frontend has no direct database connection — it is a pure API consumer.

**PostgreSQL + TimescaleDB** is the primary data store. TimescaleDB's hypertable extension handles the price history and indicator time-series columns efficiently. SQLAlchemy 2.0 (async) is the ORM; Alembic manages schema migrations.

**Redis** plays two roles: task broker for Celery and a cache layer for quote data, rate limiting, and session state. Because Redis sits between the API and both the worker queue and the external providers, it keeps repeated quote requests from hammering the rate-limited free-tier APIs.

**Celery worker** runs the actual background jobs: fetching prices and fundamentals from Yahoo Finance and Alpha Vantage, checking active alert conditions, and running AI analysis tasks queued by the API. Workers can be scaled horizontally by adding containers without touching the rest of the stack.

**Celery beat** is the scheduler. It triggers periodic tasks on a configurable schedule — data refreshes, alert scans, daily summaries — and pushes them onto the Redis broker queue for workers to consume. Beat and worker run in separate containers.

## Why the split

A monolith (Next.js API routes talking directly to the database) would have worked for basic CRUD, but this system has requirements that push against it.

The background work — scheduled data fetches, multi-step alert evaluation, AI analysis that may take several seconds — needs a proper task queue with retries, concurrency, and a separate process lifecycle. Celery is a natural fit for Python, and once you have a Python worker process, you want a Python API process next to it sharing models and services. Writing the data layer twice (once in Python for Celery, once in TypeScript for API routes) would be worse than the split.

The frontend benefits from being a dedicated Next.js app. TradingView Lightweight Charts is a JavaScript library. TanStack Query handles cache invalidation and background refetching in ways that suit a dashboard that updates frequently. Keeping the frontend as a standalone app also means it can be replaced or reskinned without touching the data layer.

## What gets stored where

| Data | Store | Why |
| --- | --- | --- |
| User accounts, watchlists, alerts config, trades | PostgreSQL | Relational, low write volume |
| Price history, indicators, snapshots | TimescaleDB hypertables | Time-series compression and fast range queries |
| Quote cache, rate-limit counters, session data | Redis | TTL-based, does not need durability |
| Celery task queue | Redis | Low-latency broker, tasks are ephemeral |

## Going deeper

For how data moves through the system end-to-end, see [Data flow](/architecture/data-flow/).

For the full domain model — Equity, Watchlist, Ratio, Alert — see [Domain model](/architecture/domain-model/).
