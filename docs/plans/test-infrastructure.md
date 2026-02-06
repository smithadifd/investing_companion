# Plan: Test Infrastructure & Enhanced Health Endpoint [COMPLETED 2026-02-05]

## Overview

Two workstreams to unlock the `logic-tester`, `pre-commit-check`, and `deploy-checker` agents:

1. **Test infrastructure** — conftest.py, fixtures, model factories, example tests
2. **Enhanced health endpoint** — add Celery worker check to existing `/health`

---

## Workstream 1: Test Infrastructure

### Current State
- `backend/tests/` has only an empty `__init__.py`
- Test dependencies already installed: pytest, pytest-asyncio, pytest-cov, httpx
- No conftest.py, no fixtures, no factories, no test database setup
- All services take `AsyncSession` in constructor (clean DI, easy to test)
- All endpoints use `get_db` dependency (overridable in tests)

### Files to Create/Modify

#### 1. `backend/pytest.ini` (or section in pyproject.toml)
- Configure pytest-asyncio mode (`auto`)
- Set test paths
- Set asyncio_mode

#### 2. `backend/tests/conftest.py` — Core fixtures
- **Test database URL**: Override `DATABASE_URL` to use `investing_companion_test` DB
- **Async engine fixture** (session-scoped): Create engine, run `Base.metadata.create_all`, yield, drop all
- **Async session fixture** (function-scoped): Create session per test, rollback after each test
- **FastAPI test client fixture**: `httpx.AsyncClient` with app, override `get_db` dependency
- **Auth fixtures**: Create test user, generate JWT token, provide authenticated client

#### 3. `backend/tests/factories.py` — Model factories
Simple factory functions (not factory-boy, to avoid adding a dependency):
- `create_test_user(db, **overrides)` → User
- `create_test_equity(db, symbol="TEST", **overrides)` → Equity
- `create_test_watchlist(db, **overrides)` → Watchlist + WatchlistItems
- `create_test_alert(db, equity, **overrides)` → Alert
- `create_test_trade(db, equity, **overrides)` → Trade

Each factory creates the object in DB and returns the ORM model.

#### 4. `backend/tests/test_services/` — Service unit tests
Start with one example to validate the infrastructure:
- `test_services/__init__.py`
- `test_services/test_alert_service.py` — Tests for alert evaluation logic (the most complex service, and the one that's had the most bugs)
  - Test each AlertConditionType (above, below, crosses_above, crosses_below, percent_up, percent_down)
  - Test cooldown behavior
  - Test with mocked Yahoo Finance provider

#### 5. `backend/tests/test_api/` — API endpoint tests
Start with one example:
- `test_api/__init__.py`
- `test_api/test_auth.py` — Registration, login, token refresh, protected endpoint access
  - Tests both success and failure cases
  - Tests rate limiting

### Key Design Decisions
- **Test DB strategy**: Create `investing_companion_test` in the same PostgreSQL instance. Use `Base.metadata.create_all/drop_all` per session (not per test — too slow). Use transaction rollback per test for isolation.
- **No factory-boy**: Keep it simple with plain async factory functions. Avoids a new dependency.
- **Mock external services**: Yahoo Finance and Discord webhook mocked via `unittest.mock.AsyncMock`. Never hit real APIs in tests.
- **TimescaleDB**: Tests use regular PostgreSQL tables (no hypertable creation). TimescaleDB-specific features tested separately if needed.

### Critical Files to Reference
- `backend/app/db/session.py` — Engine and session factory to mirror in tests
- `backend/app/db/base.py` — `Base` class for metadata.create_all
- `backend/app/db/models/__init__.py` — All models (must be imported for create_all)
- `backend/app/main.py` — FastAPI `app` instance for test client
- `backend/app/core/config.py` — Settings class to override
- `backend/app/services/alert.py` — First service to test (most complex)
- `backend/app/api/v1/endpoints/auth.py` — First endpoint to test

---

## Workstream 2: Enhanced Health Endpoint

### Current State
- `/health` exists in `backend/app/main.py`
- Checks DB (SELECT 1) and Redis (PING) when `?detailed=true`
- Returns "healthy" or "degraded"

### Changes to `backend/app/main.py`

Add a **Celery worker check** to the detailed health response:
- Use `celery_app.control.inspect().ping()` to check if workers are responsive
- Add to the `checks` dict alongside database and redis
- Timeout after 2-3 seconds (don't block if Celery is down)
- Worker being down = "degraded" (not "unhealthy" — the API still works)

Result:
```json
{
  "status": "healthy",
  "checks": {
    "database": {"status": "ok"},
    "redis": {"status": "ok"},
    "celery": {"status": "ok", "workers": 1}
  }
}
```

---

## Verification

1. Run `cd backend && python -m pytest tests/ -v` — all tests pass
2. Run `cd backend && python -m pytest tests/ --cov=app` — coverage report works
3. Hit `/health?detailed=true` locally — shows DB, Redis, Celery status
4. Invoke the `logic-tester` agent and ask it to generate tests — it can build on the fixtures
5. Invoke the `pre-commit-check` agent — its pytest step actually runs tests
6. Invoke the `deploy-checker` agent — post-deploy health check gets Celery status

---

## Estimated Scope
- **conftest.py + fixtures**: ~150 lines
- **factories.py**: ~100 lines
- **test_alert_service.py**: ~200 lines
- **test_auth.py**: ~150 lines
- **pytest config**: ~10 lines
- **Health endpoint enhancement**: ~30 lines
- **Total**: ~640 lines across ~8 files
