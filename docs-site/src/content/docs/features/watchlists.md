---
title: Watchlists
description: Organize equities into named lists with per-item thesis, target price, notes, and calendar tracking.
---

A watchlist is a named collection of equities you want to follow. You can have as many as you need — one per strategy, one per sector, one for speculative ideas, whatever works. One watchlist can be marked as the default, which is where `AddToWatchlistButton` sends equities when no explicit list is chosen.

Each item on a watchlist belongs to a specific equity (no duplicates within the same list) and carries four optional fields you fill in over time: a short-form `notes` field, a longer `thesis`, a `target_price`, and a `track_calendar` flag that controls whether the equity's earnings and economic events appear on the calendar view.

See [Domain model](/architecture/domain-model/) for the underlying `watchlists` and `watchlist_items` tables, and [Data flow](/architecture/data-flow/) for how quote reads work.

## Watchlist CRUD

All watchlist endpoints live under `/api/v1/watchlists` and require an authenticated session.

| Method | Path | What it does |
| ------ | ---- | ------------ |
| `GET` | `/api/v1/watchlists` | List all watchlists with item counts |
| `POST` | `/api/v1/watchlists` | Create a watchlist |
| `GET` | `/api/v1/watchlists/{id}` | Get a watchlist with all items (and optional live quotes) |
| `PUT` | `/api/v1/watchlists/{id}` | Rename, re-describe, or change the default flag |
| `DELETE` | `/api/v1/watchlists/{id}` | Delete the watchlist and all its items |

`POST /api/v1/watchlists` accepts:

```json
{
  "name": "High conviction",
  "description": "Positions I'd size up on a dip",
  "is_default": false
}
```

`name` is required (1–100 characters). Setting `is_default: true` automatically clears the flag from whichever list held it before — only one default can exist at a time.

`GET /api/v1/watchlists/{id}` accepts an `include_quotes` query parameter (default `true`). When true, the response embeds a live quote for every item in the list. Pass `include_quotes=false` if you just need the metadata and don't want to trigger quote fetches.

Quotes are read from the cache layer, not fetched fresh on every request. See [Data flow](/architecture/data-flow/) for TTL and refresh behavior.

## Watchlist items

Add an equity to a list with `POST /api/v1/watchlists/{id}/items`:

```json
{
  "symbol": "NVDA",
  "target_price": 110.00,
  "thesis": "Data center capex cycle still early",
  "notes": "Watch for margin compression in H2",
  "track_calendar": true
}
```

You can pass either `symbol` (looked up or created automatically) or `equity_id` (if you already know the internal ID). One of the two is required.

The `(watchlist_id, equity_id)` pair has a unique constraint (`uq_watchlist_equity`). Attempting to add the same equity twice returns a 400 — the service rolls back the integrity error and returns `null`, which the endpoint surfaces as "Could not add item."

Item fields and their constraints:

| Field | Type | Limit |
| ----- | ---- | ----- |
| `notes` | text | 5,000 characters |
| `thesis` | text | 10,000 characters |
| `target_price` | decimal | must be >= 0, stored as `Numeric(12, 2)` |
| `track_calendar` | boolean | defaults to `true` |

Update any of these after the fact with `PUT /api/v1/watchlists/{watchlist_id}/items/{item_id}`. Remove an item with `DELETE /api/v1/watchlists/{watchlist_id}/items/{item_id}`.

In the UI, the `EditItemModal` component surfaces all four fields in a modal triggered by the pencil icon on each `WatchlistItemRow`. Changes go straight to the update endpoint. There is no inline editing — the row itself is read-only.

## Export and import

### Exporting

`GET /api/v1/watchlists/{id}/export` returns a JSON document (not CSV) with the watchlist name, optional description, an `exported_at` timestamp, and an array of items:

```json
{
  "name": "High conviction",
  "description": "Positions I'd size up on a dip",
  "exported_at": "2025-03-15T10:30:00Z",
  "items": [
    {
      "symbol": "NVDA",
      "name": "NVIDIA Corporation",
      "notes": "Watch for margin compression in H2",
      "target_price": "110.00",
      "thesis": "Data center capex cycle still early",
      "added_at": "2025-01-10T08:00:00Z"
    }
  ]
}
```

The export includes `symbol`, `name`, `notes`, `target_price`, `thesis`, and `added_at` per item.

### Importing

`POST /api/v1/watchlists/import` creates a new watchlist from a JSON body matching the export shape. The `name` and `items` array are required; `description` is optional. Each item needs at minimum a `symbol`; `notes`, `target_price`, and `thesis` are optional.

```json
{
  "name": "Imported list",
  "items": [
    { "symbol": "AAPL", "target_price": 180.00 },
    { "symbol": "MSFT" }
  ]
}
```

Imported watchlists always start with `is_default: false`. Symbols that can't be resolved are silently skipped — the import does not fail if individual equities are missing. Importing does not check for an existing watchlist with the same name; it always creates a new one.

In the UI, the `ImportWatchlistModal` component handles file selection (or drag-and-drop), parses the JSON client-side, shows a preview of the watchlist name and symbol list, and submits on confirmation.

## Quote fetching

When `GET /api/v1/watchlists/{id}` runs with `include_quotes=true`, the service calls `equity_service.get_quote(symbol)` once per item in sequence. Quotes are served from the cache — the watchlist endpoint does not have a dedicated bulk quote path. For a watchlist with many items, load time scales with cache hit rate. The `/api/v1/watchlists/movers` endpoint aggregates gainers and losers across all watchlists and deduplicate symbols before fetching quotes, which makes it more efficient for cross-list summaries.

## UI features

The watchlist detail page (`/watchlists/[id]/page.tsx`) supports column sorting by symbol, price, day change, and target price. The default sort is by absolute change percentage — biggest movers appear first regardless of direction.

Row backgrounds shift to a faint green or red tint when a position has moved more than 3% in either direction. The `WatchlistItemRow` component shows a calendar icon next to the ticker symbol when `track_calendar` is enabled for that item.

The `AddToWatchlistButton` component is available on equity detail pages and sends to the user's default watchlist without prompting, or opens a list selector if no default is set.
