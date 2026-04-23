---
title: FIFO trade matching
description: How the trade_pairs table is built from raw trades, with a worked example and the known edge cases.
---

FIFO (first-in-first-out) is the matching convention used to turn a stream of buy, sell, short, and cover trades into realized P&L pairs. It was chosen for three practical reasons: most retail brokers report cost basis on a FIFO basis by default, it matches the accounting convention most users already recognize from their 1099-Bs, and it is fully deterministic — the same input trades always produce the same pairs regardless of when matching runs.

For the underlying column definitions, see [/architecture/domain-model/](/architecture/domain-model/). The stack context is in [/design-decisions/stack/](/design-decisions/stack/).

## Data model recap

Two tables are involved.

`trades` is the source of truth. Every row is user-entered: a `trade_type` (`buy`, `sell`, `short`, or `cover`), a `quantity` stored as `Numeric(18, 8)`, a `price` stored as `Numeric(18, 8)`, `fees` as `Numeric(12, 2)`, an `executed_at` timestamp, and an optional `watchlist_item_id` linking back to a thesis.

`trade_pairs` is computed, never user-entered. Each row records one match between an `open_trade_id` and a `close_trade_id`, along with `quantity_matched` (`Numeric(18, 8)`), `realized_pnl` (`Numeric(18, 2)`), `holding_period_days` (integer), and a `calculated_at` timestamp. The pair table is rebuilt from scratch on every relevant mutation — there is no incremental update path.

## The algorithm

The matching function is `TradeService._recalculate_pairs(user_id, equity_id)` in `backend/app/services/trade.py`. For a single equity it does this:

1. Deletes every existing `TradePair` row for that `(user_id, equity_id)`.
2. Loads every `Trade` for that `(user_id, equity_id)`, ordered by `executed_at` ascending.
3. Walks the trades in order, maintaining two in-memory FIFO queues: `long_queue` for open buys, `short_queue` for open shorts. Each queue entry is a tuple of `(trade_id, remaining_quantity, price, executed_at)`.
4. On a `buy`, appends to `long_queue`. On a `short`, appends to `short_queue`.
5. On a `sell`, drains `long_queue` from the head until the sell is fully matched or the queue is empty. On a `cover`, does the same against `short_queue`.
6. For each match, writes a `TradePair` row and decrements the open lot.

Long realized P&L is `quantity_matched * (close_price - open_price)`. Short realized P&L is the asymmetric `quantity_matched * (open_price - close_price)` — profit accrues when the cover price is below the short price. `holding_period_days` is `(close.executed_at - open.executed_at).days` in both cases.

### Worked example

```text
Trades (for one equity, in executed_at order):
  T1  2026-01-05  BUY   10 @ $100
  T2  2026-01-20  BUY   10 @ $110
  T3  2026-02-10  SELL  15 @ $130

FIFO match:
  1. T3 pulls 10 from T1:
       pair(open=T1, close=T3)
       quantity_matched = 10
       realized_pnl     = 10 * (130 - 100) = 300.00
       holding_days     = 36
     T1 is fully consumed, popped from long_queue.
  2. T3 still has 5 to close, pulls 5 from T2:
       pair(open=T2, close=T3)
       quantity_matched = 5
       realized_pnl     = 5  * (130 - 110) = 100.00
       holding_days     = 21
     T2 has 5 shares remaining in long_queue.

Post-state:
  long_queue = [(T2, 5, $110, 2026-01-20)]
  trade_pairs has 2 rows, total realized = $400.00
```

## When matching runs

Matching runs synchronously inside the request that mutated the data. There is no Celery task, no cron, no explicit "recalculate" endpoint. The three call sites are all in `TradeService`:

- `create_trade` calls `_recalculate_pairs(user_id, equity.id)` after committing the new trade.
- `update_trade` calls it after committing the updated trade, against the trade's current `equity_id`.
- `delete_trade` captures `equity_id` before deletion and calls it after the row is gone.

This means a mutation on one equity never touches pairs for another equity, and the API endpoints that trigger it are `POST /api/v1/trades`, `PUT /api/v1/trades/{trade_id}`, and `DELETE /api/v1/trades/{trade_id}` (all declared in `backend/app/api/v1/endpoints/trade.py`). The read-only `GET /api/v1/trades/pairs` endpoint never triggers recalculation; it just reads whatever the last mutation produced.

## Short-selling path

Shorts use a separate queue but the same algorithm. A `short` trade opens a lot in `short_queue`; a `cover` drains it FIFO. The only asymmetry is the P&L sign: `(open_price - close_price)` instead of `(close_price - open_price)`. Long and short queues are independent — a buy never matches against an open short, and a sell never matches against an open short. That also means if a user flips direction (sells more than they own), the excess sell quantity is silently discarded once `long_queue` is empty. It does not open a short.

## Edge cases and known gaps

- **Partial matches are native.** A single close trade can produce multiple `trade_pairs` rows, one per open lot it touches. The final partial open lot is written back to the queue with `open_qty - matched`.
- **Fees are ignored by P&L.** `realized_pnl` is pure price-delta times quantity. The `fees` column on `Trade` participates in `total_cost` and in the `_calculate_positions` cost-basis math, but it is not subtracted from `realized_pnl` on a pair. Net-of-fees realized P&L is not currently computed anywhere.
- **Oversold / over-covered quantity is dropped.** If a sell exceeds the long queue, the `while remaining > 0 and long_queue` loop exits and the leftover quantity is lost with no pair written and no error raised. Same for cover vs. short queue.
- **Same-timestamp tiebreaker is `trades.id` implicitly.** The ORDER BY is `Trade.executed_at` only. When multiple trades share a timestamp, Postgres returns them in an unspecified order, which in practice is insertion order (ascending `id`). If this matters, enforce ordering upstream.
- **No wash sale logic.** Losses are booked in full on the close date. Wash sale rules, superficial loss rules, and any tax-lot adjustments are out of scope.
- **Float vs. Decimal.** All math runs in `Decimal` end-to-end; no `float` conversions happen in the matching path.

## Testing

No dedicated test file currently covers `_recalculate_pairs`. `backend/tests/test_services/` contains `test_alert_service.py` but no `test_trade_service.py`. This is a known gap — the algorithm is exercised only through manual use and the `backend/scripts/seed_trades.py` script. Adding a unit test that walks the worked example above is the recommended first test.
