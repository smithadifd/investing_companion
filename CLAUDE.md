# Investing Companion - Claude Code Project Configuration

## Project Overview

Self-hosted investing companion web application providing equity analysis, watchlists, ratio tracking, market overviews, AI-powered insights, and real-time alerts.

**Owner**: Andrew (drew4bucks@gmail.com)
**Status**: Phase 6.5 complete - calendar and events functional

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| Backend | Python 3.11+ / FastAPI |
| Frontend | Next.js 14+ (App Router) / TypeScript |
| Database | PostgreSQL 15+ with TimescaleDB |
| Cache | Redis |
| Task Queue | Celery |
| Charts | TradingView Lightweight Charts |
| AI | Claude API (user-provided key) |
| Notifications | Discord webhooks |
| Deployment | Docker Compose |

---

## Directory Structure

```
investing_companion/
├── backend/                 # FastAPI application
│   ├── app/
│   │   ├── api/v1/endpoints/  # Route handlers
│   │   ├── core/              # Config, security
│   │   ├── db/models/         # SQLAlchemy models
│   │   ├── services/          # Business logic
│   │   ├── schemas/           # Pydantic schemas
│   │   ├── tasks/             # Celery tasks
│   │   └── utils/
│   ├── tests/
│   └── alembic/               # Migrations
├── frontend/                # Next.js application
│   └── src/
│       ├── app/               # Pages (App Router)
│       ├── components/        # React components
│       ├── lib/               # API clients, hooks
│       └── types/             # TypeScript types
├── docker/                  # Dockerfiles
├── docs/                    # Documentation
└── scripts/                 # Utility scripts
```

---

## Development Commands

```bash
# Start all services
docker compose up -d

# Backend only (for hot reload)
cd backend && uvicorn app.main:app --reload

# Frontend only
cd frontend && npm run dev

# Run backend tests
cd backend && pytest

# Run migrations
cd backend && alembic upgrade head

# Create new migration
cd backend && alembic revision --autogenerate -m "description"
```

---

## Code Conventions

### Python (Backend)
- Use type hints everywhere
- Pydantic for all request/response schemas
- SQLAlchemy 2.0 style (mapped_column)
- Async functions for I/O-bound operations
- Service layer pattern (endpoints → services → models)
- Meaningful variable names, avoid abbreviations

### TypeScript (Frontend)
- Strict TypeScript (no `any`)
- Functional components with hooks
- TanStack Query for server state
- Zustand for client state
- Component files: `ComponentName.tsx`
- Hooks: `useHookName.ts`

### General
- Conventional commits (feat:, fix:, docs:, etc.)
- Feature branches from `develop`
- Tests for services and critical paths
- Comments only for non-obvious logic

---

## Key Files Reference

| File | Purpose |
|------|---------|
| `docs/ROADMAP.md` | Phased development plan |
| `docs/architecture/OVERVIEW.md` | System architecture |
| `docs/sessions/` | Session notes and history |
| `backend/app/core/config.py` | Environment configuration |
| `backend/app/db/models/*.py` | Database models |
| `frontend/src/lib/api/client.ts` | API client |

---

## Session Notes

Development sessions are documented in `docs/sessions/`. Each session log includes:
- What was accomplished
- Issues encountered and resolved
- Commits made
- Next steps identified

When starting a new session, review the most recent session notes for context.

---

## Data Providers

| Provider | Usage | Rate Limit |
|----------|-------|------------|
| Yahoo Finance | Quotes, fundamentals, history | Unofficial, be gentle |
| Alpha Vantage | Technical indicators, forex | 5 req/min (free) |
| Polygon.io | Real-time, alerts (optional) | Paid tier |

---

## Environment Variables

```env
# Backend
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/investing
REDIS_URL=redis://localhost:6379/0
SECRET_KEY=your-secret-key
CLAUDE_API_KEY=  # Optional, users provide their own

# Frontend
NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1

# Services
DISCORD_WEBHOOK_URL=  # For notifications
ALPHA_VANTAGE_API_KEY=  # Free tier available
POLYGON_API_KEY=  # Optional paid tier
```

---

## Testing Strategy

- **Unit tests**: Services, utilities, data transformations
- **Integration tests**: API endpoints with test database
- **E2E tests**: Critical user flows (future, with Playwright)

Run tests:
```bash
# Backend
pytest --cov=app

# Frontend
npm test
```

---

## Working with This Project

### When starting a new phase:
1. Read `docs/ROADMAP.md` for phase requirements
2. Check architecture docs for design context
3. Create models/schemas first
4. Implement services
5. Add API endpoints
6. Build frontend features
7. Write tests

### AI Integration Notes:
- Claude API key stored encrypted in user_settings table
- Support streaming responses via SSE
- Include equity context (prices, fundamentals) in prompts
- Cache AI responses for identical queries (1-hour TTL)

### Adding a new data provider:
1. Create service in `backend/app/services/data_providers/`
2. Implement standard interface (get_quote, get_history, search)
3. Add fallback logic in aggregator service
4. Configure via environment variable

---

## Phase Status

- [x] Phase 0: Foundation (structure, docs) - COMPLETE
- [x] Phase 1: Prototype (equity display, charts) - COMPLETE
- [x] Phase 2: MVP (watchlists, analysis, import) - COMPLETE
- [x] Phase 3: Intelligence (AI, ratios, indices) - COMPLETE (AI pending OAuth - see docs/issues/)
- [x] Phase 4: Alerts (notifications) - COMPLETE
- [x] Phase 5: Polish (auth, settings) - COMPLETE
- [x] Phase 6: Trade Tracker (trades, P&L, position sizing) - COMPLETE
- [x] Phase 6.5: Calendar & Events (earnings, macro events) - COMPLETE
- [ ] Phase 6.6: Deployment Prep (security, Synology) - PLANNED
- [ ] Phase 7: Advanced AI (AI integrations, automation) - blocked on OAuth/API resolution

---

## Known Limitations

- Yahoo Finance is unofficial API - may break
- TimescaleDB extension required for PostgreSQL
- Single-user focus initially (auth is Phase 5)
- No mobile-specific optimization yet

---

## Resources

- [FastAPI Docs](https://fastapi.tiangolo.com/)
- [Next.js App Router](https://nextjs.org/docs/app)
- [TradingView Lightweight Charts](https://tradingview.github.io/lightweight-charts/)
- [TimescaleDB Docs](https://docs.timescale.com/)
- [Claude API Docs](https://docs.anthropic.com/)
