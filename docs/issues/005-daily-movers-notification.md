# Issue 005: Daily Movers Notification Summary

**Status:** Open
**Created:** 2026-02-04
**Priority:** Medium
**Affects:** Notifications, Alerts system

## Summary

Create a daily summary notification that reports watchlist equities that moved more than 5% (up or down). This should be a scheduled notification at a configurable time, not spam throughout the day.

## Current Behavior

- Individual alerts trigger immediately when conditions are met
- No aggregation or summary of daily activity
- No way to see "who moved the most today" at a glance

## Proposed Solution

### Backend Changes

1. **New Celery task: `send_daily_movers_summary`**
   ```python
   @celery_app.task
   def send_daily_movers_summary():
       # Get all watchlist items for authenticated users
       # Calculate daily change for each
       # Filter to those with |change| > 5%
       # Group by up/down
       # Send Discord notification
   ```

2. **Schedule task in Celery Beat:**
   ```python
   'daily-movers-summary': {
       'task': 'app.tasks.alerts.send_daily_movers_summary',
       'schedule': crontab(hour=16, minute=30),  # 4:30 PM market close
   },
   ```

3. **Add user setting for notification preference:**
   - Enable/disable daily summary
   - Threshold percentage (default 5%)
   - Notification time preference

### Notification Format

```
📊 Daily Movers Summary - Feb 4, 2026

🚀 Big Gainers:
• NVDA +8.2% ($892.50)
• TSLA +6.1% ($245.30)

📉 Big Losers:
• INTC -7.3% ($42.15)
• META -5.5% ($485.20)

📊 Your watchlist: 4 of 25 moved >5%
```

## Files Affected

- `backend/app/tasks/alerts.py` - New task
- `backend/app/tasks/celery_app.py` - Schedule configuration
- `backend/app/services/notifications/discord.py` - Message formatting
- `backend/app/db/models/user_settings.py` - New preferences
- `frontend/src/components/alert/NotificationSettings.tsx` - UI for preferences

## Effort Estimate

- Backend task: 2-3 hours
- User settings: 1-2 hours
- Discord formatting: 1 hour
- Frontend settings UI: 1-2 hours
- Testing: 1-2 hours

**Total: ~7-10 hours (1-1.5 days)**

## Future Enhancements

- Weekly summary option
- Sector-based grouping
- Performance vs indices comparison
- Email notification option
