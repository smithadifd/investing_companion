# Issue 008: Cross-Watchlist Top Movers

**Status:** Open
**Created:** 2026-02-04
**Priority:** Medium
**Affects:** Dashboard, potentially new insights page

## Summary

Show top movers across ALL watchlists at a glance, not just a single default watchlist. This provides a quick view of the biggest gainers and losers across the user's entire portfolio tracking.

## Current Behavior

- `WatchlistMovers` component only shows items from the first/default watchlist
- No way to see aggregate movers across multiple watchlists
- Users must visit each watchlist individually to find big movers

## Proposed Solution

### Option A: Enhanced Dashboard Widget

Modify existing `WatchlistMovers` to aggregate from all watchlists:

```tsx
// Show top 5 gainers and top 5 losers across all watchlists
const allItems = watchlists.flatMap(w => w.items);
const sorted = allItems.sort((a, b) => b.changePercent - a.changePercent);
const topGainers = sorted.slice(0, 5);
const topLosers = sorted.slice(-5).reverse();
```

### Option B: New "Insights" Page

Create dedicated page at `/insights` showing:
- Cross-watchlist movers (aggregated)
- Sector breakdown
- Portfolio performance summary
- Upcoming events for tracked equities

### UI Design (Option A)

```
┌─────────────────────────────────────────┐
│ 📈 Today's Movers (All Watchlists)      │
├─────────────────────────────────────────┤
│ 🚀 Top Gainers         📉 Top Losers    │
│ ───────────────────    ───────────────  │
│ NVDA  +8.2%  [Tech]    INTC  -7.3%     │
│ TSLA  +6.1%  [Growth]  META  -5.5%     │
│ AMD   +4.3%  [Tech]    NFLX  -3.2%     │
└─────────────────────────────────────────┘
```

### Implementation

1. **Backend: Aggregate endpoint**
   ```python
   @router.get("/movers/all")
   async def get_all_watchlist_movers(
       user_id: int,
       limit: int = 10
   ):
       # Get all watchlists for user
       # Fetch quotes for all items
       # Sort by absolute change
       # Return top gainers and losers
   ```

2. **Frontend: Enhanced component**
   - Fetch from aggregate endpoint
   - Display with watchlist tags
   - Allow filtering by watchlist
   - Sort options (by % change, by absolute $)

## Files Affected

- `backend/app/api/v1/endpoints/watchlist.py` - New aggregate endpoint
- `frontend/src/components/dashboard/WatchlistMovers.tsx` - Enhanced component
- `frontend/src/lib/hooks/useWatchlist.ts` - New hook for aggregate data

## Effort Estimate

- Backend endpoint: 2-3 hours
- Frontend component updates: 2-3 hours
- Caching (performance): 1-2 hours
- Testing: 1-2 hours

**Total: ~6-10 hours (1 day)**

## Considerations

- Performance: Fetching quotes for many symbols
- Deduplication: Same symbol in multiple watchlists
- Display: Show which watchlist(s) contain each equity
