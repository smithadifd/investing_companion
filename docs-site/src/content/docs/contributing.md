---
title: Contributing
description: Codebase orientation, service layer pattern, and testing conventions for contributors.
---

This page is for developers who have cloned the repo and want to make changes. It covers codebase layout, the service-layer pattern that governs all backend features, the typical workflow for adding something new, and testing. If you haven't gotten the stack running yet, start with [Quick start (Docker)](/running/quick-start/) — that page covers Docker setup, migrations, and seeding in full detail.

## Getting the code running

Clone, configure, and start everything:

```bash
git clone https://github.com/smithadifd/investing_companion.git
cd investing_companion
cp .env.example .env
docker compose up -d
docker compose exec api alembic upgrade head
```

`SECRET_KEY` and `POSTGRES_PASSWORD` are the two `.env` values you must set before the API will start properly. All external API keys (`ALPHA_VANTAGE_API_KEY`, `FINNHUB_API_KEY`, `CLAUDE_API_KEY`, `DISCORD_WEBHOOK_URL`) are optional — leave them blank initially and the app still runs.

For running the backend or frontend outside Docker, see [Quick start (Docker)](/running/quick-start/).

## Repository layout

```text
investing_companion/
├── backend/
│   └── app/
│       ├── api/v1/endpoints/   # Thin FastAPI route handlers
│       ├── db/models/          # SQLAlchemy models
│       ├── schemas/            # Pydantic request/response schemas
│       └── services/           # Business logic and external provider calls
│           └── data_providers/ # Thin wrappers around external SDKs
├── frontend/                   # Next.js app (App Router, TypeScript)
├── docs-site/                  # This Astro Starlight site
├── docs/                       # Markdown reference docs
├── .github/                    # CI workflows
├── docker-compose.yml
└── docker-compose.prod.yml
```

## Service-layer pattern

This is the most important thing to understand before adding code. All backend logic follows a consistent three-layer split.

**Endpoints are thin.** A route handler validates the request, instantiates a service with the injected database session, calls a single service method, and returns the result. The `GET /{symbol}` handler in `backend/app/api/v1/endpoints/equity.py` is representative:

```python
@router.get("/{symbol}", response_model=DataResponse[EquityDetailResponse])
async def get_equity(
    symbol: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DataResponse[EquityDetailResponse]:
    service = EquityService(db)
    detail = await service.get_equity_detail(symbol)

    if not detail:
        raise HTTPException(status_code=404, detail=f"Equity '{symbol}' not found")

    return DataResponse(data=detail, meta=ResponseMeta.now())
```

`Depends(get_db)` injects an `AsyncSession` from FastAPI's dependency system. You don't create sessions manually — every handler receives one and passes it straight to the service.

**Services own the logic.** They hold business rules, database queries, and calls to external providers. They are instantiated per-request with the injected session. The standard cache-first pattern, as used in `EquityService.get_quote` (`backend/app/services/equity.py`), looks like this:

```python
async def get_quote(self, symbol: str) -> Optional[QuoteResponse]:
    cache_key = cache_service.quote_key(symbol)

    try:
        cached = await cache_service.get(cache_key)
        if cached:
            return QuoteResponse(**cached)
    except Exception:
        pass  # Cache not available

    quote = await self.yahoo.get_quote(symbol)
    if quote:
        try:
            await cache_service.set(cache_key, quote.model_dump(), settings.QUOTE_CACHE_TTL)
        except Exception:
            pass  # Cache not available

    return quote
```

Check cache → on hit, return immediately. On miss, fetch from provider, write to cache, return. Both cache operations are wrapped in `try/except` so the service degrades gracefully if Redis is unavailable.

**Providers wrap external SDKs.** Services never import `yfinance`, `finnhub`, or other third-party SDKs directly. External calls go through provider classes under `backend/app/services/data_providers/` — `YahooFinanceProvider` in `data_providers/yahoo.py` is the main one. This keeps provider-specific error handling and retry logic isolated, and makes the boundary clear when swapping or mocking a data source.

For the architectural context behind this split, see [Architecture overview](/architecture/overview/).

## Adding a new feature

The typical sequence for a new backend+frontend feature:

1. Add or update a Pydantic schema under `backend/app/schemas/`.
2. Add or update a SQLAlchemy model under `backend/app/db/models/`. If the schema changed, generate and apply an Alembic migration — see the [Run migrations](/running/quick-start/#3-run-migrations) section of the quick start.
3. Add a service method under `backend/app/services/`. Follow the cache-first pattern above for any external data.
4. Add a route handler under `backend/app/api/v1/endpoints/` and register the router in `backend/app/main.py` with `app.include_router(...)`.
5. Add a frontend data hook under `frontend/src/hooks/` or an API helper under `frontend/src/lib/api/`.
6. Build the UI component.

Steps 1-4 should stay in sync. A Pydantic schema without a matching service method, or a service method without an endpoint, is a halfway-done feature.

## Tests

```bash
# Backend — requires a running Postgres instance (via docker compose or local)
cd backend && pytest --cov=app

# Frontend
cd frontend && npm test
```

Coverage is uneven. `AlertService` has service-layer tests. FIFO trade matching — the logic that builds `trade_pairs` from raw trades — has no tests yet. That gap is documented in [FIFO trade matching](/design-decisions/fifo-matching/). When adding new service logic, adding tests alongside is expected; backfilling existing gaps is welcome.

## Code style

Python: type hints on all function signatures, Pydantic schemas for all input/output shapes, async I/O throughout. TypeScript: strict mode, functional components, TanStack Query for server state. Commits follow conventional commit format (`feat:`, `fix:`, `docs:`, `refactor:`, `chore:`).

The full style notes are in `docs/CONTRIBUTING.md` in the repo root.

## Deploying your changes

Before a risky schema change, back up the database first — see [Backup and restore](/running/backup/). For deploying to a Synology NAS, see [Synology deployment](/running/synology/).
