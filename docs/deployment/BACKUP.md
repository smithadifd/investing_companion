# Backup & Restore Procedures

This document covers backup and disaster recovery for Investing Companion.

---

## What Needs to Be Backed Up

| Component | Location | Priority | Notes |
|-----------|----------|----------|-------|
| PostgreSQL Database | Docker volume `investing_companion_postgres_data` | **Critical** | All user data, watchlists, trades, settings |
| Redis | Docker volume `investing_companion_redis_data` | Low | Cache only, regenerates automatically |
| Environment Config | `/volume3/docker/investing_companion/.env.production` | **Critical** | Contains secrets, not in git |

---

## Automated Backups

### Setup Automated Daily Backups

1. **Copy the backup script to Synology:**
   ```bash
   scp scripts/backup.sh synology:/volume3/docker/investing_companion/scripts/
   ```

2. **Make it executable:**
   ```bash
   ssh synology "chmod +x /volume3/docker/investing_companion/scripts/backup.sh"
   ```

3. **Create backup directory:**
   ```bash
   ssh synology "mkdir -p /volume3/docker/investing_companion/backups"
   ```

4. **Test the backup:**
   ```bash
   ssh synology "/volume3/docker/investing_companion/scripts/backup.sh"
   ```

5. **Schedule via Synology Task Scheduler:**
   - Open DSM > Control Panel > Task Scheduler
   - Create > Scheduled Task > User-defined script
   - Schedule: Daily at 3:00 AM (or preferred time)
   - Command: `/volume3/docker/investing_companion/scripts/backup.sh`
   - Enable email notifications for failures

### Backup Retention

The backup script keeps:
- Last 7 daily backups
- Older backups are automatically deleted

Adjust `RETENTION_DAYS` in `scripts/backup.sh` to change this.

---

## Manual Backup

### Database Backup

```bash
ssh synology
cd /volume3/docker/investing_companion

# Create backup with timestamp
docker-compose --env-file .env.production exec -T db \
  pg_dump -U investing_prod investing_companion | gzip > \
  backups/db_backup_$(date +%Y%m%d_%H%M%S).sql.gz
```

### Environment Config Backup

```bash
# Backup .env.production (contains secrets - store securely!)
ssh synology "cat /volume3/docker/investing_companion/.env.production" > \
  ~/investing_env_backup_$(date +%Y%m%d).txt

# Store this file securely (password manager, encrypted drive, etc.)
```

---

## Restore Procedures

### Restore Database from Backup

**Warning:** This will overwrite all current data!

```bash
ssh synology
cd /volume3/docker/investing_companion

# Stop services that use the database
docker-compose --env-file .env.production stop api celery_worker celery_beat

# Restore from backup (replace filename with your backup)
gunzip -c backups/db_backup_20260204_030000.sql.gz | \
  docker-compose --env-file .env.production exec -T db \
  psql -U investing_prod -d investing_companion

# Restart services
docker-compose --env-file .env.production start api celery_worker celery_beat

# Verify
curl http://localhost:8000/health?detailed=true
```

### Restore After Complete Data Loss

If volumes were deleted (`docker-compose down -v` or similar):

1. **Recreate containers:**
   ```bash
   docker-compose --env-file .env.production up -d
   ```

2. **Wait for database to initialize:**
   ```bash
   sleep 10
   docker-compose --env-file .env.production ps  # Ensure db is healthy
   ```

3. **Run migrations to create schema:**
   ```bash
   docker-compose --env-file .env.production exec api alembic upgrade head
   ```

4. **Restore data from backup:**
   ```bash
   gunzip -c backups/db_backup_YYYYMMDD_HHMMSS.sql.gz | \
     docker-compose --env-file .env.production exec -T db \
     psql -U investing_prod -d investing_companion
   ```

5. **Verify restoration:**
   ```bash
   # Check API health
   curl http://localhost:8000/health?detailed=true

   # Check data exists (should return your watchlists)
   curl http://localhost:8000/api/v1/watchlists/
   ```

### Restore Environment Configuration

If `.env.production` is lost:

1. Copy from your secure backup location
2. Or recreate from `.env.production.example`:
   ```bash
   cp .env.production.example .env.production
   # Edit with your values
   nano .env.production
   ```

**Required values to restore:**
- `POSTGRES_USER`, `POSTGRES_PASSWORD` - must match what's in the database
- `SECRET_KEY` - if changed, all existing sessions will be invalidated
- `POSTGRES_PORT=5433` - required for Synology

---

## Disaster Recovery Checklist

### If Database Container Won't Start

1. Check logs: `docker-compose --env-file .env.production logs db`
2. Check disk space: `df -h`
3. Check if native PostgreSQL is blocking port: `netstat -tlnp | grep 5432`
4. Verify `POSTGRES_PORT=5433` is set in `.env.production`

### If Data Appears Missing

1. **Don't panic** - check if it's a connection issue first
2. Verify database container is running: `docker-compose ps db`
3. Check if volume exists: `docker volume ls | grep postgres`
4. If volume exists, data should be intact
5. If volume is gone, restore from backup (see above)

### If Secrets Are Compromised

1. Generate new `SECRET_KEY`:
   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```
2. Update `.env.production` with new key
3. Restart API: `docker-compose --env-file .env.production restart api`
4. All users will need to log in again

### If You Need to Move to a New Server

1. **Backup everything:**
   ```bash
   # Database
   ./scripts/backup.sh

   # Download backup and config
   scp synology:/volume3/docker/investing_companion/backups/latest.sql.gz ./
   scp synology:/volume3/docker/investing_companion/.env.production ./
   ```

2. **On new server:**
   ```bash
   # Clone repo
   git clone <repo-url> investing_companion
   cd investing_companion

   # Copy config
   cp /path/to/.env.production .

   # Start services
   docker-compose --env-file .env.production up -d

   # Wait for db, run migrations
   docker-compose --env-file .env.production exec api alembic upgrade head

   # Restore data
   gunzip -c /path/to/backup.sql.gz | \
     docker-compose --env-file .env.production exec -T db \
     psql -U investing_prod -d investing_companion
   ```

---

## Testing Backups

**Important:** Regularly test that backups can be restored!

### Monthly Backup Test Procedure

1. Create a fresh backup
2. Stop all services
3. Delete the database volume (on test system only!)
4. Restore from backup
5. Verify application works
6. Document results

```bash
# On a TEST system only!
docker-compose --env-file .env.production down -v
docker-compose --env-file .env.production up -d
sleep 10
docker-compose --env-file .env.production exec api alembic upgrade head
gunzip -c backups/latest.sql.gz | docker-compose --env-file .env.production exec -T db psql -U investing_prod -d investing_companion
curl http://localhost:8000/health?detailed=true
```

---

## Backup Storage Recommendations

1. **On-NAS backups** (`/volume3/docker/investing_companion/backups/`) - for quick recovery
2. **Off-NAS copy** - sync to cloud storage or external drive monthly
3. **Environment secrets** - store in password manager, never in git

### Syncing to Cloud (Optional)

If using Synology Cloud Sync:
1. Create a sync task for the `backups/` folder
2. Encrypt the sync for security
3. Verify files appear in cloud storage

---

## Related Documentation

- [Synology Deployment Guide](./SYNOLOGY.md)
- [Architecture Overview](../architecture/OVERVIEW.md)
