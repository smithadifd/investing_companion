---
title: Data source strategy
description: Why Yahoo Finance is the primary quote source, where Finnhub fits for news, and what Alpha Vantage and Polygon are reserved for.
---

Investing Companion pulls market data from multiple providers, each chosen for a specific job. Two are wired into the backend today: Yahoo Finance for quotes, history, fundamentals, and earnings calendars, and Finnhub for news. Alpha Vantage and Polygon have env-var placeholders but no provider client yet — they live in the roadmap, not in `backend/app/services/data_providers/`.

This page records why the current choices were made, what to watch out for, and how a future provider would slot in.

## Yahoo Finance (implemented)

Yahoo is the starting point because it is free, has no registration, and covers the bulk of what a prototype needs in one client. The `YahooFinanceProvider` class in `backend/app/services/data_providers/yahoo.py` wraps the `yfinance` library and exposes quotes, historical OHLCV, fundamentals, a lightweight symbol search, and earnings/dividend calendar data. That single provider carries Phase 1 (equity dashboard), most of Phase 2 (fundamentals and indicators computed from history), and the earnings side of Phase 6.5 (calendar).

The risk is that `yfinance` talks to an unofficial endpoint. Yahoo can change its response shape, throttle aggressively, or block scraping entirely, and there is no SLA behind any of it. The mitigation is the cache-first read path described in [Cache-first data flow](/design-decisions/cache-first/): the UI reads from Postgres and Redis, never directly from Yahoo. When a quote is requested, `get_quote` checks `cache_service` first and only falls through to `yfinance` on a miss. Quotes are cached for 5 minutes, fundamentals for 1 hour, and history for 15 minutes (see `QUOTE_CACHE_TTL`, `FUNDAMENTALS_CACHE_TTL`, and `HISTORY_CACHE_TTL` in `yahoo.py`). A short Yahoo outage is invisible to the user.

Two other practical notes. Calls into `yfinance` are synchronous, so they run on a bounded `ThreadPoolExecutor` with `max_workers=4` to avoid swamping Yahoo. The executor is shut down on process exit via `atexit.register`. And `yfinance` has no real search endpoint — `search()` does a direct ticker lookup of the query string. The docstring in the file calls out Alpha Vantage `SYMBOL_SEARCH` as the intended replacement.

## Finnhub (implemented)

Finnhub is the news provider. `FinnhubNewsProvider` in `backend/app/services/data_providers/finnhub.py` is a thin `httpx` client around two endpoints — `/company-news` for per-symbol news and `/news` for general market news by category (general, forex, crypto, merger). The free tier allows 60 requests per minute, which is enough for the current refresh cadence.

Finnhub was picked over layering news on top of Yahoo because it has an official free tier, a documented contract, and a clean per-symbol endpoint. The client checks `settings.FINNHUB_API_KEY` on each call and returns an empty list if the key is not configured, so the app works without it — news just disappears from the UI. Errors are logged and swallowed; news is treated as best-effort enrichment, not a hard dependency.

## Alpha Vantage (env-configured, not yet wired)

`ALPHA_VANTAGE_API_KEY` is declared in `.env.example` with a link to the free-tier signup, but there is no `alpha_vantage.py` in `data_providers/` and nothing is exported from the package `__init__.py`. The roadmap (`docs/ROADMAP.md`, Phases 2 and 3) lists Alpha Vantage as optional for additional indicators, forex, and economic data, and the `yahoo.py` search method explicitly points at Alpha Vantage `SYMBOL_SEARCH` as the eventual upgrade for search quality. Treat this as scaffolded intent, not a live integration.

## Polygon (env-configured, not yet wired)

`POLYGON_API_KEY` is also in `.env.example`, labeled as optional and paid. The roadmap's "Data Source Strategy" note positions Polygon.io Starter ($29/mo) as the upgrade path once the free tier stops being enough — real-time quotes and more history. Like Alpha Vantage, there is no provider client today and nothing upstream of `data_providers/` references it.

## The normalization layer

Everything upstream of `data_providers/` is meant to be provider-agnostic. The equity service, price history tasks, and calendar aggregator consume typed Pydantic schemas — `QuoteResponse`, `OHLCVData`, `FundamentalsResponse`, `EquityCalendarInfo`, `EquitySearchResult` — and do not know or care which client produced them. Today `YahooFinanceProvider` is the only implementation of this de facto interface, so the contract is implicit rather than enforced by a `Protocol` or ABC.

The roadmap mentions fallback logic ("if one provider fails, try another") as a goal. That is not in the code yet. Adding it cleanly will likely mean formalizing the provider interface once a second quote source lands.

## Adding a new provider

If you are adding Alpha Vantage, Polygon, or something else, the shape to follow is visible in the two existing clients:

1. Create `backend/app/services/data_providers/<name>.py` with a provider class.
2. Read the API key from `app.core.config.settings` and expose an `is_configured` check. Degrade to empty results, not exceptions, when the key is missing — match the Finnhub pattern.
3. Return the existing Pydantic schemas from `app.schemas.equity` and `app.schemas.economic_event` rather than inventing new shapes. That keeps callers unchanged.
4. If the underlying library is synchronous (as `yfinance` is), run it through a thread pool; if it is HTTP-based, use `httpx.AsyncClient` with a timeout, as `finnhub.py` does.
5. Export the class from `backend/app/services/data_providers/__init__.py`.
6. Add any new env vars to `.env.example` and document them in [Configuration](/running/configuration/).

Cache TTLs belong next to the provider that sets them. The goal is that a call into the service layer looks the same whether Yahoo, Alpha Vantage, or Polygon answers it.
