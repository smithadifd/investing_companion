# Investing Companion - Deployment Guide

This guide covers deploying Investing Companion on a Synology NAS or similar Docker-capable home server.

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Quick Start](#quick-start)
3. [Synology-Specific Setup](#synology-specific-setup)
4. [Configuration](#configuration)
5. [SSL/HTTPS Setup](#sslhttps-setup)
6. [Database Seeding](#database-seeding)
7. [Monitoring](#monitoring)
8. [Maintenance](#maintenance)
9. [Troubleshooting](#troubleshooting)

---

## Prerequisites

### Hardware Requirements

- **CPU**: 2+ cores recommended
- **RAM**: 2GB minimum, 4GB recommended
- **Storage**: 10GB minimum for application + data growth

### Software Requirements

- Docker Engine 20.10+
- Docker Compose v2.0+
- Domain name (for HTTPS/Let's Encrypt)

### Network Requirements

- Ports 80 and 443 accessible from the internet (for Let's Encrypt)
- DNS A record pointing to your server's public IP

---

## Quick Start

### 1. Clone the Repository

```bash
git clone https://github.com/yourusername/investing_companion.git
cd investing_companion
```

### 2. Create Production Environment File

```bash
cp .env.production.example .env.production
```

### 3. Configure Required Settings

Edit `.env.production`:

```bash
# REQUIRED - Change these values
DOMAIN=invest.yourdomain.com
ACME_EMAIL=your-email@example.com
SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
POSTGRES_PASSWORD=$(openssl rand -base64 24)
```

### 4. Deploy

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production up -d
```

### 5. Seed Initial Data

```bash
docker exec investing_api python -m scripts.seed_demo_data
```

### 6. Create Your User Account

Before disabling registration, create your admin account:

```bash
# With registration enabled (default)
# Navigate to https://your-domain.com and register
# OR via API:
curl -X POST https://your-domain.com/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email": "you@email.com", "password": "your-secure-password"}'
```

Then disable registration in `.env.production`:

```bash
REGISTRATION_ENABLED=false
```

And restart the API:

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production up -d api
```

---

## Synology-Specific Setup

### Using Synology Container Manager

1. **Install Container Manager** from Package Center

2. **Create Project**
   - Open Container Manager → Project
   - Create new project from compose file
   - Upload `docker-compose.prod.yml`
   - Add environment variables from `.env.production`

3. **Configure Resources**
   - Set memory limits appropriate for your NAS
   - Recommended: 512MB API, 256MB each Celery worker

### Using SSH/Terminal

1. **Enable SSH** on your Synology (Control Panel → Terminal & SNMP)

2. **SSH into your NAS**:
```bash
ssh admin@your-nas-ip
```

3. **Navigate to docker folder**:
```bash
cd /volume1/docker/investing_companion
```

4. **Deploy**:
```bash
sudo docker compose -f docker-compose.prod.yml --env-file .env.production up -d
```

### Port Forwarding

Configure your router to forward:
- Port 80 → Synology IP:80
- Port 443 → Synology IP:443

---

## Configuration

### Required Environment Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `DOMAIN` | Your domain name | `invest.example.com` |
| `ACME_EMAIL` | Email for Let's Encrypt | `admin@example.com` |
| `SECRET_KEY` | JWT signing key (32+ chars) | Use `secrets.token_urlsafe(32)` |
| `POSTGRES_PASSWORD` | Database password | Use strong random password |

### Optional Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `REGISTRATION_ENABLED` | `false` | Allow new user registration |
| `DISCORD_WEBHOOK_URL` | ` ` | Discord notifications for alerts |
| `CLAUDE_API_KEY` | ` ` | Fallback Claude API key |
| `ALPHA_VANTAGE_API_KEY` | ` ` | Additional market data |

### Generating Secure Keys

```bash
# Generate SECRET_KEY
python3 -c "import secrets; print(secrets.token_urlsafe(32))"

# Generate POSTGRES_PASSWORD
openssl rand -base64 24
```

---

## SSL/HTTPS Setup

### Automatic (Let's Encrypt via Traefik)

The production docker-compose includes Traefik configured for automatic Let's Encrypt certificates.

**Requirements:**
1. Domain DNS pointing to your server
2. Ports 80 and 443 open to the internet
3. Valid `DOMAIN` and `ACME_EMAIL` in environment

Certificates are automatically obtained and renewed.

### Manual Certificate

If you have existing certificates, mount them:

```yaml
# In docker-compose.prod.yml, add to traefik service:
volumes:
  - /path/to/cert.pem:/certs/cert.pem:ro
  - /path/to/key.pem:/certs/key.pem:ro
```

And configure Traefik to use them instead of Let's Encrypt.

### Troubleshooting Let's Encrypt

```bash
# Check Traefik logs
docker logs investing_traefik

# Verify DNS resolution
dig +short your-domain.com

# Test port accessibility
curl -I http://your-domain.com
```

---

## Database Seeding

### Initial Seed

After first deployment, seed the database with default data:

```bash
docker exec investing_api python -m scripts.seed_demo_data
```

This creates:
- Default financial ratios (Gold/Silver, SPY/QQQ, etc.)
- Macro economic events calendar (FOMC, CPI, NFP, GDP)

### Seed Specific Data

```bash
# Ratios only
docker exec investing_api python -m scripts.seed_demo_data --ratios

# Events only (specific year)
docker exec investing_api python -m scripts.seed_demo_data --events --year 2026
```

---

## Monitoring

### Health Endpoint

Basic health check:
```bash
curl https://your-domain.com/health
```

Detailed health check (includes DB/Redis status):
```bash
curl https://your-domain.com/health?detailed=true
```

### Uptime Kuma Integration

1. Add new monitor in Uptime Kuma
2. Type: HTTP(s)
3. URL: `https://your-domain.com/health`
4. Expected status: 200

### Container Logs

```bash
# All services
docker compose -f docker-compose.prod.yml logs -f

# Specific service
docker compose -f docker-compose.prod.yml logs -f api

# Last 100 lines
docker compose -f docker-compose.prod.yml logs --tail 100 api
```

---

## Maintenance

### Backups

**Manual Backup:**
```bash
./scripts/backup.sh ./backups
```

**Automated Backups (Synology Task Scheduler):**

1. Control Panel → Task Scheduler
2. Create → Scheduled Task → User-defined script
3. Schedule: Daily at 2:00 AM
4. Script:
```bash
cd /volume1/docker/investing_companion
./scripts/backup.sh /volume1/backups/investing
```

**Restore from Backup:**
```bash
./scripts/restore.sh /path/to/backup.sql.gz
```

### Updates

1. **Stop services:**
```bash
docker compose -f docker-compose.prod.yml --env-file .env.production down
```

2. **Pull latest code:**
```bash
git pull origin main
```

3. **Rebuild and restart:**
```bash
docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build
```

4. **Run migrations (if any):**
```bash
docker compose -f docker-compose.prod.yml --env-file .env.production up migrate
```

### Database Migrations

Migrations run automatically on startup via the `migrate` service. For manual migration:

```bash
docker exec investing_api alembic upgrade head
```

---

## Troubleshooting

### Container Won't Start

```bash
# Check logs
docker compose -f docker-compose.prod.yml logs api

# Common issues:
# - SECRET_KEY too short or using default
# - Database credentials mismatch
# - Port already in use
```

### Database Connection Failed

```bash
# Check database is running
docker ps | grep investing_db

# Check database logs
docker logs investing_db

# Test connection
docker exec investing_db pg_isready -U investing_prod
```

### Let's Encrypt Certificate Fails

1. Verify DNS is correct: `dig +short your-domain.com`
2. Verify ports 80/443 are accessible from internet
3. Check Traefik logs: `docker logs investing_traefik`
4. Ensure no firewall blocking ports

### API Returns 401 Unauthorized

1. Token may have expired - refresh or re-login
2. Check if user account exists
3. Verify SECRET_KEY hasn't changed

### Redis Connection Refused

```bash
# Check Redis is running
docker logs investing_redis

# Test Redis
docker exec investing_redis redis-cli ping
```

### Memory Issues on Synology

Reduce resource limits in docker-compose.prod.yml:

```yaml
deploy:
  resources:
    limits:
      memory: 256M  # Reduce from 512M
```

---

## Security Checklist

Before going live, verify:

- [ ] `SECRET_KEY` is unique and secure (32+ characters)
- [ ] `POSTGRES_PASSWORD` is strong
- [ ] `REGISTRATION_ENABLED=false` (after creating your account)
- [ ] `.env.production` is not in git (check `.gitignore`)
- [ ] HTTPS is working correctly
- [ ] Firewall only allows 80/443 from internet
- [ ] Database is not exposed to internet (no port mapping)
- [ ] Automatic backups are configured

---

## Architecture Overview

```
Internet
    │
    ▼
┌─────────────────┐
│     Traefik     │ ← HTTPS termination, Let's Encrypt
│   (Port 80/443) │
└────────┬────────┘
         │
    ┌────┴────┐
    │         │
    ▼         ▼
┌───────┐ ┌──────────┐
│  API  │ │ Frontend │
│ :8000 │ │  :3000   │
└───┬───┘ └──────────┘
    │
    ├───────────────┐
    │               │
    ▼               ▼
┌───────┐     ┌─────────┐
│  DB   │     │  Redis  │
│ :5432 │     │  :6379  │
└───────┘     └────┬────┘
                   │
              ┌────┴────┐
              │         │
              ▼         ▼
         ┌────────┐ ┌────────┐
         │ Worker │ │  Beat  │
         │(Celery)│ │(Celery)│
         └────────┘ └────────┘
```

---

## Support

For issues:
1. Check this troubleshooting guide
2. Search existing GitHub issues
3. Create a new issue with logs and configuration (redact secrets!)
