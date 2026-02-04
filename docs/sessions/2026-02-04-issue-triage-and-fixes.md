# Session: Issue Triage and Bug Fixes

**Date:** 2026-02-04
**Focus:** CI/CD improvements, issue triage, bug fixes, caching implementation

## Summary

Productive session focused on deployment improvements, triaging user-reported issues, and implementing critical fixes.

## Accomplished

### 1. CI/CD and Deployment Improvements

- **Git SSH on Synology**: Configured SSH key authentication for GitHub
  - Added SSH key at `~/.ssh/id_ed25519`
  - Changed remote from HTTPS to SSH
  - Fixed `core.fileMode` for permission tracking

- **Created deployment scripts**:
  - `scripts/test-build.sh` - Local build testing (TypeScript, ESLint, Docker)
  - `scripts/deploy-synology.sh` - One-command deployment to Synology

- **Fixed deployment issues**:
  - Added Node 20 PATH to scripts (Synology has Node 14 default)
  - Regenerated `package-lock.json` for npm ci compatibility
  - Created `frontend/.eslintrc.json` for build configuration
  - Fixed `--env-file .env.production` in docker-compose commands

### 2. Issue Triage

Categorized 22 user-reported issues:
- **Quick Fixes**: 4 items (fixed same session)
- **Easy Features**: 6 items
- **Medium Features**: 3 items
- **Large Features**: 7 items
- **Investigation Required**: 1 item (alert bug)

Created formal issue documentation (004-011) in `/docs/issues/`.

### 3. Quick UI Fixes Deployed

| Component | Fix |
|-----------|-----|
| `EditItemModal.tsx` | Calendar toggle default: `true` → `false` |
| `AddToWatchlistButton.tsx` | Fixed transparent dropdown background |
| `FundamentalsCard.tsx` | Fixed dividend yield % display (values >1) |
| `calendar/page.tsx` | Added `flex-wrap` for mobile button overflow |

### 4. Issue 011: Alert Crosses Detection Bug (HIGH PRIORITY)

**Root Cause**: `crosses_above`/`crosses_below` alerts used `last_checked_value` which updates every check. If price was already above threshold when alert created, it would never trigger.

**Solution**: Added `was_above_threshold` boolean field to track threshold-relative state.

**Files Changed**:
- `backend/app/db/models/alert.py` - Added `was_above_threshold` field
- `backend/app/services/alert.py` - Updated `_evaluate_condition()` and `process_alert()`
- `backend/alembic/versions/20260204_001_add_was_above_threshold_to_alerts.py` - Migration

### 5. Issue 006: Data Caching (Partial Implementation)

Implemented simple Redis caching directly in `YahooFinanceProvider`:

| Data Type | Cache TTL | Cache Key |
|-----------|-----------|-----------|
| Quotes | 5 minutes | `quote:{symbol}` |
| Fundamentals | 1 hour | `fundamentals:{symbol}` |

**Performance**: ~22x faster for cached requests (440ms → 20ms)

**File Changed**: `backend/app/services/data_providers/yahoo.py`

## Commits

1. `feat: add CI/CD scripts for local testing and Synology deployment`
2. `fix: quick UI fixes from issue triage`
3. `docs: create issue documentation (004-011)`
4. `fix: alert crosses detection using was_above_threshold`
5. `feat: add Redis caching to Yahoo Finance provider`
6. `docs: update Issue 006 - basic caching implemented`

## Deployment Notes

- Synology uses `docker-compose.local.yml` (not default `docker-compose.yml`)
- Native PostgreSQL on Synology uses port 5432 - local compose doesn't expose db port
- Deploy command: `docker-compose -f docker-compose.local.yml --env-file .env.production up -d`

## Remaining Open Issues

| # | Issue | Priority |
|---|-------|----------|
| 001 | Claude OAuth Support | Medium |
| 004 | Chart Enhancements | Medium |
| 005 | Daily Movers Notification | Medium |
| 007 | News Integration | Low |
| 008 | Cross-Watchlist Movers | Medium |
| 009 | Calendar Event Management | Medium |
| 010 | Mobile Responsive Fixes | Medium |

## Next Steps

1. Consider implementing chart timeframe buttons (Issue 004) - good user experience win
2. Mobile responsive fixes (Issue 010) - affects daily usability
3. Daily movers notification (Issue 005) - useful feature addition
4. Resolve Claude OAuth (Issue 001) to unblock AI features

## Technical Notes

- Cache gracefully falls back to API on Redis errors
- Cross alert baseline established on first check (no trigger until second check)
- `was_above_threshold` persists across alert checks for reliable detection
