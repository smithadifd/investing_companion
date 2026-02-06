# Known Issues

Tracked issues and limitations that don't block development but need future resolution.

| ID | Title | Status | Priority | Affects |
|----|-------|--------|----------|---------|
| [001](./001-claude-oauth-support.md) | Claude Max OAuth Token Support | Open | Medium | AI Analysis |
| [002](./002-local-build-testing.md) | Add Local Production Build Testing | Resolved | Low | Deployment |
| [003](./003-synology-git-sync.md) | Synology Git Repository Sync | Resolved | Medium | Deployment |
| [004](./004-chart-enhancements.md) | Chart Timeframe and Type Enhancements | Open | Medium | Charts |
| [005](./005-daily-movers-notification.md) | Daily Movers Notification Summary | Resolved | Medium | Notifications |
| [006](./006-data-caching.md) | Data Caching and Background Updates | Partial | Medium | Performance |
| [007](./007-news-integration.md) | News Integration | Open | Low | Equity Page |
| [008](./008-cross-watchlist-movers.md) | Cross-Watchlist Top Movers | Open | Medium | Dashboard |
| [009](./009-calendar-event-management.md) | Calendar Event Auto-Add and Management | Open | Medium | Calendar |
| [010](./010-mobile-responsive-fixes.md) | Mobile Responsive Design Fixes | Open | Medium | Mobile UI |
| [011](./011-alert-crosses-detection-bug.md) | Alert "Crosses Above/Below" Detection Bug | Resolved | High | Alerts |
| [012](./012-redis-cache-event-loop.md) | Redis Cache Client Event Loop in Celery | Open | Low | Celery/Caching |
| [013](./013-news-page.md) | News Page & Catalyst Integration | Planned | Low | Notifications/UI |
| [014](./014-intelligent-agents.md) | Intelligent Product Agents | Planned | Medium | Notifications/AI/Trading |

## Quick Reference

### Partial (Basic Implementation Done)
- **006**: Data caching - basic Redis caching implemented (5-min quotes, 1-hr fundamentals)

### High Priority
- None currently

### Medium Priority
- **004**: Chart timeframes and line chart toggle
- **008**: Cross-watchlist top movers view
- **009**: Calendar event auto-add behavior and delete
- **010**: Mobile responsive fixes

### Low Priority
- **007**: News integration (nice to have)
- **012**: Redis cache event loop lifecycle in Celery tasks
- **013**: News page & catalyst notes for notification summaries

### Resolved
- **002**: Local build testing - scripts added
- **003**: Git sync on Synology - SSH configured
- **005**: Daily movers notification - replaced with rich morning pulse + EOD wrap summaries
- **011**: Alert crosses detection bug - fixed with `was_above_threshold` tracking
