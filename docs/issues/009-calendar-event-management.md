# Issue 009: Calendar Event Auto-Add and Management

**Status:** Partially Resolved
**Created:** 2026-02-04
**Updated:** 2026-02-04
**Priority:** Medium
**Affects:** Calendar, Equity page, Watchlist

## Summary

Two related issues with calendar event management:

1. **Auto-add behavior:** Viewing equity events seems to automatically add them to the calendar. Users often just want to see when earnings are without tracking them.

2. **Delete capability:** No way to remove individual equity events from the calendar (e.g., if no longer tracking a stock).

## Resolution

### Fix 2: Delete Capability - IMPLEMENTED

Added delete button to `EventDetailModal` for custom events (user-created events).

**Changes made:**
- Updated `frontend/src/components/event/EventDetailModal.tsx`:
  - Added `useState` for delete confirmation modal
  - Added `useDeleteEvent` hook integration
  - Added `onDeleted` callback prop
  - Added conditional delete button (only shows for events with `source === 'manual'` and non-null `user_id`)
  - Added delete confirmation modal using `ConfirmModal` component
  - Delete button styled with red color in footer

**Behavior:**
- Custom events (source: 'manual') show a red "Delete" button in the modal footer
- System events (earnings from Yahoo, seeded macro events) do NOT show a delete button
- Clicking Delete shows a confirmation dialog
- After deletion, the modal closes and the calendar refreshes

### Fix 1: Auto-Add Behavior - NOT REQUIRED

After investigation, the current behavior does NOT auto-add events when viewing:
- `EquityEvents` component only reads events from the backend
- Events are fetched from Yahoo Finance when equity is created or when "Refresh" is clicked
- Viewing the equity page does not create new events

The original issue description may have been a misunderstanding. The current behavior is correct:
- Earnings dates come from Yahoo Finance during equity creation/refresh
- They are global data, not per-user
- Users can control which equities they track via watchlists

## Remaining Work

**Optional enhancements (not required):**
1. Add 'custom' event type to default calendar filter so custom events show by default
2. Allow users to "hide" system events from their calendar view (soft filter, not delete)

## Files Changed

- `frontend/src/components/event/EventDetailModal.tsx` - Added delete functionality

## Edge Cases Resolved

- **Macro events (FOMC, CPI):** NOT deletable - these are system events
- **Equity events (earnings, dividends):** NOT deletable - these are global data from Yahoo
- **Custom events:** Deletable by the user who created them
