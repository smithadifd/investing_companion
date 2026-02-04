# Session: Deployment Issues - 2026-02-04 (Part 2)

## What Happened
After fixing calendar/events issues, attempted to deploy to Synology but encountered cascading issues:

1. **CORS Error** - API wasn't returning CORS headers for frontend at `192.168.50.88:3000`
2. **Database Port Conflict** - Docker db container couldn't start because native PostgreSQL was using port 5432
3. **Permission Errors** - Frontend and Celery containers couldn't write to volume mounts (different user ownership)
4. **DATABASE NUKED** - When we recreated the db container, it started fresh with empty data

## Root Causes
- Synology has native PostgreSQL on port 5432 (listening on 127.0.0.1 only)
- Docker compose recreates containers which loses data if volumes aren't properly persisted
- Container user (uid 1001) doesn't match Synology file ownership
- No backup strategy in place

## Fixes Applied (but need review)
- Changed db port to configurable `${POSTGRES_PORT:-5432}` (set to 5433 in prod)
- Added `user: root` to frontend, celery_worker, celery_beat containers
- Added CORS_ORIGINS, NEXT_PUBLIC_API_URL to .env.production

## TODO Next Session

### 1. Database Recovery
- Check if postgres_data volume still has data or if it was wiped
- If wiped, need to recreate user account and re-import any data
- Consider using native Synology PostgreSQL instead of Docker container

### 2. Backup Strategy
- Implement automated database backups
- Document backup/restore procedures
- Test restore process

### 3. Deployment Documentation
- Create `.env.synology` or similar for Synology-specific config (gitignored)
- Document SSH connection: `ssh synology` (alias for 192.168.50.88:12221, user fivefootfive)
- Document paths: `/volume3/docker/investing_companion/`
- Document which services run in Docker vs native

### 4. Architecture Decision: Docker DB vs Native DB
Options:
- **Docker DB**: Isolated, portable, but permission issues and port conflicts
- **Native Synology PostgreSQL**: Already running, but needs configuration for app access

### 5. Files Modified This Session
- `docker-compose.yml` - Added user: root, configurable ports/env vars
- `.env.production` on Synology - Added CORS_ORIGINS, POSTGRES_PORT, NEXT_PUBLIC_API_URL

## Synology Connection Info (for reference)
```
SSH: ssh synology (configured in ~/.ssh/config)
  - Host: 192.168.50.88
  - Port: 12221
  - User: fivefootfive

Docker path: /volume3/docker/investing_companion/
Git: /usr/local/bin/git (not in default PATH)
Docker compose: docker-compose (with hyphen, not space)

Native PostgreSQL: Running on 127.0.0.1:5432
Docker PostgreSQL: Configured for port 5433
```

## Commands to Check Status
```bash
# SSH to Synology
ssh synology

# Check containers
cd /volume3/docker/investing_companion
export PATH=/usr/local/bin:$PATH
docker-compose --env-file .env.production ps

# Check API health
curl http://localhost:8000/health?detailed=true

# Check database volume
docker volume inspect investing_companion_postgres_data
```
