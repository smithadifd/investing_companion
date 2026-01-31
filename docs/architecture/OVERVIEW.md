# Investing Companion - Architecture Overview

## Vision

A self-hosted web application serving as a comprehensive investing companion. It provides technical/fundamental analysis, watchlists, ratio comparisons, market indices tracking, AI-powered insights, and real-time alerts.

---

## Technology Stack

### Backend
| Component | Technology | Purpose |
|-----------|------------|---------|
| **Framework** | FastAPI (Python 3.11+) | High-performance async API |
| **Database** | PostgreSQL 15+ | Primary data store |
| **Time-Series** | TimescaleDB extension | Efficient price/indicator storage |
| **Cache** | Redis | Session cache, rate limiting, pub/sub |
| **Task Queue** | Celery + Redis | Background jobs, scheduled tasks |
| **ORM** | SQLAlchemy 2.0 | Database operations |
| **Migrations** | Alembic | Schema versioning |

### Frontend
| Component | Technology | Purpose |
|-----------|------------|---------|
| **Framework** | Next.js 14+ (App Router) | React with SSR capabilities |
| **Language** | TypeScript | Type safety |
| **Styling** | Tailwind CSS | Utility-first styling |
| **Charts** | TradingView Lightweight Charts | Professional financial charts |
| **State** | Zustand | Lightweight state management |
| **Data Fetching** | TanStack Query | Server state management |

### Infrastructure
| Component | Technology | Purpose |
|-----------|------------|---------|
| **Containerization** | Docker + Docker Compose | Service orchestration |
| **Reverse Proxy** | Traefik or Nginx | SSL termination, routing |
| **Notifications** | Discord Webhooks | Alert delivery |

### External Services
| Service | Purpose | Tier |
|---------|---------|------|
| **Yahoo Finance** | Basic quotes, fundamentals | Free |
| **Alpha Vantage** | Technical indicators, forex | Free (rate limited) |
| **Polygon.io** | Real-time data, alerts | Paid (optional) |
| **Claude API** | AI analysis | User-provided key |

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         User Browser                            │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Reverse Proxy (Traefik)                      │
│                    - SSL Termination                            │
│                    - Path-based routing                         │
└─────────────────────────────────────────────────────────────────┘
                    │                           │
                    ▼                           ▼
┌──────────────────────────────┐  ┌──────────────────────────────┐
│       Next.js Frontend       │  │      FastAPI Backend         │
│       (Port 3000)            │  │      (Port 8000)             │
│  ┌────────────────────────┐  │  │  ┌────────────────────────┐  │
│  │   App Router Pages     │  │  │  │    API Endpoints       │  │
│  │   - Dashboard          │  │  │  │    /api/v1/...         │  │
│  │   - Equity Detail      │  │  │  │                        │  │
│  │   - Watchlists         │  │  │  ├────────────────────────┤  │
│  │   - Ratios             │  │  │  │    Services Layer      │  │
│  │   - Alerts             │  │  │  │    - Data Providers    │  │
│  │   - Settings           │  │  │  │    - Analysis Engine   │  │
│  │                        │  │  │  │    - AI Integration    │  │
│  ├────────────────────────┤  │  │  │    - Notifications     │  │
│  │   Components           │  │  │  │                        │  │
│  │   - Charts (TV Light)  │  │  │  └────────────────────────┘  │
│  │   - Data Tables        │  │  │                              │
│  │   - Forms              │  │  └──────────────────────────────┘
│  └────────────────────────┘  │                │
└──────────────────────────────┘                │
                                                ▼
                    ┌───────────────────────────────────────────┐
                    │              Celery Workers               │
                    │  - Scheduled data fetching                │
                    │  - Alert monitoring                       │
                    │  - AI analysis jobs                       │
                    └───────────────────────────────────────────┘
                                        │
            ┌───────────────────────────┼───────────────────────┐
            ▼                           ▼                       ▼
┌─────────────────────┐  ┌─────────────────────┐  ┌─────────────────────┐
│    PostgreSQL       │  │       Redis         │  │   External APIs     │
│    + TimescaleDB    │  │  - Cache            │  │  - Yahoo Finance    │
│  - User data        │  │  - Task broker      │  │  - Alpha Vantage    │
│  - Watchlists       │  │  - Pub/Sub          │  │  - Polygon.io       │
│  - Alerts config    │  │  - Rate limiting    │  │  - Claude API       │
│  - Price history    │  │                     │  │                     │
└─────────────────────┘  └─────────────────────┘  └─────────────────────┘
                                                            │
                                                            ▼
                                              ┌─────────────────────┐
                                              │   Discord Webhook   │
                                              │   (Notifications)   │
                                              └─────────────────────┘
```

---

## Core Domain Models

### Equity
The central entity representing a stock, ETF, or other tradeable security.

```
Equity
├── symbol (e.g., "AAPL")
├── name
├── exchange
├── asset_type (stock, etf, crypto, forex)
├── sector
├── industry
└── fundamentals (1:1 → EquityFundamentals)
    ├── market_cap
    ├── pe_ratio
    ├── eps
    ├── dividend_yield
    └── ...
```

### Watchlist
User-curated collections of equities with notes and tags.

```
Watchlist
├── name
├── description
├── is_default
└── items (1:N → WatchlistItem)
    ├── equity
    ├── added_date
    ├── notes
    ├── target_price
    └── thesis
```

### Ratio
Predefined or custom ratios for market analysis.

```
Ratio
├── name (e.g., "Gold/Bitcoin")
├── numerator_symbol
├── denominator_symbol
├── description
├── category (commodity, equity, macro)
└── is_favorite
```

### Alert
Configurable notifications based on price/indicator conditions.

```
Alert
├── equity or ratio
├── condition_type (above, below, crosses, percent_change)
├── threshold_value
├── timeframe
├── is_active
├── notification_channel
└── last_triggered
```

---

## Data Flow Patterns

### 1. Real-time Quotes
```
User Request → API → Cache Check → [Hit: Return] / [Miss: Fetch from Provider → Cache → Return]
```

### 2. Historical Data
```
Scheduled Job → Fetch from Provider → Store in TimescaleDB → Available for Analysis
```

### 3. AI Analysis
```
User Request → Build Context (equity data, fundamentals, technicals) → Claude API → Stream Response → Display
```

### 4. Alerts
```
Celery Beat (every N minutes) → Check Active Alerts → Compare Conditions → [Triggered: Discord Webhook]
```

---

## Security Considerations

1. **API Keys**: Stored encrypted in database, decrypted at runtime
2. **Authentication**: JWT-based (Phase 5), optional for single-user deployments
3. **Rate Limiting**: Per-user and global limits via Redis
4. **Input Validation**: Pydantic schemas for all endpoints
5. **CORS**: Configured for frontend origin only
6. **Secrets**: Environment variables, never in code

---

## Scalability Notes

This is designed for personal use but structured for growth:

- **Horizontal**: Celery workers can scale independently
- **Caching**: Redis reduces API calls to external providers
- **Time-series**: TimescaleDB handles large historical datasets efficiently
- **Stateless API**: Multiple FastAPI instances behind load balancer if needed

---

## Directory Structure

```
investing_companion/
├── backend/
│   ├── app/
│   │   ├── api/v1/endpoints/    # Route handlers
│   │   ├── core/                # Config, security, dependencies
│   │   ├── db/models/           # SQLAlchemy models
│   │   ├── services/            # Business logic
│   │   │   ├── data_providers/  # Yahoo, Alpha Vantage, Polygon
│   │   │   ├── analysis/        # Technical/fundamental analysis
│   │   │   ├── ai/              # Claude integration
│   │   │   └── notifications/   # Discord, future channels
│   │   ├── schemas/             # Pydantic models
│   │   ├── tasks/               # Celery task definitions
│   │   └── utils/               # Helpers
│   ├── tests/
│   ├── alembic/                 # Database migrations
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── app/                 # Next.js App Router pages
│   │   ├── components/          # React components
│   │   ├── lib/                 # API clients, hooks, utilities
│   │   ├── types/               # TypeScript definitions
│   │   └── context/             # React context providers
│   ├── public/
│   └── package.json
├── docker/                      # Dockerfiles
├── docs/                        # Documentation
├── scripts/                     # Utility scripts
├── docker-compose.yml
├── .env.example
└── CLAUDE.md                    # Claude Code project config
```
