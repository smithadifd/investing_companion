# Synology NAS Deployment Guide

This guide documents the deployment of Investing Companion to a Synology NAS.

---

## Connection Information

First, configure your SSH connection details. Add to `~/.ssh/config`:
```
Host synology
    HostName <your-nas-ip>
    Port <your-ssh-port>
    User <your-ssh-user>
```

Then connect with:
```bash
ssh synology
```

**Paths on Synology:**
- Application: `/volume3/docker/investing_companion/`
- Docker volumes: Managed by Docker (use `docker volume ls` to see)

**Important:** Git is not in the default PATH on Synology. Either use the full path or export:
```bash
export PATH=/usr/local/bin:$PATH
```

---

## Architecture

### Services

| Service | Type | Port | Notes |
|---------|------|------|-------|
| PostgreSQL | Docker | 5433 (external) | TimescaleDB, uses port 5433 to avoid conflict with native Synology PostgreSQL on 5432 |
| Redis | Docker | 6379 | Cache and Celery broker |
| API (FastAPI) | Docker | 8000 | Backend REST API |
| Frontend (Next.js) | Docker | 3000 | Web UI |
| Celery Worker | Docker | - | Background task processing |
| Celery Beat | Docker | - | Scheduled task scheduler |

### Port Conflicts

Synology runs native PostgreSQL on `127.0.0.1:5432`. Our Docker PostgreSQL uses port **5433** to avoid conflicts. This is configured via `POSTGRES_PORT=5433` in `.env.production`.

---

## Environment Configuration

The production environment file (`.env.production`) lives **only on the Synology** and is **never committed to git**.

### Required Variables

```bash
# Database (port 5433 to avoid native PostgreSQL conflict)
POSTGRES_USER=investing_prod
POSTGRES_PASSWORD=<secure-password>
POSTGRES_DB=investing_companion
POSTGRES_PORT=5433

# Security
SECRET_KEY=<generated-secret>

# CORS (must include the Synology IP/port)
CORS_ORIGINS=http://<your-nas-ip>:3000,http://localhost:3000

# Frontend API URL (what the browser uses)
NEXT_PUBLIC_API_URL=http://<your-nas-ip>:8000/api/v1

# Environment
ENVIRONMENT=production
```

### Optional Variables

```bash
DISCORD_WEBHOOK_URL=<webhook-url>
ALPHA_VANTAGE_API_KEY=<api-key>
POLYGON_API_KEY=<api-key>
CLAUDE_API_KEY=<api-key>
```

---

## Deployment Commands

### Initial Deployment

```bash
# SSH to Synology
ssh synology

# Navigate to app directory
cd /volume3/docker/investing_companion

# Ensure git is available
export PATH=/usr/local/bin:$PATH

# Pull latest code
git pull origin main

# Start all services
docker-compose --env-file .env.production up -d --build

# Run database migrations
docker-compose --env-file .env.production exec api alembic upgrade head

# Check status
docker-compose --env-file .env.production ps
```

### Updating the Deployment

```bash
ssh synology
cd /volume3/docker/investing_companion
export PATH=/usr/local/bin:$PATH

# Pull changes
git pull origin main

# Rebuild and restart (preserves volumes/data)
docker-compose --env-file .env.production up -d --build

# Run any new migrations
docker-compose --env-file .env.production exec api alembic upgrade head
```

### Stopping Services

```bash
# Stop all services (preserves data)
docker-compose --env-file .env.production down

# Stop and remove volumes (DESTROYS DATA - use with caution!)
docker-compose --env-file .env.production down -v
```

---

## Health Checks

### Quick Status Check

```bash
# Container status
docker-compose --env-file .env.production ps

# API health
curl http://localhost:8000/health

# Detailed API health
curl http://localhost:8000/health?detailed=true

# Database connection test
docker-compose --env-file .env.production exec db psql -U investing_prod -d investing_companion -c "SELECT 1;"
```

### Viewing Logs

```bash
# All services
docker-compose --env-file .env.production logs -f

# Specific service
docker-compose --env-file .env.production logs -f api
docker-compose --env-file .env.production logs -f frontend
docker-compose --env-file .env.production logs -f db
docker-compose --env-file .env.production logs -f celery_worker
```

---

## Troubleshooting

### Container Won't Start

1. **Check logs:**
   ```bash
   docker-compose --env-file .env.production logs <service-name>
   ```

2. **Check port conflicts:**
   ```bash
   netstat -tlnp | grep <port>
   ```

3. **Check disk space:**
   ```bash
   df -h
   ```

### Database Connection Issues

1. **Verify database is running:**
   ```bash
   docker-compose --env-file .env.production ps db
   ```

2. **Check database logs:**
   ```bash
   docker-compose --env-file .env.production logs db
   ```

3. **Test connection from API container:**
   ```bash
   docker-compose --env-file .env.production exec api python -c "from app.db.session import engine; print('OK')"
   ```

### CORS Errors in Browser

Ensure `CORS_ORIGINS` in `.env.production` includes the URL you're accessing the frontend from:
```bash
CORS_ORIGINS=http://<your-nas-ip>:3000,http://localhost:3000
```

After changing, restart the API:
```bash
docker-compose --env-file .env.production restart api
```

### Permission Errors

The celery and frontend containers run as root to avoid permission issues with Synology's volume mounts. If you see permission errors:

1. Check the `user: root` directive is present in `docker-compose.yml` for affected services
2. Verify volume mount paths exist and are accessible

### Database Data Loss After Restart

**Prevention:** Never use `docker-compose down -v` unless you intend to destroy data.

**If data is lost:** See [BACKUP.md](./BACKUP.md) for restore procedures.

---

## Access URLs

| Service | Internal (from Synology) | External (from LAN) |
|---------|-------------------------|---------------------|
| Frontend | http://localhost:3000 | http://&lt;your-nas-ip&gt;:3000 |
| API | http://localhost:8000 | http://&lt;your-nas-ip&gt;:8000 |
| API Docs | http://localhost:8000/docs | http://&lt;your-nas-ip&gt;:8000/docs |

---

## Security Notes

1. **Never commit `.env.production`** - it contains secrets
2. **Change default passwords** before first deployment
3. **The application is only accessible on the local network** unless you configure port forwarding
4. **Registration is disabled by default** (`REGISTRATION_ENABLED=false`)

---

## Related Documentation

- [Backup & Restore Procedures](./BACKUP.md)
- [Architecture Overview](../architecture/OVERVIEW.md)
- [Development Setup](../../README.md)
