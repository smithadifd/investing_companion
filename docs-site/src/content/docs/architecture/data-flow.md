---
title: Data flow
description: How quotes, history, AI analysis, and alerts move through the system end-to-end.
---

This page traces four concrete paths through the system: a live quote request, a historical price pull, an AI analysis request, and alert evaluation. For the service-level view — what each process is and how they're wired together — see [Architecture overview](/architecture/overview/).

---

## Flow 1: Live quote request

When the frontend requests a quote for a ticker, the request hits the FastAPI backend and goes through `EquityService.get_quote()` in `backend/app/services/equity.py`.

```text
1. GET /api/v1/equities/{symbol}/quote arrives at the equity endpoint
2. EquityService.get_quote(symbol) is called
3. cache_service.quote_key(symbol) produces the key "quote:{SYMBOL}" (uppercased)
4. cache_service.get(key) checks Redis
   - Hit: deserialize the cached JSON, return QuoteResponse immediately
   - Miss: continue
5. YahooFinanceProvider.get_quote(symbol) fetches live data via yfinance
   (runs in a thread pool executor — yfinance is synchronous)
6. cache_service.set(key, quote.model_dump(), settings.QUOTE_CACHE_TTL) writes to Redis
7. QuoteResponse is returned to the caller
```

`CacheService` is in `backend/app/services/cache.py`. The default TTL for `CacheService.set()` is 900 seconds (15 minutes), but `EquityService` passes `settings.QUOTE_CACHE_TTL` explicitly. The Yahoo provider sets `QUOTE_CACHE_TTL = 300` (5 minutes) at the top of `backend/app/services/data_providers/yahoo.py`. Redis failures are caught and swallowed in both directions, so the app keeps working without a cache.

The same cache-check pattern applies to `get_fundamentals()` (key: `fundamentals:{SYMBOL}`, TTL: 3600 s) and `get_history()` (key: `history:{SYMBOL}:{period}:{interval}`, TTL: 900 s).

---

## Flow 2: Historical price pull

Historical OHLCV data travels two distinct paths depending on who's asking.

**On-demand (frontend):** `GET /api/v1/equities/{symbol}/history` calls `EquityService.get_history(symbol, period, interval)`. This follows the same cache-first pattern as quotes. On a miss, `YahooFinanceProvider.get_history()` fetches the data via yfinance, the result is wrapped in a `HistoryResponse`, cached in Redis, and returned. The data never touches the database in this path.

**Persisted history (alert evaluation):** The `price_history` table — a TimescaleDB hypertable defined in `backend/app/db/models/price_history.py` with a composite primary key of `(equity_id, timestamp)` — stores OHLCV rows for use by the alert evaluator. `AlertService._get_historical_reference_value()` queries this table when evaluating `percent_up` / `percent_down` alert conditions. It uses `_get_closest_close()`, which searches within a ±3-day window around the target time to handle weekends and holidays.

At the time of writing, there is no scheduled Celery task that writes to `price_history`. The table is populated through other means not evidenced in the current task files — see Gaps below.

---

## Flow 3: AI analysis request

The streaming path is the one the UI uses. The non-streaming `POST /api/v1/ai/analyze` endpoint exists for programmatic access.

```text
1. Frontend posts to POST /api/v1/ai/analyze/stream
2. The analyze_stream endpoint in backend/app/api/v1/endpoints/ai.py
   returns a StreamingResponse with media_type "text/event-stream"
3. AIService.analyze_stream(request) is called
4. If request.analysis_type == EQUITY and request.include_context is true:
   a. AIService._get_equity_context(symbol) calls EquityService.get_equity_detail()
      which fetches quote + fundamentals (cache-first, as above)
   b. AIService._build_equity_prompt() assembles the full prompt:
      current price, day change, 52-week range, market cap, P/E, forward P/E,
      EPS (TTM), beta, dividend yield, sector, industry
5. For RATIO analysis: _get_ratio_context(ratio_id) fetches 1-month ratio history
   via RatioService; _build_ratio_prompt() assembles that context
6. AIService._build_system_prompt() produces the system message
   (appends custom_instructions from the user_settings table if set)
7. anthropic.Anthropic.messages.stream() is called with the assembled prompt
8. Each text chunk is yielded as "data: {chunk}\n\n" (SSE format)
9. Stream ends with "data: [DONE]\n\n"
```

The Claude API key is read first from the `user_settings` table (key: `claude_api_key`), falling back to the `CLAUDE_API_KEY` environment variable. The model is read from `user_settings` key `ai_default_model`, defaulting to `AIModel.CLAUDE_SONNET`.

---

## Flow 4: Alert evaluation

Alerts run on a tight Celery Beat loop. The schedule is defined in `backend/app/tasks/celery_app.py`.

```text
1. Celery Beat fires "alerts.check_all_alerts" every 300 seconds (5 minutes)
2. check_all_alerts() in backend/app/tasks/alerts.py opens an AsyncSession
   and calls AlertService.check_all_active_alerts()
3. check_all_active_alerts() queries all Alert rows where is_active = true
4. For each alert, AlertService.process_alert(alert) runs:
   a. check_alert(alert) fetches the current value:
      - Equity alerts: YahooFinanceProvider.get_quote() (live, bypasses Redis cache)
      - Ratio alerts: two concurrent get_quote() calls, price divided
   b. _evaluate_condition() compares current value against threshold_value
      using the alert's condition_type ("above", "below", "crosses_above",
      "crosses_below", "percent_up", "percent_down")
      Intraday high/low from the quote are used for crossing alerts to catch
      threshold breaches that occur between polls
   c. _check_cooldown(alert) compares now() against
      last_triggered_at + timedelta(minutes=cooldown_minutes)
      If still in cooldown, should_notify = false and no webhook fires
5. If triggered and past cooldown:
   a. An AlertHistory row is written with triggered_value and threshold_value
   b. alert.last_triggered_at is updated
   c. discord_service.send_alert_notification() posts to the Discord webhook
   d. history.notification_sent is set to true on success
6. Results are summarized: checked / triggered / errors counts logged
```

Cooldown is per-alert and stored on the `Alert` row itself (`cooldown_minutes`, `last_triggered_at`). There is no global cooldown — each alert ages out independently.

The `check_all_alerts` task is registered as Celery task name `"alerts.check_all_alerts"`. A separate `check_single_alert(alert_id)` task (name: `"alerts.check_single_alert"`) exists for on-demand testing of individual alerts.
