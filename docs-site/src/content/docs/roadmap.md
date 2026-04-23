---
title: Roadmap and status
description: Phase history, current project status, and known gaps — a summary of what's shipped and what's not.
---

Investing Companion has completed all planned development phases through Phase 6.6. Every core feature — equity data, watchlists, fundamental analysis, trade tracking, alerts, an AI panel, a calendar, and production deployment — is shipped and running. This page summarizes where the project stands. The full per-phase deliverable checklist, including unchecked stretch items, lives in [`docs/ROADMAP.md`](https://github.com/smithadifd/investing_companion/blob/main/docs/ROADMAP.md) in the repo.

## Phase history

| Phase | Name | Status | Outcome |
| --- | --- | --- | --- |
| 0 | Foundation | Complete | Docker Compose running, database connected, health endpoint live |
| 1 | Prototype | Complete | Equity search, live quotes, TradingView price charts |
| 2 | MVP | Complete | Watchlists, technical indicators, fundamental analysis, CSV import/export |
| 3 | Intelligence | Complete | AI analysis panel, ratio comparator, market overview with sector heatmaps |
| 4 | Alerts | Complete | Price and ratio alerts, Discord notifications, Celery Beat schedule |
| 5 | Polish | Complete | Authentication, user settings with encrypted API keys, session management |
| 6 | Trade tracker | Complete | Trade entry, FIFO P&L matching, performance analytics, position sizer |
| 6.5 | Calendar & events | Complete | Earnings calendar, macro economic events, watchlist calendar integration |
| 6.6 | Deployment readiness | Complete | Security hardening, production Docker Compose, Synology deploy |
| 7 | Advanced AI | Future | See below |

## What's shipped

The application has ten feature areas in production:

- **Equity dashboard** — search, quote, and chart any publicly traded stock. See [equity dashboard](/features/equity-dashboard/).
- **Watchlists** — named lists with per-item notes, target prices, and thesis tracking. See [watchlists](/features/watchlists/).
- **Fundamental analysis** — P/E, forward P/E, EPS, beta, dividend yield, market cap, and cross-equity peer comparison.
- **Market overview** — index tracking, sector heatmaps, daily movers, currencies, and commodities.
- **AI analysis** — Claude-powered equity analysis with live market data injected into the prompt. See [AI analysis](/features/ai-analysis/).
- **Price alerts** — configurable conditions (above, below, crosses, percent change) with Discord delivery. See [alerts](/features/alerts/).
- **Trade tracker** — log trades, compute FIFO realized P&L, view open positions, and size new trades by account risk. See [trade tracker](/features/trade-tracker/).
- **Calendar and events** — earnings dates, ex-dividend dates, and macro events (FOMC, CPI, NFP, GDP). See [calendar](/features/calendar/).
- **Scheduled tasks** — Celery Beat handles data refreshes, alert checks, and daily Discord market pulse and end-of-day wrap summaries.
- **Authentication** — single-user credentials-based login with Argon2id password hashing, JWT access tokens, and encrypted settings storage.

## Known gaps and open work

A few things are incomplete or not wired up yet.

**Percent-change alerts don't fire.** The `percent_up` and `percent_down` alert conditions look up historical prices in the `price_history` hypertable, but no scheduled task or API endpoint currently writes to that table. Alerts configured with these conditions will silently not trigger. The full details are on the [alerts page](/features/alerts/).

**FIFO matching has known edge cases.** Realized P&L on trade pairs excludes fees (`fees` is stored on the `Trade` row but not subtracted from `realized_pnl`). If a sell order exceeds open long inventory, the excess quantity is dropped silently — it does not open a short. Neither the FIFO algorithm nor the overall trade service has a test file yet. See [FIFO trade matching](/design-decisions/fifo-matching/) for the edge case inventory.

**Alpha Vantage and Polygon are not wired.** Both API keys have env-var placeholders in `.env.example` and are mentioned in the roadmap as upgrade paths, but no provider client exists for either in `backend/app/services/data_providers/`. The app runs entirely on Yahoo Finance (quotes, fundamentals, earnings) and Finnhub (news) today. See [data source strategy](/design-decisions/data-sources/).

**AI analysis only runs on the equity detail page.** The backend defines four `AnalysisType` values — `equity`, `ratio`, `watchlist`, and `general` — but only the `equity` path has a frontend UI. The other three types are reachable via the API but nothing renders their output yet. See [AI analysis](/features/ai-analysis/).

**Chart event markers are a stretch item.** Phase 6.5 listed earnings and event markers overlaid on the price chart as a stretch goal. They are not implemented.

## Phase 7: advanced AI automation

Phase 7 is a set of features that make the AI analysis more automatic: scheduled portfolio reviews, alert-triggered commentary, trade journal prompts, SEC filing analysis, and deeper Claude integrations including an MCP server so Claude Code can query your portfolio directly.

The blocker is access model, not engineering. Anthropic's API does not currently support OAuth tokens for third-party integrations, which means Phase 7 requires either a user-supplied Anthropic API key (already supported) or a proxy layer. The details are in [`docs/issues/001-claude-oauth-support.md`](https://github.com/smithadifd/investing_companion/blob/main/docs/issues/001-claude-oauth-support.md) in the repo.

## Deployment

The application runs in production on a Synology NAS via Docker Compose, and is also available at the public demo site [invest.smithadifd.com](https://invest.smithadifd.com). Two compose files cover the deployment options: `docker-compose.prod.yml` ships Traefik and Let's Encrypt as a self-contained stack, while `docker-compose.local.yml` omits the built-in proxy for anyone already fronting the app with Caddy, Nginx, or similar. The demo resets weekly and blocks write operations. For self-hosting instructions, see [running on Synology](/running/synology/).
