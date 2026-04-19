---
title: Trade tracker
description: Log buy, sell, short, and cover trades, get realized P&L via automatic FIFO matching, and view open positions alongside a position sizing calculator.
---

The trade tracker is the transaction layer of Investing Companion. You log individual trades — buys, sells, shorts, and covers — and the system keeps the rest consistent: open positions are recalculated from raw trade data, and realized P&L is derived via FIFO matching every time you create, edit, or delete a trade. Nothing drifts. If you change an execution price from three months ago, the downstream pair history updates immediately.

Trades can optionally link back to a watchlist item via `watchlist_item_id`, so you can trace a position back to the thesis that prompted it. See [Watchlists](/features/watchlists/) for how that link works.

For the underlying data model, see [Domain model](/architecture/domain-model/) — specifically the `trades` and `trade_pairs` tables.

## Entering a trade

The `CreateTradeModal` component handles trade entry. Open it from the "Log Trade" button at the top right of `/trades`. The form has these fields:

- **Trade type** — one of `buy`, `sell`, `short`, or `cover`, selected via a four-button toggle. Buy and cover render green; sell and short render red.
- **Symbol** — an `EquitySearchInput` that resolves against existing equities or creates a new one on the backend if the symbol is not yet in the database.
- **Quantity** — number of shares or units (fractional values are accepted).
- **Price per share** — execution price.
- **Fees/Commission** — optional, defaults to 0. Included in `total_cost` but not `total_value`.
- **Executed at** — datetime-local input, pre-filled to now.
- **Notes** — optional free text, up to 5,000 characters.

The form shows a running total (trade value + fees) once quantity and price are both filled.

On submit, `CreateTradeModal` sends `POST /api/v1/trades` with a `TradeCreate` body. You can supply either `equity_id` (for an equity already in the database) or `symbol` (the backend resolves or creates it). Both are optional in the schema, but the endpoint returns 400 if neither is provided.

`EditTradeModal` uses the same fields. The symbol is shown as read-only text — you cannot change the equity on an existing trade.

## What happens after submit

`TradeService.create_trade` inserts the `trades` row, commits, then immediately calls `_recalculate_pairs(user_id, equity_id)` before returning. The same recalculation runs after `update_trade` and `delete_trade`. It is synchronous within the request: the response you get back already reflects the updated pair state.

`_recalculate_pairs` deletes all existing `trade_pairs` rows for that user/equity combination and rebuilds them from scratch by replaying the full trade history in chronological order. A FIFO queue tracks open long lots (for buy/sell) and a separate queue tracks open short lots (for short/cover). Each time a closing trade is processed, it drains the queue from the front and emits one `TradePair` row per matched lot.

The full algorithm is described in [FIFO matching](/design-decisions/fifo-matching/).

## Viewing positions

The Positions tab (backed by `GET /api/v1/trades/portfolio`) shows all equities where you have an active position. Each `PositionCard` displays:

- **Quantity** — net shares held (negative for a net short position)
- **Avg cost basis** — `avg_cost_basis` from `PositionSummary`
- **Cost basis total** — `total_cost`
- **Current value** — fetched live via `EquityService.get_quote`; absent if no quote is available
- **Unrealized P&L** — and unrealized P&L percent, when current price is available
- **Realized P&L** — sum of `realized_pnl` across all matched pairs for that equity

You can also look up a single equity's position via `GET /api/v1/trades/positions/{equity_id}`, which returns a `PositionSummary` or 404 if no trades exist for that equity.

Each position card has "Buy More" and "Sell" quick-action buttons that open `QuickTradeModal` pre-filled with the symbol, type, and current price.

## Viewing matched pairs

`GET /api/v1/trades/pairs` returns all `TradePair` records for the authenticated user, optionally filtered by `equity_id`. The trade pairs list is read-only — you cannot create or edit pairs directly; they are always a derived view of your trade log.

Each `TradePairResponse` includes:

| Field | Description |
| --- | --- |
| `open_trade_id` | The opening trade (buy or short) |
| `close_trade_id` | The closing trade (sell or cover) |
| `quantity_matched` | Shares matched in this pairing |
| `realized_pnl` | Profit or loss for this lot |
| `holding_period_days` | Calendar days between open and close execution timestamps |
| `calculated_at` | When this pair row was written |

The pairs tab is not exposed as a separate tab in the current `/trades` UI — pairs are accessible via the API but not yet rendered in the front end. The performance tab (described below) aggregates pair data into win rate, profit factor, and streak metrics.

## Performance

The Performance tab calls `GET /api/v1/trades/performance` and renders `PerformanceMetricsDisplay`. The metrics come from `PerformanceMetrics`:

- Win rate, total realized P&L, profit factor
- Average win, average loss, largest win, largest loss
- Current streak (positive = winning, negative = losing), longest winning and losing streaks
- Average holding period in days

The `GET /api/v1/trades/performance` endpoint accepts optional `start_date` and `end_date` query params to scope the calculation to a date range.

## Position sizing calculator

The Position Sizer tab renders the `PositionSizer` component, which calls `POST /api/v1/trades/position-size`. The formula is the fixed-risk method:

```text
shares = floor((account_size * risk_percent / 100) / abs(entry_price - stop_loss))
```

Inputs: account size, risk percent (defaults to 2 in the UI), entry price, stop loss. The backend returns suggested share count, total position value, dollar amount at risk, and risk per share. If the resulting position value exceeds 25% of account size, the response includes a warning in the `notes` field.

## Editing and deleting trades

`PUT /api/v1/trades/{trade_id}` accepts a `TradeUpdate` body — all fields are optional, so you can patch just the price without resending everything. `DELETE /api/v1/trades/{trade_id}` removes the row. Both endpoints trigger `_recalculate_pairs` before responding, so the pair history is always consistent with the current trade set.

Both mutation endpoints are blocked in demo mode.
