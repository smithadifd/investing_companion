---
title: Synology NAS deployment
description: Deploy Investing Companion on a Synology NAS behind an external reverse proxy using docker-compose.local.yml.
---

This page covers the NAS-specific path: using `docker-compose.local.yml` to run Investing Companion on a Synology NAS behind an external reverse proxy (Caddy, Nginx, or similar running on a separate machine). If you want the self-contained stack with Traefik and Let's Encrypt built in, see [Quick start](/running/quick-start/) instead.

## Prerequisites

**Hardware:** 2+ CPU cores, 4 GB RAM recommended (2 GB minimum), 10 GB free on the target volume for the app, database, and data growth.

**Synology software:** Container Manager (DSM 7.2+) or the legacy Docker package. Either works. SSH access is optional but makes the deploy steps faster.

**On your NAS:** Docker Engine 20.10 or newer. Check with `docker --version` over SSH.

**An external reverse proxy** that can route traffic to the NAS by IP and port. The app itself does not terminate TLS — your proxy handles that.

## Which compose file to use

`docker-compose.local.yml` is the right file for NAS deployment. It strips out Traefik and exposes two ports directly:

- `8000` — the FastAPI backend
- `3000` — the Next.js frontend

Your reverse proxy sits in front of both. The root `docker-compose.yml` is for local development only (includes hot-reload, dev tooling). `docker-compose.prod.yml` bundles Traefik with Let's Encrypt and is meant for a VPS with a public domain — not what you want on a LAN.

## Environment configuration

Copy `.env.example` to `.env.production` and fill in your values. The variables that matter most for a NAS deployment:

```env
# Database
POSTGRES_USER=investing
POSTGRES_PASSWORD=a-strong-random-password
POSTGRES_DB=investing_companion

# Application
SECRET_KEY=your-secret-key-here
ENVIRONMENT=production

# Set this to the origin your browser hits — your proxy's URL
CORS_ORIGINS=https://invest.home

# Optional
DISCORD_WEBHOOK_URL=
ALPHA_VANTAGE_API_KEY=
FINNHUB_API_KEY=
CLAUDE_API_KEY=
```

Generate `SECRET_KEY` with:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

`CORS_ORIGINS` must match the origin your browser uses to reach the app. If Caddy serves it at `https://invest.home`, set it to exactly that. A mismatch here causes the frontend to get blocked by the API's CORS policy.

`NEXT_PUBLIC_API_URL` defaults to `/api/v1` inside the compose file (baked into the frontend build), so the frontend calls the API through a relative path. You do not need to set this unless you change the routing.

## Reverse proxy setup

The compose file does not include a proxy service. You point your external proxy (Caddy, Nginx, etc.) at the NAS IP on port `3000` for the frontend and at port `8000` for the API, or you proxy everything through port `3000` and let the frontend proxy API requests.

Because `NEXT_PUBLIC_API_URL` is set to `/api/v1` at build time, API requests from the browser go to the same origin as the frontend — meaning a single proxy entry pointing at `nas-ip:3000` is usually enough. The API on port `8000` only needs to be reachable from inside the Docker network and from the NAS host itself (for `docker exec` commands).

Do not expose port `5432` (PostgreSQL) or `6379` (Redis) outside the Docker network. Neither service has a port binding in `docker-compose.local.yml`.

## First deploy

SSH into your NAS or use the terminal in Container Manager.

```bash
# Set PATH if docker commands aren't found
export PATH=/usr/local/bin:/usr/syno.bin:$PATH

cd /volume3/docker/investing_companion

# Pull latest code if you cloned from git
git pull origin main

# Build and start all services
docker-compose -f docker-compose.local.yml --env-file .env.production up -d --build
```

Wait for the database healthcheck to pass, then run migrations:

```bash
docker exec investing_api alembic upgrade head
```

Seed the initial data (financial ratios, macro events calendar):

```bash
docker exec investing_api python -m scripts.seed_demo_data
```

Create your user account by navigating to the frontend URL and registering. Once your account exists, lock down registration:

```env
# In .env.production
REGISTRATION_ENABLED=false
```

Then restart the API service:

```bash
docker-compose -f docker-compose.local.yml --env-file .env.production up -d api
```

## Upgrading

From your local machine, run the deploy script if you have it set up:

```bash
./scripts/deploy-synology.sh
```

That script runs a local build test, pushes to GitHub, pulls on the NAS, and rebuilds. For a manual upgrade:

```bash
# On the NAS
cd /volume3/docker/investing_companion
git pull origin main
docker-compose -f docker-compose.local.yml --env-file .env.production up -d --build
docker exec investing_api alembic upgrade head
```

Check logs after a restart:

```bash
docker-compose -f docker-compose.local.yml logs -f api
```

## Synology quirks

**Docker CLI path.** On DSM, `docker` and `docker-compose` may not be in `$PATH` when you SSH in. Prefix commands with the full path or export it first:

```bash
export PATH=/usr/local/bin:/usr/syno/bin:$PATH
```

**docker-compose v1 vs v2.** Synology NAS units running older DSM ship docker-compose v1 (`docker-compose` command). The `docker compose` plugin (v2, no hyphen) may not be available. Use `docker-compose` with the hyphen on the NAS. On your Mac or a newer Docker install, either works.

**Volume permissions.** Named volumes (`investing_postgres_data`, `investing_redis_data`) are managed by Docker and don't require manual `chown`. If you switch to bind mounts pointing at a Synology shared folder, you may need `chmod 777` on the host path — Synology doesn't give passwordless sudo, so you'll need to set permissions before the container starts.

**Memory limits.** If the NAS is under memory pressure, reduce the Celery worker concurrency. Edit the `command` line in `docker-compose.local.yml`:

```yaml
command: ["celery", "-A", "app.tasks.celery_app", "worker", "--loglevel=info", "--concurrency=1"]
```

The compose file does not include `deploy.resources.limits` blocks, so Docker will use whatever memory is available by default.
