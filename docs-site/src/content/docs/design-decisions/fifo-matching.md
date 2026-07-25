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
2. Loads every `Trade` for that `(user_id, equity_id)`, ordered by `executed_at` ascending with `id` as a secondary sort key, so trades sharing a timestamp still sort deterministically.
3. Walks the trades in order, maintaining FIFO queues keyed by `account_id` (`None` is its own "unassigned" partition): `long_queues[account_id]` for open buys, `short_queues[account_id]` for open shorts. Each queue entry is a tuple of `(trade_id, remaining_quantity, price, executed_at, open_fee_per_share)`. A close only matches opens in the same account — **FIFO matching is partitioned by account**.
4. On a `buy`, appends to `long_queues[trade.account_id]`. On a `short`, appends to `short_queues[trade.account_id]`.
5. On a `sell`, drains `long_queues[trade.account_id]` from the head until the sell is fully matched or the queue is empty. On a `cover`, does the same against `short_queues[trade.account_id]`.
6. For each match, writes a `TradePair` row (carrying the same `account_id`) and decrements the open lot.

Long realized P&L is `quantity_matched * (close_price - open_price) - quantity_matched * (open_fee_per_share + close_fee_per_share)`. Short realized P&L is the asymmetric `quantity_matched * (open_price - close_price) - quantity_matched * (open_fee_per_share + close_fee_per_share)` — profit accrues when the cover price is below the short price. `open_fee_per_share` and `close_fee_per_share` come from `_fee_per_share()`, which spreads a trade's whole-order `fees` evenly across its `quantity`; both legs' matched share of commission is netted out of `realized_pnl`. `holding_period_days` is `(close.executed_at - open.executed_at).days` in both cases.

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
- **Fees are netted into `realized_pnl`, not ignored.** Each pair's `realized_pnl` subtracts the matched share of both legs' commissions (see [the algorithm](#the-algorithm) for the formula and `_fee_per_share()` at `trade.py:33`). `backend/tests/test_services/test_trade_fees.py` (`TestRealizedPnlIncludesFees`) covers this directly.
- **Oversold / over-covered quantity is dropped.** If a sell exceeds the long queue, the `while remaining > 0 and long_queue` loop exits and the leftover quantity is lost with no pair written and no error raised. Same for cover vs. short queue.
- **Same-timestamp ties are broken by `id` explicitly.** The ORDER BY is `Trade.executed_at, Trade.id` (`trade.py:482`) — trades sharing a timestamp sort deterministically by ascending `id` rather than relying on Postgres's unspecified tie order. `backend/tests/test_services/test_trade_fifo_tiebreak.py` covers this directly.
- **No wash sale logic.** Losses are booked in full on the close date. Wash sale rules, superficial loss rules, and any tax-lot adjustments are out of scope.
- **Float vs. Decimal.** All math runs in `Decimal` end-to-end; no `float` conversions happen in the matching path.

## Testing

`_recalculate_pairs` itself is covered across several files in `backend/tests/test_services/`, not one single `test_trade_service.py`: `test_trade_fifo_tiebreak.py` (same-timestamp ordering), `test_trade_fees.py` (fee netting into `realized_pnl`), and `test_trade_positions.py` (per-account partitioning, e.g. `test_fifo_matching_stays_within_account`). Two more files cover closely related but distinct code, not `_recalculate_pairs` directly: `test_open_lots.py` tests `_get_open_lots`, the read-only sibling walk used for basis reconciliation, and `test_trade_journal_pair_order.py` tests `_closed_trade_pairs` in `trade_journal.py` — deterministic *display* ordering of already-computed pairs for the journal narrative, not FIFO matching itself.
