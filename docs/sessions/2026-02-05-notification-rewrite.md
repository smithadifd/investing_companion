# Session: Discord Notification Summary Rewrite - 2026-02-05

## Summary
Rewrote the morning and end-of-day Discord notifications from basic embed-based messages to rich, scannable plain-text summaries. Added configurable notification timing via the Settings UI.

## What Changed

### New Notification Format

**Morning Pulse (8:00 AM ET default)**
- Futures: ES, NQ, RTY change %
- VIX level/change + 10Y yield/basis point change
- Overnight Moves: Gold, Silver, DXY, Crude, Nat Gas, VEA, VWO grouped by category with color emoji
- Today's Calendar: medium+high importance events with type icons
- Watchlist Pre-Market Movers: >2% moves across all watchlists
- Alert Status: active count + overnight triggers

**End of Day Wrap (4:30 PM ET default)**
- Market Close: SPY, QQQ, IWM change % + VIX, 10Y, DXY levels
- Theme Performance: per non-default watchlist with emoji, benchmark, and narrative
- My Positions: best 2 / worst 2 from default watchlist
- Big Movers: >3% across all watchlists
- Alerts: triggered count + details
- Tomorrow's Calendar: next trading day medium+high events

### Configurable Timing
- Notification times are now configurable in Settings > Notifications
- Times stored in DB settings, checked every minute by a scheduler task
- Last-sent date tracking prevents double-sends
- Weekday-only (skips weekends)

### Technical Changes
- Plain text `content` field instead of Discord embeds (more compact, emoji-friendly)
- Graceful degradation: each section wrapped in try/except, skipped on failure
- Discord 2000-char limit handled with progressive section truncation
- DST-aware timezone handling using `zoneinfo.ZoneInfo("America/New_York")`

## Files Created
- `backend/app/services/notifications/formatters.py` - Formatting logic with `MorningData`, `EODData`, `ThemeData`, `AlertTrigger` dataclasses
- `docs/issues/013-news-page.md` - Future news/catalyst integration ticket

## Files Modified
- `backend/app/schemas/auth.py` - Added `morning_notification_time` and `eod_notification_time` fields
- `backend/app/services/settings.py` - Added 4 notification setting keys and wired into get/update
- `backend/app/services/notifications/discord.py` - Added `send_plain_text()` method
- `backend/app/tasks/alerts.py` - Replaced `send_morning_events`/`send_end_of_day_summary` with `send_morning_pulse`/`send_eod_wrap`/`check_notification_schedule`
- `backend/app/tasks/__init__.py` - Updated exports
- `backend/app/tasks/celery_app.py` - Replaced crontab entries with 60s scheduler
- `frontend/src/lib/api/types.ts` - Added notification time TypeScript types
- `frontend/src/app/settings/page.tsx` - Added notification schedule UI with time pickers
- `docs/issues/README.md` - Added issue 013, marked 005 as resolved

## Verification
- Dry-ran morning pulse with live Yahoo Finance data (430 chars, well under 2000 limit)
- Dry-ran EOD wrap with live market data + sample positions (530 chars)
- Verified imports and formatter output via Python REPL

## Next Steps
- Monitor first real morning pulse and EOD wrap on Synology
- Issue 013: Add news/catalyst notes to notification summaries (future)
