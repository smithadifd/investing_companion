---
title: Security hardening
description: How to generate a secure secret key, configure registration controls, set up HTTPS, and understand the rate limiting and network isolation that ship with Investing Companion.
---

Before exposing Investing Companion to a network, you need to set a real `SECRET_KEY`, lock down registration, and make sure internal services are not reachable outside Docker. This page covers all of that.

## Secret key

`SECRET_KEY` is the root secret for the application. It signs JWT access tokens and derives the Fernet key used to encrypt API credentials stored in the database. If it leaks, an attacker can forge sessions and decrypt user data.

Generate one before first run:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

That produces a 43-character URL-safe string. The application refuses to start with `ENVIRONMENT=production` if `SECRET_KEY` is shorter than 32 characters or matches any of the known-insecure defaults (`changeme`, `secret`, `dev-secret-key-change-in-production`, and similar).

Put the value in `.env.production` — never in source control:

```bash
SECRET_KEY=<output from command above>
```

**If you rotate this key**, all existing sessions are invalidated immediately. Every logged-in user has to sign in again. There is no migration path for active tokens.

You also need a strong `POSTGRES_PASSWORD`. A quick way to generate one:

```bash
openssl rand -base64 24
```

## Disabling registration

`REGISTRATION_ENABLED` controls whether the `/api/v1/auth/register` endpoint accepts new users. It defaults to `true`.

Once you have created your account, set it to `false`:

```bash
REGISTRATION_ENABLED=false
```

The `docker-compose.prod.yml` file defaults this to `false` already (`REGISTRATION_ENABLED=${REGISTRATION_ENABLED:-false}`), so if you deploy from that file without setting the variable, registration is off. If you are running locally or with a custom compose file, check that you have set it explicitly.

To re-enable registration temporarily (for example, to add another user), flip the variable and restart the API container, then flip it back.

## Rate limiting

Login rate limiting is implemented in `app/core/rate_limit.py` using Redis as a counter store. It applies two independent windows at the `/api/v1/auth/login` endpoint:

| Scope | Limit | Window |
| --- | --- | --- |
| Per IP address | 20 attempts | 15 minutes |
| Per email address | 5 attempts | 15 minutes |

Both return HTTP 429 with a `Retry-After: 900` header when the limit is hit. On a successful login the per-email counter resets; the per-IP counter does not.

This is the only endpoint with application-level rate limiting. General API traffic is rate-limited at the Traefik layer in `docker-compose.prod.yml`: 100 requests/second average, 50 burst, applied as a Traefik middleware on the API router.

Rate limiting depends on Redis. If the Redis container is unreachable at startup, the rate limiter will fail to initialise and login attempts will not be counted. Make sure Redis is healthy before the API starts — the compose file enforces this with a `service_healthy` dependency.

## HTTPS

How you get TLS depends on which compose file you use. See [configuration](/running/configuration/) for the full picture; the short version:

**Public deployment (`docker-compose.prod.yml`)** — Traefik handles TLS termination and fetches certificates from Let's Encrypt automatically using the HTTP-01 challenge. You need a domain pointed at the server and ports 80 and 443 open. Set your email address for ACME notifications:

```bash
ACME_EMAIL=you@example.com
DOMAIN=yourapp.example.com
```

HTTP traffic on port 80 redirects to HTTPS. The API and frontend containers have no public ports of their own — all traffic enters through Traefik.

**LAN/NAS deployment (`docker-compose.local.yml`)** — this file expects an external reverse proxy (Caddy on the [Synology setup](/running/synology/)) to handle TLS. The compose file does not include Traefik, so you are responsible for terminating TLS before traffic reaches the app. The application itself sets `Strict-Transport-Security: max-age=31536000; includeSubDomains` on all responses when `ENVIRONMENT=production`, so your proxy must be terminating HTTPS for that header to be meaningful.

In both cases, the `/api/v1/docs` and `/api/v1/redoc` endpoints are disabled when `ENVIRONMENT=production`. The API docs are only available in development.

## CORS

`CORS_ORIGINS` is a comma-separated list of allowed origins. In development it defaults to `http://localhost:3000,http://localhost:3001`. The application will refuse to start with `ENVIRONMENT=production` if `CORS_ORIGINS` contains `*`.

For a production deployment set it to the exact origin your frontend is served from:

```bash
CORS_ORIGINS=https://yourapp.example.com
```

The `docker-compose.prod.yml` file sets this automatically from the `DOMAIN` variable: `CORS_ORIGINS=https://${DOMAIN}`.

## Network isolation

All services run on the `investing_network` Docker bridge network. Neither PostgreSQL (port 5432) nor Redis (port 6379) have `ports:` entries in `docker-compose.prod.yml`, so they are only reachable from other containers on the same network. The API runs on port 8000 inside Docker and is exposed externally only via Traefik routing rules.

Do not add port mappings for `db` or `redis` in production. Direct database access should go through `docker exec` on the host.

Flower (the Celery monitoring UI) is not included in the production compose file. If you add it for debugging, do not expose it publicly.

## Security headers

`SecurityHeadersMiddleware` adds the following to every response:

- `X-Frame-Options: DENY`
- `X-Content-Type-Options: nosniff`
- `X-XSS-Protection: 1; mode=block`
- `Referrer-Policy: strict-origin-when-cross-origin`
- `Permissions-Policy` — disables geolocation, microphone, camera, payment, USB, magnetometer, and gyroscope
- `Strict-Transport-Security: max-age=31536000; includeSubDomains` (production only)
- `Cache-Control: no-store` on `/api/v1/auth/*` routes

The `server` response header is stripped.

## Pre-launch checklist

Before going live, verify each of these:

- [ ] `SECRET_KEY` is at least 32 characters and not a known default
- [ ] `POSTGRES_PASSWORD` is not the dev default (`investing_dev`)
- [ ] `REGISTRATION_ENABLED=false` (or left unset in `docker-compose.prod.yml` which defaults to false)
- [ ] `CORS_ORIGINS` is set to your exact frontend origin, no wildcards
- [ ] `ENVIRONMENT=production` — triggers validation on startup and enables HSTS
- [ ] Ports 5432 and 6379 are NOT forwarded to the host
- [ ] Only ports 80 and 443 are reachable from the internet
- [ ] HTTPS is working: `curl -I https://your-domain.com` returns a 200 with HSTS header
- [ ] Rate limiting is working: 25 rapid POST requests to `/api/v1/auth/login` should start returning 429 after the 20th attempt from the same IP
- [ ] `.env.production` is listed in `.gitignore`
