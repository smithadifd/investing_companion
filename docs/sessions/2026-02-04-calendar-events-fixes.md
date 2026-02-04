# Session: Calendar & Events Fixes

**Date:** 2026-02-04
**Focus:** Calendar filter fixes, equity events auto-fetch, Discord notifications

## Summary

This session focused on fixing the "Watchlist equities only" calendar filter, implementing auto-fetch for equity events, and adding morning events Discord notifications.

## Issues Addressed

### 1. Calendar "Watchlist equities only" Filter Not Working

**Problem:** The filter checkbox wasn't triggering API requests with the `watchlist_only` parameter.

**Root Cause:**
- The filters object wasn't being memoized, causing React Query to not detect changes
- The MCP browser automation tool was setting checkbox values via DOM without triggering React's onChange

**Fix:**
- Added `useMemo` to memoize the filters object in `calendar/page.tsx`
- Filter now correctly sends `watchlist_only=true` to the API

**Behavior Clarification:**
- "Watchlist equities only" filters to show ONLY events for equities IN the user's watchlist
- Macro events (CPI, FOMC, etc.) are excluded when this filter is enabled
- Equities that have events tracked but are NOT in a watchlist won't appear

### 2. Equity Events Not Auto-Loading

**Problem:** Users had to click "Track Events" to see any events for an equity, even if events might exist.

**Fix:** Modified `EquityEvents.tsx` to auto-fetch events when the component mounts:
- Added `useEffect` hook to automatically call the refresh API when no events exist
- Shows "Loading events..." spinner during auto-fetch
- "Refresh" button always visible for manual re-fetch
- "Untrack" button only appears when events exist
- Reset auto-fetch flag when navigating to a different equity

### 3. Morning Events Discord Notification

**Added:** New Celery task and Discord service method to send daily morning events notifications.

**Schedule:** 7 AM ET (12 PM UTC) before market open

**Features:**
- Groups events by date
- Shows event icons based on type (earnings, dividends, FOMC, etc.)
- Displays symbol and title for each event
- Configurable days ahead (default: 2 days)

## Files Modified

### Frontend
- `frontend/src/app/calendar/page.tsx` - Added useMemo for filters
- `frontend/src/components/equity/EquityEvents.tsx` - Auto-fetch events on mount
- `frontend/src/components/event/EventDetailModal.tsx` - Added untrack button
- `frontend/src/components/charts/ChartControls.tsx` - Disabled indicators for non-daily intervals
- `frontend/src/lib/hooks/useEvents.ts` - Added useDeleteEquityEvents hook
- `frontend/src/lib/api/client.ts` - Added deleteEquityEvents method

### Backend
- `backend/app/services/economic_event.py` - Added delete_events_for_symbol method
- `backend/app/api/v1/endpoints/event.py` - Added DELETE /events/equity/{symbol} endpoint
- `backend/app/services/notifications/discord.py` - Added send_upcoming_events method
- `backend/app/tasks/alerts.py` - Added send_morning_events task
- `backend/app/tasks/celery_app.py` - Added morning events schedule

## Database State

After this session, the following equities have events tracked:
- CCJ (Cameco) - Earnings
- AAPL - Ex-Dividend, Earnings
- MSFT - Ex-Dividend, Dividend Payment, Earnings
- GOOGL - Earnings

Watchlist equities (AAPL, GOOGL, MSFT, etc.) are in watchlists, so they will appear when "Watchlist equities only" is checked IF they have events.

## Celery Beat Schedule

Updated schedule includes:
- Check alerts every 5 minutes
- Daily alert summary at 6 PM UTC
- Daily movers summary at 9:30 PM UTC (4:30 PM ET)
- **Morning events at 12 PM UTC (7 AM ET)** - NEW
- Refresh watchlist events at 10 PM UTC (5 PM ET)

## Testing Notes

1. Calendar filter works correctly - macro events hidden when "Watchlist equities only" checked
2. Equity events auto-fetch on first view
3. Untrack functionality removes all auto-fetched events for an equity
4. Discord notification methods are ready (requires webhook configuration)

## Next Steps

- Consider adding a tooltip to "Watchlist equities only" explaining the filter
- Monitor auto-fetch performance for frequently visited equities
- Test Discord notifications when webhook is configured
