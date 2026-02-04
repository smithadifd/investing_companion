# Issue 009: Calendar Event Auto-Add and Management

**Status:** Open
**Created:** 2026-02-04
**Priority:** Medium
**Affects:** Calendar, Equity page, Watchlist

## Summary

Two related issues with calendar event management:

1. **Auto-add behavior:** Viewing equity events seems to automatically add them to the calendar. Users often just want to see when earnings are without tracking them.

2. **Delete capability:** No way to remove individual equity events from the calendar (e.g., if no longer tracking a stock).

## Current Behavior

### Issue 1: Auto-Add
- Opening equity events component may trigger event creation
- No clear UX indicating "these events will be tracked"
- No option to "just view" vs "add to calendar"

### Issue 2: No Delete
- `EventDetailModal` shows event info but no delete option
- User must remove equity from watchlist to stop seeing events
- No way to delete individual events

## Proposed Solution

### Fix 1: Explicit Add-to-Calendar

1. **Separate viewing from tracking:**
   - Equity page shows earnings date as read-only info
   - Explicit "Track on Calendar" button to add events
   - Match the existing `track_calendar` toggle on watchlist items

2. **Clear UX:**
   ```
   Next Earnings: Feb 15, 2026
   [📅 Add to Calendar]  ← Only adds if clicked
   ```

### Fix 2: Event Deletion

1. **Add delete to EventDetailModal:**
   ```tsx
   <button onClick={handleDelete}>
     <Trash className="h-4 w-4" />
     Remove from Calendar
   </button>
   ```

2. **Backend delete endpoint:**
   ```python
   @router.delete("/events/{event_id}")
   async def delete_event(event_id: int, user_id: int):
       # Verify ownership (user's equity event or custom event)
       # Delete event
       # Return success
   ```

3. **Confirmation dialog:**
   - For equity events: "Remove this event? Future events for {symbol} will still appear if tracking is enabled."
   - For custom events: "Delete this event? This cannot be undone."

## Files Affected

- `frontend/src/components/equity/EquityEvents.tsx` - Separate view from add
- `frontend/src/components/event/EventDetailModal.tsx` - Add delete button
- `backend/app/api/v1/endpoints/event.py` - Delete endpoint
- `backend/app/services/economic_event.py` - Delete logic

## Effort Estimate

### Fix 1: Auto-Add
- Investigate current behavior: 1 hour
- Modify EquityEvents component: 1-2 hours
- Testing: 1 hour
**Subtotal: 3-4 hours**

### Fix 2: Delete
- Backend endpoint: 1 hour
- Frontend modal updates: 1-2 hours
- Confirmation dialog: 30 min
- Testing: 1 hour
**Subtotal: 3-4 hours**

**Total: ~6-8 hours (1 day)**

## Edge Cases

- Deleting system macro events (FOMC, CPI) - should these be deletable?
- Deleting equity event when still tracking equity - will re-appear?
- Soft delete vs hard delete
