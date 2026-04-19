---
title: Investing Companion
description: Self-hosted platform for equity tracking, analysis, and alerts.
---

Investing Companion is a self-hosted dashboard for tracking stocks, running fundamental and technical analysis on them, and getting a Discord ping when something moves. It fills the gap between free tools that only quote a price and paid tools like Koyfin or TradingView that cost more than a hobbyist wants to spend.

Live demo: [invest.smithadifd.com](https://invest.smithadifd.com) (log in as `demo@example.com` / `demo1234!`). Source: [github.com/smithadifd/investing_companion](https://github.com/smithadifd/investing_companion).

## What it does

- **Equity dashboard** — search any publicly traded symbol, see a TradingView Lightweight Chart, fundamentals (P/E, market cap, dividend yield, beta, 52-week range), and a technical tab with RSI, MACD, SMA, EMA, and Bollinger Bands.
- **Watchlists** — group equities with notes, target prices, and a written thesis. Import and export as CSV or JSON.
- **Market overview & ratios** — indices (S&P 500, NASDAQ, Dow), sector heatmap, top gainers and losers, and a ratios page preloaded with Gold/Silver, SPY/QQQ, Copper/Gold, TLT/IEF, and others.
- **AI analysis** — bring your own Claude API key. The backend builds a prompt from the equity's fundamentals, price history, and your watchlist context, then streams the response back over SSE.
- **Alerts** — price above, below, crosses a moving average, percent change, or a ratio threshold. Celery Beat checks them on a schedule and posts to a Discord webhook with a per-alert cooldown.
- **Trade tracker** — log buys, sells, shorts, and covers. FIFO matching calculates realized P&L, and a separate view tracks unrealized P&L, win rate, profit factor, and best/worst trades. Includes a position sizer (fixed risk, Kelly, ATR-based).
- **Calendar** — earnings dates, ex-dividend dates, and macro events (FOMC, CPI, NFP, GDP). Filterable to only your watchlist.

## Who it's for

Built for a single user running it on their own hardware — a NAS, a home server, or any Docker host. It assumes you're comfortable editing a `.env` file, running `docker compose`, and applying Alembic migrations.

These docs cover architecture, features, deployment, and the reasoning behind the major design choices. They are not a user manual for the UI and not an exhaustive OpenAPI reference — the FastAPI backend serves its own interactive docs at `/docs` when you run it.

## Try it or run it

- [Live demo](https://invest.smithadifd.com) — read-only-ish. Seed data, weekly reset, write operations disabled.
- [Quick start (Docker)](/running/quick-start/) — clone, copy `.env.example`, `docker compose up -d`, run migrations.
- [Synology NAS deployment](/running/synology/) — the setup this project was built for.

## Read deeper

- [Architecture overview & stack](/architecture/overview/) — what runs where, and why.
- [Data flow](/architecture/data-flow/) — how quotes, history, AI analysis, and alerts move through the system.
- [Features](/features/equity-dashboard/) — one page per feature, with the relevant endpoints and models.
- [Design decisions](/design-decisions/stack/) — TimescaleDB, cache-first reads, FIFO trade matching, the AI integration shape.
- [Roadmap & status](/roadmap/) — what's done, what's next.

## What's in the repo

The project is a two-service app wrapped in Docker Compose. `backend/` is a FastAPI application with SQLAlchemy 2.0 models, Alembic migrations, and Celery tasks under `app/tasks/`. `frontend/` is a Next.js App Router app using Zustand for client state and TanStack Query for server state. Postgres 15 with the TimescaleDB extension stores price history as a hypertable; Redis handles the cache and acts as the Celery broker. Reverse-proxied by Caddy in the deployment setup.
