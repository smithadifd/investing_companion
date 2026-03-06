# Investing Companion

Self-hosted equity analysis dashboard with AI-powered insights, real-time alerts, and trade tracking.

<!-- TODO: Add 3-4 screenshots (dashboard, equity detail, AI analysis, trade tracker) -->

## Why This Exists

Free tools like Yahoo Finance and Google Finance are fine for checking a stock price, but fall apart when you want to compare ratios across a watchlist, track your actual trades, or get AI-generated analysis that considers your specific holdings. Paid tools (TradingView, Koyfin) are great but expensive for a hobbyist investor. This project fills the gap: a self-hosted dashboard that combines data from multiple sources, runs analysis you care about, and sends alerts to Discord when something moves.

## Tech Stack

| Layer | Technology |
|-------|------------|
| Backend | Python 3.11 / FastAPI |
| Frontend | Next.js 16 (App Router) / TypeScript |
| Database | PostgreSQL 15 + TimescaleDB |
| Cache | Redis |
| Task Queue | Celery + Redis broker |
| Charts | TradingView Lightweight Charts |
| AI | Claude API (user-provided key) |
| Notifications | Discord webhooks |
| State | Zustand + TanStack Query |
| Deployment | Docker Compose |

## Architecture

Dual-stack application: Python/FastAPI backend handles data ingestion, analysis, and scheduling; Next.js frontend provides the interactive dashboard.

```
                    +-----------+
                    |  Browser  |
                    +-----+-----+
                          |
                    +-----+-----+
                    |   Caddy   |  (reverse proxy)
                    +--+-----+--+
                       |     |
              +--------+     +--------+
              |                       |
        +-----+-----+          +-----+-----+
        | Next.js 16 |          |  FastAPI   |
        |  Frontend  |          |  Backend   |
        +-----+-----+          +--+--+--+---+
              |                    |  |  |
              +--------+-----------  |  |
                       |             |  |
                 +-----+-----+      |  |
                 | PostgreSQL |      |  |
                 | TimescaleDB|  +---+  +---+
                 +-----------+   |          |
                              +--+--+  +----+----+
                              | Redis|  | Celery  |
                              +-----+  +---------+
```

Data flows through Celery background tasks that pull from Yahoo Finance and Alpha Vantage on a schedule, normalize it, and store it in TimescaleDB hypertables. The frontend reads from the API, never from external sources directly.

## Features

- **Equity Dashboard** -- Search, quote, and chart any publicly traded stock with TradingView charts
- **Watchlists** -- Organize equities into named watchlists with custom columns and sorting
- **Fundamental Analysis** -- P/E, P/B, dividend yield, market cap, and 20+ financial ratios with cross-equity comparison
- **Market Overview** -- Index tracking (S&P 500, NASDAQ, Dow) with sector heatmaps and daily movers
- **AI Analysis** -- Claude-powered equity analysis that considers price history, fundamentals, and your watchlist context
- **Price Alerts** -- Configurable alerts (price crosses, percent change, volume spike) with Discord notifications
- **Trade Tracker** -- Log trades, calculate P&L, track position sizes, and review trade history
- **Calendar & Events** -- Earnings dates, ex-dividend dates, and macro economic events
- **Scheduled Tasks** -- Celery-powered background jobs for data refresh, alert checking, and daily summaries
- **Authentication** -- Single-user auth with secure password hashing and session management

## Quick Start

### Docker (recommended)

```bash
git clone https://github.com/smithadifd/investing_companion.git
cd investing_companion
cp .env.example .env

# Edit .env -- set SECRET_KEY, optionally add DISCORD_WEBHOOK_URL and CLAUDE_API_KEY

docker compose up -d

# Run database migrations
docker compose exec api alembic upgrade head
```

The frontend will be at `http://localhost:3000` and the API at `http://localhost:8000` (with interactive docs at `/docs`).

### Local Development

```bash
# Backend
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# Frontend (separate terminal)
cd frontend
npm install
npm run dev
```

Requires Python 3.11+, Node.js 20+, PostgreSQL 15+ with TimescaleDB, and Redis.

## Testing

```bash
# Backend
cd backend && pytest --cov=app

# Frontend
cd frontend && npm test
```

## Data Sources

| Source | Purpose | Auth |
|--------|---------|------|
| Yahoo Finance | Quotes, fundamentals, history | None (unofficial) |
| Alpha Vantage | Technical indicators, forex | Free API key |
| Claude API | AI-powered analysis | User-provided key |

## License

[MIT](LICENSE)

---

Built with [Claude Code](https://claude.ai/code)
