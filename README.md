# Investing Companion

Self-hosted investing companion web application providing equity analysis, watchlists, ratio tracking, market overviews, AI-powered insights, and real-time alerts.

## Quick Start (Local Development)

### Prerequisites

- Python 3.11+
- Node.js 18+
- (Optional) Docker & Docker Compose for full stack with database

### Backend Setup

```bash
cd backend

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run the API server
uvicorn app.main:app --reload --port 8000
```

The API will be available at http://localhost:8000

- API docs: http://localhost:8000/docs
- Health check: http://localhost:8000/health

### Frontend Setup

```bash
cd frontend

# Install dependencies (requires Node 18+)
npm install

# Run development server
npm run dev
```

The frontend will be available at http://localhost:3000

### Full Stack with Docker

```bash
# Copy environment file
cp .env.example .env

# Start all services
docker compose up -d

# Run database migrations
cd backend && alembic upgrade head
```

## Current Status

- **Phase 0**: Foundation - Complete
- **Phase 1**: Prototype - Complete (equity search, quotes, charts, fundamentals)
- **Phase 2**: MVP (watchlists, analysis) - Planned
- **Phase 3**: Intelligence (AI, ratios) - Planned
- **Phase 4**: Alerts - Planned
- **Phase 5**: Auth & Settings - Planned

## Tech Stack

| Layer | Technology |
|-------|------------|
| Backend | Python 3.11+ / FastAPI |
| Frontend | Next.js 14 / TypeScript |
| Database | PostgreSQL 15+ with TimescaleDB |
| Cache | Redis |
| Task Queue | Celery |
| Charts | TradingView Lightweight Charts |
| AI | Claude API (user-provided key) |

## API Endpoints (Phase 1)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/equity/search?q=AAPL` | Search equities |
| GET | `/api/v1/equity/{symbol}` | Get equity details |
| GET | `/api/v1/equity/{symbol}/quote` | Get current quote |
| GET | `/api/v1/equity/{symbol}/history` | Get price history |

## License

Private project - All rights reserved
