---
title: Configuration reference
description: Every environment variable Investing Companion reads, with defaults and notes on required vs optional.
---

Configuration is loaded by a Pydantic `Settings` object in `backend/app/core/config.py`. Values are read from the process environment first, then from a `.env` file in the project root. Copy `.env.example` to `.env` and fill in your values before starting the stack.

There is no `.env.local` layer — if you need environment-specific overrides, pass them directly in `docker-compose.prod.yml` or your shell.

---

## Application

| Variable | Required | Default | Purpose |
| --- | --- | --- | --- |
| `SECRET_KEY` | Yes (prod) | `dev-secret-key-change-in-production` | Signs JWT tokens. Must be 32+ characters and unique per deployment. |
| `ENVIRONMENT` | No | `development` | Runtime context. Set to `production` to enable startup validation of secrets and CORS. |
| `CORS_ORIGINS` | No | `http://localhost:3000,http://localhost:3001` | Comma-separated list of origins the API allows. Wildcards are rejected in production. |
| `REGISTRATION_ENABLED` | No | `true` | Set to `false` after creating your account to prevent new signups. |

When `ENVIRONMENT=production`, the app exits at startup if `SECRET_KEY` is a known insecure value, is shorter than 32 characters, or if `CORS_ORIGINS` contains `*`.

Generate a secure key with:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

---

## Database

| Variable | Required | Default | Purpose |
| --- | --- | --- | --- |
| `DATABASE_URL` | No | `postgresql+asyncpg://investing:investing_dev@localhost:5432/investing_companion` | Full async SQLAlchemy connection string. |
| `POSTGRES_USER` | No | — | Used by the Postgres Docker service to create the database user. Not read by the API directly. |
| `POSTGRES_PASSWORD` | No | — | Used by the Postgres Docker service. Set this to match the credentials in `DATABASE_URL`. |
| `POSTGRES_DB` | No | — | Database name for the Postgres Docker service. |

`POSTGRES_USER`, `POSTGRES_PASSWORD`, and `POSTGRES_DB` are Docker Compose variables consumed by the `postgres` container image, not by the Python application. The API reads only `DATABASE_URL`. Keep the credentials in `DATABASE_URL` in sync with these three values.

---

## Redis

| Variable | Required | Default | Purpose |
| --- | --- | --- | --- |
| `REDIS_URL` | No | `redis://localhost:6379/0` | Connection string for the Redis instance used as a cache and Celery broker/result backend. |

Celery workers and Celery Beat both use `REDIS_URL` as their broker and result backend. There is no separate `CELERY_BROKER_URL` variable — the single `REDIS_URL` covers all three consumers.

---

## Auth

| Variable | Required | Default | Purpose |
| --- | --- | --- | --- |
| `JWT_ALGORITHM` | No | `HS256` | Algorithm used to sign and verify JWTs. |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | No | `30` | How long an access token is valid. |
| `REFRESH_TOKEN_EXPIRE_DAYS` | No | `30` | How long a refresh token is valid. |
| `DEMO_MODE` | No | `false` | Set to `true` to enable demo mode: disables mutations and clears auth. |

---

## Data providers

| Variable | Required | Default | Purpose |
| --- | --- | --- | --- |
| `ALPHA_VANTAGE_API_KEY` | No | `""` | Key for Alpha Vantage market data. Free tier available. |
| `POLYGON_API_KEY` | No | `""` | Key for Polygon.io. Paid tier required for real-time data. |
| `FINNHUB_API_KEY` | No | `""` | Key for Finnhub news data. Free tier allows 60 requests/minute. |

All three keys are optional at startup. Features that depend on a missing key will return errors at runtime.

---

## Cache TTLs

| Variable | Required | Default | Purpose |
| --- | --- | --- | --- |
| `QUOTE_CACHE_TTL` | No | `900` | Seconds to cache quote data (15 minutes). |
| `FUNDAMENTALS_CACHE_TTL` | No | `86400` | Seconds to cache fundamentals data (24 hours). |
| `HISTORY_CACHE_TTL` | No | `3600` | Seconds to cache price history (1 hour). |

---

## Notifications

| Variable | Required | Default | Purpose |
| --- | --- | --- | --- |
| `DISCORD_WEBHOOK_URL` | No | `""` | Discord webhook endpoint for price and alert notifications. |

---

## AI integration

| Variable | Required | Default | Purpose |
| --- | --- | --- | --- |
| `CLAUDE_API_KEY` | No | `""` | Fallback Claude API key used in development. In production, each user supplies their own key via the UI; this value is the server-level default. |

---

## Frontend (Next.js)

| Variable | Required | Default | Purpose |
| --- | --- | --- | --- |
| `NEXT_PUBLIC_API_URL` | No | `http://localhost:8000/api/v1` | Base URL the frontend uses for API requests. This variable is baked into the Next.js build — change it before building the image, not at runtime. |

---

## Infrastructure (Docker Compose only)

These variables are read by Docker Compose or Traefik, not by the Python application. They appear in `.env.example` but are absent from `config.py`.

| Variable | Required | Default | Purpose |
| --- | --- | --- | --- |
| `DOMAIN` | Yes (prod) | — | Your public domain name, used by Traefik for routing and Let's Encrypt certificate requests. |
| `ACME_EMAIL` | Yes (prod) | — | Email passed to Let's Encrypt for certificate expiry notices. |

---

## Example `.env` (development)

```env
SECRET_KEY=your-secret-key-here
ENVIRONMENT=development
CORS_ORIGINS=http://localhost:3000

DATABASE_URL=postgresql+asyncpg://investing:investing_dev@localhost:5432/investing_companion
POSTGRES_USER=investing
POSTGRES_PASSWORD=investing_dev
POSTGRES_DB=investing_companion

REDIS_URL=redis://localhost:6379/0

ALPHA_VANTAGE_API_KEY=
POLYGON_API_KEY=
FINNHUB_API_KEY=

DISCORD_WEBHOOK_URL=
CLAUDE_API_KEY=

NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1
```

`.env.example` in the project root is the canonical reference. When variables are added or removed, that file is updated first. If you find this page out of date, the example file is the authority.
