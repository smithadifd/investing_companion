# Session: Synology Production Deployment

**Date**: 2026-02-01
**Phase**: 6.6 Deployment (Execution)
**Status**: COMPLETE

---

## Overview

Deployed the Investing Companion application to Synology NAS at your-nas-ip. This session covered the actual deployment, debugging build errors, and resolving runtime issues.

---

## What Was Accomplished

### Discord Webhook Configuration (Post-Deployment)

1. **Feature Enhancement**
   - Modified Discord notification service to read webhook URL from user settings database
   - Previously only checked environment variable; now falls back to database
   - Allows users to configure Discord webhook via Settings UI without editing `.env`

2. **Debugging Journey**
   - Initial confusion: Mac Docker and Synology Docker both running with same container names
   - Database queries from Mac were hitting wrong database
   - Confirmed user data exists on Synology by testing login from phone
   - Root cause: Updated code was on Mac but not deployed to Synology

3. **Deployment Process**
   - Copied updated files via SMB to `/Volumes/docker/investing_companion`
   - SSH'd to Synology and ran rebuild: `docker-compose -f docker-compose.local.yml --env-file .env.production build api`
   - Restarted API container with new code
   - Test notification successful ✅

### Initial Setup

1. **Repository Transfer**
   - Git clone failed on Synology via SMB mount (filesystem limitations)
   - Cloned locally and copied to `/Volumes/docker/investing_companion`
   - Created `.env.production` with secure generated secrets

2. **Local Network Configuration**
   - Created `docker-compose.local.yml` for local network deployment (no Traefik/HTTPS)
   - Exposed ports directly: 3000 (frontend), 8000 (API)
   - Configured CORS for `your-nas-ip`

### Build Issues Resolved

| Issue | Root Cause | Fix |
|-------|-----------|-----|
| `service_completed_successfully` | Docker Compose v1 on Synology | Removed migrate container |
| Missing tailwindcss | `npm ci --only=production` excluded devDeps | Changed to `npm ci` |
| TypeScript Set iteration | ES5 target doesn't support Set iteration | Added `downlevelIteration: true`, `target: ES2015` |
| Missing EventStats | Not imported in calendar page | Added to import statement |
| Lucide icon title prop | Lucide doesn't accept `title` attribute | Wrapped in `<span title="...">` |
| Missing public folder | Next.js standalone requires it | Created with `.gitkeep` |
| Import collision | `settings` endpoint shadowed config | Aliased config as `app_settings` |
| CORS errors | NEXT_PUBLIC_API_URL not in build | Added ARG/ENV to Dockerfile |

### Security Updates

1. **Next.js Security Fix**
   - Updated from 14.1.0 to 14.2.29
   - Addresses SSRF vulnerability in Server Actions

2. **Registration Disabled**
   - Set `REGISTRATION_ENABLED=false` after account creation
   - Sign-in only mode for production

### Documentation

1. **Created Issues**
   - `docs/issues/002-local-build-testing.md` - Pre-deployment build testing
   - `docs/issues/003-synology-git-sync.md` - Git sync strategy

---

## Files Created

- `docker-compose.local.yml` - Local network deployment config
- `/Volumes/docker/investing_companion/.env.production` - Production secrets
- `/Volumes/docker/investing_companion/frontend/public/.gitkeep` - Empty dir for build
- `docs/issues/002-local-build-testing.md`
- `docs/issues/003-synology-git-sync.md`

## Files Modified

- `backend/app/services/notifications/discord.py` - Read webhook URL from database as fallback
- `backend/app/api/v1/endpoints/alert.py` - Use async config check for Discord status
- `backend/app/api/v1/endpoints/settings.py` - Clear Discord cache when settings updated
- `backend/app/main.py` - Aliased settings import as `app_settings`
- `frontend/tsconfig.json` - Added `downlevelIteration`, `target: ES2015`
- `frontend/src/app/calendar/page.tsx` - Added EventStats import
- `frontend/src/components/watchlist/WatchlistItemRow.tsx` - Fixed icon title
- `frontend/package.json` - Updated Next.js to 14.2.29
- `docker/Dockerfile.frontend.prod` - Added NEXT_PUBLIC_API_URL build arg, fixed npm ci
- `docs/issues/README.md` - Added new issues

---

## Commits

1. `0d21958` - fix: resolve deployment issues for Synology production build
2. (pending) - docs: add deployment session notes and known issues

---

## Current State

### Repository Sync Status

| Location | Commit | Files |
|----------|--------|-------|
| Mac | `0d21958` | ✅ Current |
| GitHub | `0d21958` | ✅ Current |
| Synology | `056948e` | ⚠️ One behind (files manually updated) |

### Running Services

```
your-nas-ip:3000 - Frontend (Next.js)
your-nas-ip:8000 - API (FastAPI)
Internal: PostgreSQL, Redis, Celery Worker, Celery Beat
```

### Docker Volumes (Data)

- `investing_postgres_data` - Database (persistent)
- `investing_redis_data` - Cache

---

## Lessons Learned

1. **Test builds locally first**
   - `docker compose -f docker-compose.local.yml build` catches TypeScript errors
   - Would have found most issues before deploying

2. **Docker Compose v1 vs v2**
   - Synology uses v1 (older syntax)
   - `service_completed_successfully` not supported
   - `depends_on` conditions work differently

3. **Next.js NEXT_PUBLIC_* variables**
   - Must be set at BUILD time, not runtime
   - Use ARG in Dockerfile to pass into build

4. **Git on Synology**
   - SMB mounts have issues with git operations
   - SSH directly or use Synology's Git package

5. **Docker Compose v1 vs v2 (Synology)**
   - Synology uses `docker-compose` (hyphen) not `docker compose` (space)
   - Commands like `docker compose -f` fail; use `docker-compose -f` instead

6. **Mac vs Synology Docker Confusion**
   - Running Docker on both Mac and Synology with same project causes confusion
   - Container names are identical; docker commands go to local Docker daemon
   - Stop Mac Docker when working on Synology deployment

---

## Future Synology Updates

When git is working on Synology:

```bash
cd /volume3/docker/investing_companion

# Backup first
./scripts/backup.sh ./backups

# Check status
git status

# Stash local changes
git stash

# Pull updates
git pull origin main

# Drop stash (files should match)
git stash drop

# Rebuild (note: docker-compose with hyphen on Synology)
docker-compose -f docker-compose.local.yml --env-file .env.production up -d --build
```

---

## Next Steps

1. Fix git on Synology for easier updates
2. Set up automated backups via Task Scheduler
3. ~~Configure Discord webhook for alerts~~ ✅ DONE
4. Add Claude API key when OAuth resolved (Issue 001)
