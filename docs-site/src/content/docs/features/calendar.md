---
title: Calendar and events
description: How equity-specific and macro economic events are stored, synced, and displayed on the unified calendar view.
---

The calendar tracks two distinct kinds of events in one place. Equity-specific events — earnings releases, ex-dividend dates, dividend payment dates, and stock splits — are tied to a particular ticker and sourced from Yahoo Finance. Macro events — FOMC meetings, CPI, PPI, NFP, GDP, PCE, retail sales, unemployment, ISM manufacturing, ISM services, housing starts, and consumer confidence releases — are not tied to any ticker and are seeded or entered manually. Both live in the same `economic_events` table and surface on the same calendar view.

## Event types

The `EventType` enum defines every supported value:

**Equity events** (have an `equity_id`):

- `earnings`
- `ex_dividend`
- `dividend_pay`
- `stock_split`

**Macro events** (`equity_id` is `null`):

- `fomc`, `cpi`, `ppi`, `nfp`, `gdp`, `pce`
- `retail_sales`, `unemployment`
- `ism_manufacturing`, `ism_services`
- `housing_starts`, `consumer_confidence`

**User-defined**:

- `custom`
- `ipo`

Each event also carries an `importance` field with three levels: `low`, `medium`, and `high`.

## Where data comes from

Equity events are fetched from Yahoo Finance via `EconomicEventService.refresh_equity_events()`. The service populates `earnings` dates (with `BMO`/`AMC` timing where available), `ex_dividend` dates, and `dividend_pay` dates for a given symbol. Stock splits come through the same path when present.

Macro events are seeded — they enter the database with `source = "seed"` rather than being fetched on a schedule. If you need to add an upcoming FOMC or CPI date that isn't in the seed data, you can do it via the custom event endpoint (see [Custom events](#custom-events) below), or by inserting directly and setting `source = "seed"` and a `recurrence_key`.

## Sync schedule

Equity event data is refreshed by the Celery Beat task `refresh-watchlist-events-daily`. It runs at 22:00 UTC (after US market close) and calls `events.refresh_all_watchlist_events`. The task queries all `WatchlistItem` rows where `track_calendar = true`, collects the distinct equity symbols, and calls `refresh_equity_events` for each with a 1.5-second delay between requests to avoid Yahoo rate limits.

You can also trigger a sync manually for a single ticker:

```http
POST /api/v1/events/refresh/{symbol}
```

Or for all equities across a user's watchlist(s):

```http
POST /api/v1/events/refresh/watchlist
```

## Deduplication

Two constraints prevent duplicate imports. For equity events, a `UniqueConstraint` on `(equity_id, event_type, event_date)` — named `uq_equity_event_date` — blocks inserting the same event type for the same ticker on the same date twice. For macro events, a partial unique index on `recurrence_key` (where `recurrence_key IS NOT NULL`) prevents duplicate seeded entries. The key follows a pattern like `fomc_2026_01` or `earnings_AAPL_2025Q1`. When the sync task upserts an event it either matches on this key or falls back to the equity/type/date constraint.

## Calendar UI

The main calendar endpoint returns events grouped by day:

```http
GET /api/v1/events/calendar/{year}/{month}
```

Each day in the response includes `has_earnings`, `has_macro`, and `event_count` flags so the UI can render summary indicators without reading every event detail upfront.

The list endpoint at `GET /api/v1/events` supports several filters:

- `event_types` — one or more `EventType` values
- `importance` — `low`, `medium`, or `high`
- `watchlist_only=true` — restricts results to equities tracked by the authenticated user
- `watchlist_id` — narrows to a specific watchlist
- `equity_symbol` — single ticker
- `start_date` / `end_date` — date range

For a quick forward-looking view (dashboard widgets, notification summaries), use:

```http
GET /api/v1/events/upcoming?days=7
```

`days` accepts 1–90. The default is 7.

Clicking any event on the calendar opens `EventDetailModal`, which shows date, time (if not all-day), importance badge, description, and — for macro events that have been updated with results — a three-column grid of `previous`, `forecast`, and `actual` values. System events (those with `source = "yahoo"` or `source = "seed"`) cannot be edited. The modal offers an "Untrack" action for equity events, which calls `DELETE /api/v1/events/equity/{symbol}` and removes all auto-fetched events for that ticker.

## Watchlist integration

Whether a ticker's events appear on the calendar depends on `track_calendar` on the `WatchlistItem` row. If a user has a ticker on their watchlist but `track_calendar` is `false`, the daily sync task skips it and `watchlist_only=true` on the list endpoint will exclude it. See [Watchlists](/features/watchlists/) for how to enable calendar tracking per item.

## Custom events

Authenticated users can create personal calendar entries via:

```http
POST /api/v1/events
```

The request body takes `event_type`, `event_date`, `title`, `importance`, and optionally `description`, `event_time`, `all_day`, and `equity_symbol` (to link the event to a specific ticker). Custom events are created with `source = "manual"` and the `user_id` of the authenticated user. Only events owned by the requesting user can be updated (`PUT /api/v1/events/{event_id}`) or deleted (`DELETE /api/v1/events/{event_id}`). The `CreateEventModal` component in the frontend wraps this endpoint.

Demo mode blocks all mutation endpoints including event creation, update, and delete.
