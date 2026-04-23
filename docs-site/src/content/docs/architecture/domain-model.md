---
title: Domain model
description: The core database entities, their columns, and how they relate to each other. Migrations live in backend/alembic/versions/.
---

This page covers the central tables you'll touch most when adding a field or building a new endpoint. For the TimescaleDB-specific details of `price_history`, see [/design-decisions/timescaledb/](/design-decisions/timescaledb/). Migration files are in `backend/alembic/versions/`.

---

## Equity

**Table:** `equities` — **Model:** `Equity`

The root entity. Every stock, ETF, index, or other security gets one row here. Watchlist items, trades, alerts, and price history all hang off it.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | integer PK | |
| `symbol` | varchar(20) | Unique. The canonical ticker, e.g. `AAPL`. |
| `name` | varchar(255) | Full company or fund name. |
| `asset_type` | varchar(20) | `stock`, `etf`, `crypto`, `forex`, `commodity`, or `index`. Defaults to `stock`. |
| `exchange` | varchar(50) | Optional. |
| `sector` / `industry` | varchar | Optional. Used for filtering and display. |
| `country` / `currency` | varchar | Default `US` / `USD`. |
| `is_active` | boolean | Soft-delete flag. Defaults to `true`. |

**Relationships out:** one optional `EquityFundamentals` (one-to-one, `equity_id`), many `PriceHistory` rows.

**EquityFundamentals** (`equity_fundamentals`) is a separate table joined 1:1 to `equities` via `equity_id`. It holds cached valuation, profitability, dividend, and trading statistics (P/E, EPS, beta, 52-week range, etc.) sourced from external APIs. Keeping fundamentals in their own table avoids widening the core `equities` row and makes cache invalidation straightforward.

---

## Watchlist and WatchlistItem

**Tables:** `watchlists`, `watchlist_items` — **Models:** `Watchlist`, `WatchlistItem`

A user can have many watchlists. Each watchlist has many items; each item points at one equity.

**`watchlists`**

| Column | Notes |
| --- | --- |
| `user_id` | FK → `users.id`, nullable (supports single-user mode without auth). |
| `name` | Required, varchar(100). |
| `is_default` | Boolean. At most one default watchlist per user. |
| `description` | Optional text. |

**`watchlist_items`**

| Column | Notes |
| --- | --- |
| `watchlist_id` | FK → `watchlists.id` (cascade delete). |
| `equity_id` | FK → `equities.id` (cascade delete). |
| `target_price` | Optional decimal(12,2). Personal price target. |
| `thesis` | Optional text. Investment rationale. |
| `notes` | Optional text. |
| `track_calendar` | Boolean, defaults to `true`. Controls whether economic events for this equity appear in the calendar. |

The pair `(watchlist_id, equity_id)` has a unique constraint — you can't add the same equity to the same watchlist twice.

---

## Trade and TradePair

**Tables:** `trades`, `trade_pairs` — **Models:** `Trade`, `TradePair`

**`trades`** records individual executions. Each row is a single buy, sell, short, or cover.

| Column | Notes |
| --- | --- |
| `user_id` | FK → `users.id` (required). |
| `equity_id` | FK → `equities.id` (required). |
| `trade_type` | Enum: `buy`, `sell`, `short`, `cover`. |
| `quantity` | decimal(18,8). |
| `price` | decimal(18,8). Execution price per share. |
| `fees` | decimal(12,2). Defaults to 0. |
| `executed_at` | Timestamptz. When the trade happened. |
| `watchlist_item_id` | Optional FK → `watchlist_items.id` (set null on delete). Links a trade back to the thesis that drove it. |

**`trade_pairs`** is a computed table that matches an opening trade with a closing trade for realized P&L, using FIFO matching. It is not written by the user directly.

| Column | Notes |
| --- | --- |
| `open_trade_id` | FK → `trades.id`. |
| `close_trade_id` | FK → `trades.id`. |
| `quantity_matched` | Portion of the open trade that this pair covers. |
| `realized_pnl` | decimal(18,2). Calculated at match time. |
| `holding_period_days` | Integer. Days between open and close. |

---

## Alert and AlertHistory

**Tables:** `alerts`, `alert_history` — **Models:** `Alert`, `AlertHistory`

An alert watches either an equity price or a ratio value and fires when a condition is met.

**`alerts`**

| Column | Notes |
| --- | --- |
| `user_id` | FK → `users.id`, nullable (single-user mode). |
| `equity_id` | FK → `equities.id`. Mutually exclusive with `ratio_id`. |
| `ratio_id` | FK → `ratios.id`. Mutually exclusive with `equity_id`. |
| `condition_type` | String (enum value): `above`, `below`, `crosses_above`, `crosses_below`, `percent_up`, `percent_down`. |
| `threshold_value` | numeric(18,6). The trigger level. |
| `comparison_period` | String, e.g. `"1d"`, `"1w"`. Used only for percent-change conditions. |
| `is_active` | Boolean. Inactive alerts are skipped by the checker. |
| `cooldown_minutes` | Integer, defaults to 60. Minimum gap between consecutive triggers. |
| `was_above_threshold` | Nullable boolean. Tracks prior state for crossing conditions. |

**`alert_history`** logs each trigger event. It records the actual value that fired the alert, the threshold at that moment, and whether the notification was delivered — including channel and any delivery error.

---

## Ratio

**Table:** `ratios` — **Model:** `Ratio`

A ratio compares two assets by dividing one price series by another. The table stores the symbol pair; the actual computed values are derived at query time from `price_history`.

| Column | Notes |
| --- | --- |
| `numerator_symbol` | varchar(20). Top of the ratio (e.g. `GLD`). |
| `denominator_symbol` | varchar(20). Bottom of the ratio (e.g. `SLV`). |
| `category` | `commodity`, `equity`, `macro`, `crypto`, or `custom`. |
| `is_system` | Boolean. Pre-seeded system ratios (Gold/Silver, SPY/QQQ, etc.). |
| `is_favorite` | Boolean. User-level pin. |

`Ratio` has no FK to `equities` — symbols are stored as strings, not joined. Alerts can target a ratio via `ratio_id` on the `alerts` table.

---

## EconomicEvent

**Table:** `economic_events` — **Model:** `EconomicEvent`

Covers both equity-specific events (earnings, dividends, splits) and macro releases (FOMC, CPI, NFP, GDP, PCE, and others). The `event_type` column holds one of the `EventType` enum values.

| Column | Notes |
| --- | --- |
| `id` | UUID PK. |
| `event_type` | String (enum value). Determines whether `equity_id` is expected. |
| `equity_id` | FK → `equities.id`, nullable. Set for earnings/dividend/split events; null for macro events. |
| `user_id` | FK → `users.id`, nullable. Set for user-created custom events. |
| `event_date` | Date. Indexed. |
| `importance` | `low`, `medium`, or `high`. |
| `actual_value` / `forecast_value` / `previous_value` | Nullable numerics for releases that publish a data point. |
| `recurrence_key` | Nullable string used as a unique key to prevent duplicate imports (e.g. `"fomc_2025_01"`). |

---

## Relationships summary

- `Equity` is the hub. `WatchlistItem`, `Trade`, `TradePair`, `Alert`, `EconomicEvent`, `EquityFundamentals`, and `PriceHistory` all FK into `equities`.
- A `User` has many `Watchlist`s. Each `Watchlist` has many `WatchlistItem`s, each pointing at one `Equity`.
- A `User` has many `Trade`s. `TradePair` links two `Trade` rows (open and close) and belongs to both the `User` and the `Equity`.
- A `Trade` can optionally reference the `WatchlistItem` that motivated it via `watchlist_item_id`.
- An `Alert` targets either one `Equity` or one `Ratio` — never both. `AlertHistory` rows belong to an `Alert` and record each trigger event.
- `Ratio` stores symbol pairs as strings; it does not FK into `equities`.
- `EconomicEvent` optionally references an `Equity` (for corporate events) or a `User` (for custom events); macro events have neither.

---

## Migrations

All schema changes go through Alembic. Migration files are in `backend/alembic/versions/` and follow the naming convention `YYYYMMDD_NNN_description.py`. To apply pending migrations:

```bash
alembic upgrade head
```

The `price_history` table is a TimescaleDB hypertable partitioned on `timestamp`. Its creation and compression policy are applied as part of the migration that creates it. For the reasoning behind that choice, see [/design-decisions/timescaledb/](/design-decisions/timescaledb/).
