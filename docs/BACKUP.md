# Investing Companion - Backup & Restore Guide

## Overview

This guide covers backup and restore procedures for the Investing Companion application.

## What Gets Backed Up

The backup script (`scripts/backup.sh`) creates PostgreSQL dumps containing:

- User accounts and settings
- Watchlists and watchlist items
- Trades and trade history
- Alerts and alert history
- Custom ratios
- Economic events

**Not backed up** (can be regenerated):
- Redis cache data
- Price history (fetched from Yahoo Finance)
- AI response cache

---

## Backup Procedures

### Manual Backup

```bash
cd /path/to/investing_companion

# Backup to default ./backups directory
./scripts/backup.sh

# Backup to custom location
./scripts/backup.sh /volume1/backups/investing
```

Output:
```
========================================
Investing Companion Backup
Started: Sat Feb  1 14:30:00 PST 2026
========================================
Creating backup: investing_companion_20260201_143000.sql.gz
Backup created: ./backups/investing_companion_20260201_143000.sql.gz (2.5M)
Backup integrity verified
Cleaning up backups older than 30 days...
Deleted 0 old backup(s)

Backup Summary:
  - Total backups: 7
  - Total size: 17M
  - Latest backup: investing_companion_20260201_143000.sql.gz

Backup completed successfully at Sat Feb  1 14:30:05 PST 2026
========================================
```

### Automated Backups (Synology)

#### Using Task Scheduler

1. Open **Control Panel → Task Scheduler**
2. Click **Create → Scheduled Task → User-defined script**
3. Configure:
   - **General**: Name it "Investing Companion Backup"
   - **Schedule**: Daily at 2:00 AM (or your preference)
   - **Task Settings**:
     - Run command:
       ```bash
       cd /volume1/docker/investing_companion && ./scripts/backup.sh /volume1/backups/investing
       ```
     - Send run details by email (optional)

#### Using Cron (SSH)

```bash
# Edit crontab
crontab -e

# Add daily backup at 2 AM
0 2 * * * cd /volume1/docker/investing_companion && ./scripts/backup.sh /volume1/backups/investing >> /var/log/investing_backup.log 2>&1
```

### Backup Retention

By default, backups older than 30 days are automatically deleted. To change:

```bash
# Edit scripts/backup.sh
RETENTION_DAYS=30  # Change to desired number
```

---

## Restore Procedures

### Before Restoring

⚠️ **Warning**: Restoring will **DELETE ALL EXISTING DATA**!

1. **Create a fresh backup first** (in case you need to roll back)
2. Stop application services to prevent data corruption

### Restore Steps

1. **Stop application services**:
   ```bash
   docker compose -f docker-compose.prod.yml stop api celery_worker celery_beat frontend
   ```

2. **Run restore script**:
   ```bash
   ./scripts/restore.sh /path/to/backup.sql.gz
   ```

3. **Confirm restore** by typing `RESTORE` when prompted

4. **Restart services**:
   ```bash
   docker compose -f docker-compose.prod.yml --env-file .env.production up -d
   ```

5. **Verify restoration**:
   ```bash
   curl https://your-domain.com/health?detailed=true
   ```

### Manual Restore

If the restore script doesn't work:

```bash
# Stop services
docker compose -f docker-compose.prod.yml stop api celery_worker celery_beat

# Drop and recreate database
docker exec investing_db psql -U investing_prod -d postgres -c "DROP DATABASE IF EXISTS investing_companion;"
docker exec investing_db psql -U investing_prod -d postgres -c "CREATE DATABASE investing_companion;"

# Restore from backup
gunzip -c /path/to/backup.sql.gz | docker exec -i investing_db psql -U investing_prod -d investing_companion

# Restart services
docker compose -f docker-compose.prod.yml --env-file .env.production up -d
```

---

## Backup Verification

### Test Restore (Recommended Monthly)

1. Spin up a test database container:
   ```bash
   docker run -d --name test_restore \
     -e POSTGRES_USER=test \
     -e POSTGRES_PASSWORD=test \
     -e POSTGRES_DB=test_restore \
     timescale/timescaledb:latest-pg15
   ```

2. Restore to test database:
   ```bash
   gunzip -c /path/to/backup.sql.gz | docker exec -i test_restore psql -U test -d test_restore
   ```

3. Verify data:
   ```bash
   docker exec test_restore psql -U test -d test_restore -c "SELECT COUNT(*) FROM users;"
   docker exec test_restore psql -U test -d test_restore -c "SELECT COUNT(*) FROM trades;"
   ```

4. Cleanup:
   ```bash
   docker stop test_restore && docker rm test_restore
   ```

---

## Disaster Recovery

### Complete System Loss

If you lose everything and need to recover:

1. **Set up fresh installation** following DEPLOYMENT.md

2. **Restore database** from backup:
   ```bash
   ./scripts/restore.sh /path/to/backup.sql.gz
   ```

3. **Re-seed macro events** (they may have expired):
   ```bash
   docker exec investing_api python -m scripts.seed_demo_data --events
   ```

4. **Verify user login works**

5. **Reconfigure integrations**:
   - Discord webhook URL
   - Claude API key
   - Other API keys in settings

### Partial Data Loss

If only some data is corrupted:

1. **Export specific tables** from backup:
   ```bash
   gunzip -c backup.sql.gz | grep -A 1000 "COPY trades" > trades_data.sql
   ```

2. **Import specific tables**:
   ```bash
   docker exec -i investing_db psql -U investing_prod -d investing_companion < trades_data.sql
   ```

---

## Off-Site Backups

### Synology Hyper Backup

1. Open **Hyper Backup**
2. Create backup task
3. Select backup folder (e.g., `/volume1/backups/investing`)
4. Choose destination (cloud, remote NAS, USB)
5. Schedule to run after local backup completes

### Manual Off-Site Copy

```bash
# Copy to external drive
cp -r /volume1/backups/investing /volumeUSB1/usbshare/backups/

# Sync to remote server
rsync -avz /volume1/backups/investing user@remote:/backups/

# Upload to cloud (rclone)
rclone copy /volume1/backups/investing remote:backups/investing
```

---

## Troubleshooting

### "Container not running"

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production up -d db
# Wait for healthy status
docker compose -f docker-compose.prod.yml ps db
```

### "Permission denied"

```bash
chmod +x scripts/backup.sh scripts/restore.sh
```

### Backup is corrupt

If `gunzip -t backup.sql.gz` fails:
- Try previous backup
- Check disk space during backup time
- Verify no container restart during backup

### Restore hangs

Large databases may take time. Monitor with:
```bash
docker logs -f investing_db
```

---

## Best Practices

1. **Test restores regularly** - A backup you can't restore is worthless
2. **Keep multiple backups** - Don't just keep the latest
3. **Store off-site** - Local backups don't help if the NAS fails
4. **Monitor backup success** - Check logs, set up alerts
5. **Document your process** - Know exactly how to restore in an emergency
