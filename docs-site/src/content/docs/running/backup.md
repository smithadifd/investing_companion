---
title: Backup and restore
description: How to back up the Investing Companion Postgres database, verify the backup, and restore it when something goes wrong.
---

Investing Companion stores everything that matters in Postgres: user accounts, watchlists, trades, alerts, custom ratios, and economic events. Redis holds only ephemeral cache data — price lookups, AI response cache — and is not worth backing up. If Redis is empty after a restart, it refills itself.

There is no automated backup task in the app itself. Celery Beat handles alert checks and event refresh, but backup is left to the OS scheduler. Run `scripts/backup.sh` on a cron or via Synology Task Scheduler.

## What the backup contains

`scripts/backup.sh` calls `pg_dump` inside the `investing_db` container and compresses the output with `gzip`. The resulting `.sql.gz` file contains the full logical dump of the `investing_companion` database: all tables, sequences, and data.

Not included (safe to skip):

- Redis cache
- Price history (re-fetched from Yahoo Finance on demand)
- AI response cache

## Run a manual backup

From the project root:

```bash
# Default output: ./backups/
./scripts/backup.sh

# Custom output directory (e.g., a Synology share)
./scripts/backup.sh /volume1/backups/investing
```

The script reads `POSTGRES_USER` and `POSTGRES_DB` from `.env.production` if that file is present, falling back to `investing_prod` and `investing_companion`. It checks that the `investing_db` container is running, runs the dump, verifies the gzip with `gunzip -t`, then deletes files matching `investing_companion_*.sql.gz` that are older than `RETENTION_DAYS` (default: 30).

Output files are named `investing_companion_YYYYMMDD_HHMMSS.sql.gz`.

## Schedule automated backups

### Synology Task Scheduler

1. Open **Control Panel → Task Scheduler**.
2. Create → Scheduled Task → User-defined script.
3. Set the run command:

```bash
cd /volume1/docker/investing_companion && ./scripts/backup.sh /volume1/backups/investing >> /var/log/investing_backup.log 2>&1
```

4. Schedule daily, 2 AM is a reasonable default.

See [Synology deployment](/running/synology/) for notes on the Docker path and `PATH` export requirements on the NAS.

### Cron (SSH)

```bash
crontab -e
```

```text
0 2 * * * cd /volume1/docker/investing_companion && ./scripts/backup.sh /volume1/backups/investing >> /var/log/investing_backup.log 2>&1
```

## Retention

The default retention is 30 days. Change it by editing `RETENTION_DAYS` at the top of `scripts/backup.sh`:

```bash
RETENTION_DAYS=30  # Change to desired number of days
```

## Restore

Restoring drops and recreates the database. Take a fresh backup first.

### Using the restore script

```bash
# 1. Stop the app services (leave the db container running)
docker compose -f docker-compose.prod.yml stop api celery_worker celery_beat frontend

# 2. Run the restore script
./scripts/restore.sh /path/to/backup.sql.gz
```

The script verifies the backup file with `gunzip -t`, then prompts you to type `RESTORE` to confirm. After confirmation it:

1. Drops the existing database inside `investing_db`
1. Creates a fresh empty database with the same name
1. Pipes the decompressed dump into `psql`

Then restart everything:

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production up -d
```

Check the health endpoint once services are up:

```bash
curl https://your-domain.com/health?detailed=true
```

### Manual restore (if the script fails)

```bash
docker compose -f docker-compose.prod.yml stop api celery_worker celery_beat

docker exec investing_db psql -U investing_prod -d postgres -c "DROP DATABASE IF EXISTS investing_companion;"
docker exec investing_db psql -U investing_prod -d postgres -c "CREATE DATABASE investing_companion;"

gunzip -c /path/to/backup.sql.gz | docker exec -i investing_db psql -U investing_prod -d investing_companion

docker compose -f docker-compose.prod.yml --env-file .env.production up -d
```

`investing_prod` and `investing_companion` are the defaults; substitute actual values from `POSTGRES_USER` and `POSTGRES_DB` in your `.env.production`. See [Configuration](/running/configuration/) for variable reference.

## Test a restore (do this monthly)

A backup you have never tested is a guess. Spin up a throwaway container and restore into it:

```bash
# 1. Start a test Postgres container
docker run -d --name test_restore \
  -e POSTGRES_USER=test \
  -e POSTGRES_PASSWORD=test \
  -e POSTGRES_DB=test_restore \
  timescale/timescaledb:latest-pg15

# 2. Restore the backup
gunzip -c /path/to/backup.sql.gz | docker exec -i test_restore psql -U test -d test_restore

# 3. Spot-check row counts
docker exec test_restore psql -U test -d test_restore -c "SELECT COUNT(*) FROM users;"
docker exec test_restore psql -U test -d test_restore -c "SELECT COUNT(*) FROM trades;"

# 4. Clean up
docker stop test_restore && docker rm test_restore
```

This does not touch your live database at all. Run it against the previous night's backup.

## Troubleshooting

**"Container not running"** — the `investing_db` container must be up for both backup and restore. Start it with:

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production up -d db
```

**"Permission denied"** — the scripts may lack execute permission after a fresh clone:

```bash
chmod +x scripts/backup.sh scripts/restore.sh
```

**Corrupt backup** — test with `gunzip -t backup.sql.gz`. If it fails, use the previous backup and check available disk space during the time the backup ran.

**Restore hangs** — large dumps take time. Watch progress via:

```bash
docker logs -f investing_db
```

## Off-site copies

Local backups on the NAS do not protect against NAS failure. Use Synology Hyper Backup to replicate `/volume1/backups/investing` to a cloud destination or remote NAS after each local backup completes. Alternatively, `rsync` or `rclone` work fine over SSH or S3-compatible targets.
