# Issue 005: Daily Movers Notification Summary

**Status:** Resolved
**Created:** 2026-02-04
**Resolved:** 2026-02-04
**Priority:** Medium
**Affects:** Notifications, Alerts system

## Summary

Create a daily summary notification that reports watchlist equities that moved more than 5% (up or down). This should be a scheduled notification at a configurable time, not spam throughout the day.

## Resolution

Implemented daily movers summary notification via Discord webhook.

### Implementation Details

#### 1. Discord Service - New Method (`backend/app/services/notifications/discord.py`)

Added `send_movers_summary()` method that:
- Takes gainers, losers, threshold, and summary stats
- Filters movers above the threshold (default 5%)
- Skips notification if no big movers (to avoid noise)
- Formats a rich Discord embed with:
  - Gainers section with symbol, change %, price, watchlist name
  - Losers section with symbol, change %, price, watchlist name
  - Summary showing total movers vs total items

#### 2. Celery Task (`backend/app/tasks/alerts.py`)

Added `send_daily_movers_summary` task that:
- Uses existing `WatchlistService.get_all_movers()` from Issue 008
- Converts Pydantic models to dicts for Discord service
- Accepts configurable `threshold_percent` parameter (default 5%)
- Logs results for monitoring

#### 3. Celery Beat Schedule (`backend/app/tasks/celery_app.py`)

Added schedule entry:
```python
"send-daily-movers-summary": {
    "task": "alerts.send_daily_movers_summary",
    "schedule": crontab(hour=21, minute=30),  # 4:30 PM ET
},
```

### Discord Message Format

```
📊 Daily Movers Summary - Feb 4, 2026

🚀 Big Gainers (>5%):
• NVDA +8.2% ($892.50) - Tech Watchlist
• TSLA +6.1% ($245.30) - My Watchlist

📉 Big Losers (<-5%):
• INTC -7.3% ($42.15) - Value Picks
• META -5.5% ($485.20) - My Watchlist

📈 Summary
4 of 25 equities moved >5% across 3 watchlists
```

### Schedule

- **Time**: 9:30 PM UTC (4:30 PM Eastern Time)
- **Frequency**: Daily (weekdays and weekends, though weekends will have no movers)
- **Threshold**: 5% (configurable via task argument)

### Files Changed

- `backend/app/services/notifications/discord.py` - Added `send_movers_summary()` method
- `backend/app/tasks/alerts.py` - Added `send_daily_movers_summary` task
- `backend/app/tasks/celery_app.py` - Added schedule entry

## Future Enhancements

- Weekly summary option
- Sector-based grouping
- Performance vs indices comparison
- Email notification option
- User setting to enable/disable and customize threshold
