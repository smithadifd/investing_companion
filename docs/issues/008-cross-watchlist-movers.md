# Issue 008: Cross-Watchlist Top Movers

**Status:** Resolved
**Created:** 2026-02-04
**Resolved:** 2026-02-04
**Priority:** Medium
**Affects:** Dashboard, potentially new insights page

## Summary

Show top movers across ALL watchlists at a glance, not just a single default watchlist. This provides a quick view of the biggest gainers and losers across the user's entire portfolio tracking.

## Resolution

Implemented Option A: Enhanced Dashboard Widget with aggregate backend endpoint.

### Backend Changes

1. Added new Pydantic schemas in `backend/app/schemas/watchlist.py`:
   - `MoverItem` - Individual mover with symbol, name, price, change info, and source watchlist
   - `AllWatchlistMovers` - Container with gainers list, losers list, total items count, and watchlist count

2. Added `get_all_movers()` method in `backend/app/services/watchlist.py`:
   - Fetches all watchlists and their items
   - Gets quotes for all unique symbols
   - Deduplicates (same symbol in multiple watchlists picks first occurrence)
   - Sorts by change_percent and returns top gainers/losers

3. Added `/watchlists/movers` endpoint in `backend/app/api/v1/endpoints/watchlist.py`:
   - Returns `DataResponse[AllWatchlistMovers]`
   - Accepts `limit` parameter (1-50, default 10)

### Frontend Changes

1. Added types in `frontend/src/lib/api/types.ts`:
   - `MoverItem` interface
   - `AllWatchlistMovers` interface

2. Added API method `getAllWatchlistMovers()` in `frontend/src/lib/api/client.ts`

3. Added `useAllWatchlistMovers()` hook in `frontend/src/lib/hooks/useWatchlist.ts`

4. Rewrote `WatchlistMovers` component with:
   - Tabs: All / Gainers / Losers
   - Shows watchlist source as subtitle on each stock card
   - Displays "Across N watchlists (M equities)" summary
   - "All" mode interleaves top 3 gainers and top 3 losers

5. Added `subtitle` prop to `StockCard` component in `frontend/src/components/ui/StockCard.tsx`

### UI Result

```
┌─────────────────────────────────────────┐
│ Today's Movers           View All →     │
│ Across 3 watchlists (16 equities)       │
├─────────────────────────────────────────┤
│ [All] [📈 Gainers] [📉 Losers]          │
├─────────────────────────────────────────┤
│ 1  SLV    iShares Silver    $79.18      │
│    My Watchlist              +2.88%     │
│ 2  TSLA   Tesla Inc.       $406.01      │
│    My Watchlist              -3.78%     │
│ ...                                     │
└─────────────────────────────────────────┘
```

## Files Changed

- `backend/app/schemas/watchlist.py` - Added MoverItem, AllWatchlistMovers
- `backend/app/services/watchlist.py` - Added get_all_movers method
- `backend/app/api/v1/endpoints/watchlist.py` - Added /movers endpoint
- `frontend/src/lib/api/types.ts` - Added type interfaces
- `frontend/src/lib/api/client.ts` - Added getAllWatchlistMovers method
- `frontend/src/lib/hooks/useWatchlist.ts` - Added useAllWatchlistMovers hook
- `frontend/src/components/dashboard/WatchlistMovers.tsx` - Complete rewrite
- `frontend/src/components/ui/StockCard.tsx` - Added subtitle prop
