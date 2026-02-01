# Investing Companion - Development Roadmap

## Phase Overview

| Phase | Name | Focus | Est. Effort | Outcome |
|-------|------|-------|-------------|---------|
| 0 | Foundation | Infrastructure setup | 1-2 days | Dev environment running |
| 1 | Prototype | Core equity display | 3-5 days | View equities, basic charts |
| 2 | MVP | Watchlists + Analysis | 1-2 weeks | Usable daily driver |
| 3 | Intelligence | AI + Ratios + Indices | 1-2 weeks | AI-powered insights |
| 4 | Alerts | Notifications | 3-5 days | Real-time alerts |
| 5 | Polish | Auth + Settings | 3-5 days | Production-ready |
| 6 | Advanced | Trade Tracker | Ongoing | Full trading companion |

---

## Phase 0: Foundation
**Goal**: Development environment and infrastructure ready

### Deliverables
- [x] Docker Compose with all services (Postgres, Redis, API, Frontend)
- [x] FastAPI skeleton with health endpoint
- [x] Next.js skeleton with basic layout
- [x] Database connection and Alembic setup
- [x] Environment configuration (.env structure)
- [ ] Basic CI workflow (linting, type checking)

### Success Criteria
```bash
docker compose up  # All services start
curl localhost:8000/health  # Returns OK
open localhost:3000  # Shows placeholder page
```

### Technical Decisions Made
- PostgreSQL with TimescaleDB extension enabled
- Redis for cache + Celery broker
- Traefik for reverse proxy (production) / direct ports (dev)

---

## Phase 1: Prototype
**Goal**: View equity data with basic charting

### Deliverables

#### Backend
- [x] Equity model + basic CRUD endpoints
- [x] Yahoo Finance data provider integration
- [x] Quote endpoint (`GET /api/v1/equity/{symbol}/quote`)
- [x] Historical data endpoint (`GET /api/v1/equity/{symbol}/history`)
- [x] Search endpoint (`GET /api/v1/equity/search?q=...`)
- [x] Basic caching (15-min for quotes, 1-day for fundamentals)

#### Frontend
- [x] Dashboard page with search bar
- [x] Equity detail page (`/equity/[symbol]`)
- [x] Price chart using TradingView Lightweight Charts
- [x] Basic fundamentals display (P/E, Market Cap, etc.)
- [x] Simple responsive layout

#### Data Model
```
equities
├── id (PK)
├── symbol (unique)
├── name
├── exchange
├── asset_type
├── sector
├── industry
├── created_at
└── updated_at

price_history (TimescaleDB hypertable)
├── equity_id (FK)
├── timestamp
├── open
├── high
├── low
├── close
├── volume
└── (PRIMARY KEY: equity_id, timestamp)
```

### Success Criteria
- Search for "AAPL" → View Apple stock page with live quote and 1-year chart
- Page loads in < 2 seconds
- Data refreshes without full page reload

---

## Phase 2: MVP
**Goal**: Watchlists, analysis views, import/export - a usable daily driver

### Deliverables

#### Backend
- [x] Watchlist model + CRUD endpoints
- [x] WatchlistItem with notes, target price, thesis
- [x] Fundamental analysis aggregation service (peer comparison)
- [x] Technical indicators service (RSI, MACD, Moving Averages)
- [x] Import endpoint (CSV, JSON upload)
- [x] Export endpoint (CSV, JSON download)
- [ ] Alpha Vantage integration for additional indicators (optional)

#### Frontend
- [x] Watchlist management page
- [x] Create/edit watchlist modal
- [x] Add equity to watchlist (from detail page or search)
- [x] Equity notes and thesis editor
- [x] Technical analysis tab on equity detail
  - [x] Indicator overlays on chart (SMA, EMA, Bollinger Bands)
  - [x] RSI, MACD sub-charts
- [x] Fundamental analysis tab
  - [x] Key metrics table
  - [x] Peer comparison (same sector)
- [x] Import dialog (drag & drop CSV/JSON)
- [x] Export button on watchlist

#### Data Model Additions
```
watchlists
├── id (PK)
├── user_id (FK, nullable until Phase 5)
├── name
├── description
├── is_default
├── created_at
└── updated_at

watchlist_items
├── id (PK)
├── watchlist_id (FK)
├── equity_id (FK)
├── notes (text)
├── target_price (decimal, nullable)
├── thesis (text, nullable)
├── added_at
└── (UNIQUE: watchlist_id, equity_id)

equity_fundamentals
├── equity_id (FK, unique)
├── market_cap
├── pe_ratio
├── forward_pe
├── peg_ratio
├── eps_ttm
├── dividend_yield
├── beta
├── 52w_high
├── 52w_low
├── avg_volume
├── updated_at
```

### Success Criteria
- Create watchlist "Uranium Plays"
- Add CCJ, UEC, DNN with notes
- View technical indicators on any equity
- Export watchlist to CSV, reimport successfully

---

## Phase 3: Intelligence ✅
**Goal**: AI analysis, ratio comparisons, market indices overview
**Status**: COMPLETE (AI pending OAuth support - see [Issue #001](./issues/001-claude-oauth-support.md))

### Deliverables

#### Backend
- [x] Claude API integration service
- [x] Configurable AI provider (API key from settings)
- [x] AI analysis endpoint (`POST /api/v1/ai/analyze`)
- [x] Streaming response support (SSE)
- [x] Ratio model + CRUD endpoints
- [x] Ratio calculation service
- [x] Pre-defined ratio library (Gold/Silver, SPY/QQQ, etc.)
- [x] Market indices aggregation
- [x] Sector performance ranking
- [ ] Alpha Vantage integration (optional - for additional indicators, forex, economic data)

#### Frontend
- [x] AI Analysis component (chat-like interface on equity page)
- [x] "Analyze This" button triggering AI review
- [x] AI settings (model selection, custom instructions)
- [x] Ratios page
  - Favorites at top
  - Chart for each ratio
  - Configurable timeframes
- [x] Market Overview page
  - Major indices cards
  - Sector heatmap
  - Top gainers/losers
  - Currency & commodity snapshot

#### Known Limitations
- AI features require standard API key or proxy setup (OAuth tokens not yet supported by Anthropic API)

#### Data Model Additions
```
ratios
├── id (PK)
├── name
├── numerator_symbol
├── denominator_symbol
├── description
├── category (commodity, equity, macro, crypto)
├── is_system (boolean, for presets)
├── is_favorite
└── created_at

market_indices
├── symbol
├── name
├── region
├── asset_class
└── display_order

user_settings (prep for Phase 5)
├── id (PK)
├── user_id (nullable)
├── key
├── value (encrypted for sensitive)
└── updated_at
```

### Pre-loaded Ratios
| Ratio | Numerator | Denominator | Category |
|-------|-----------|-------------|----------|
| Gold/Silver | GLD | SLV | Commodity |
| Gold/Bitcoin | GLD | BITO | Crypto |
| Value/Growth | VTV | VUG | Equity |
| SPY/QQQ | SPY | QQQ | Equity |
| Copper/Gold | CPER | GLD | Macro |
| TLT/IEF | TLT | IEF | Macro |
| DXY proxy | UUP | - | Macro |

### AI Analysis Features
- **Equity Analysis**: Fundamentals review, technical setup, thesis challenges
- **Ratio Context**: Explain what the ratio indicates, historical significance
- **Watchlist Review**: Summarize holdings, flag concerns, suggest actions
- **Custom Questions**: Chat interface for follow-up questions

### Success Criteria
- Ask AI "What's the bull and bear case for CCJ?"
- View Gold/Silver ratio chart with 5-year history
- See sector heatmap showing energy +2.3% today
- Add custom ratio (e.g., URA/XLE)

---

## Phase 4: Alerts
**Goal**: Real-time monitoring and Discord notifications
**Status**: COMPLETE

### Deliverables

#### Backend
- [x] Alert model + CRUD endpoints
- [x] Celery Beat scheduler (configurable interval)
- [x] Alert condition evaluator service
- [x] Discord webhook notification service
- [x] Alert history tracking
- [x] Cooldown logic (don't spam same alert)

#### Frontend
- [x] Alerts management page
- [x] Create alert dialog
  - Select equity or ratio
  - Condition type (above, below, crosses, % change)
  - Threshold value
  - Optional: timeframe, notes
- [x] Active alerts list with toggle
- [x] Alert history log
- [x] Discord integration settings

#### Data Model Additions
```
alerts
├── id (PK)
├── user_id (nullable)
├── name
├── equity_id (FK, nullable)
├── ratio_id (FK, nullable)
├── condition_type (enum)
├── threshold_value
├── comparison_period (for % change)
├── is_active
├── cooldown_minutes
├── last_triggered_at
├── created_at
└── updated_at

alert_history
├── id (PK)
├── alert_id (FK)
├── triggered_at
├── triggered_value
├── notification_sent
└── notification_channel
```

### Alert Condition Types
| Type | Example |
|------|---------|
| `ABOVE` | Price > $50 |
| `BELOW` | Price < $40 |
| `CROSSES_ABOVE` | Price crosses above 200 MA |
| `CROSSES_BELOW` | Price crosses below 50 MA |
| `PERCENT_UP` | +5% in 24h |
| `PERCENT_DOWN` | -5% in 24h |
| `RATIO_ABOVE` | Gold/Silver > 85 |
| `RATIO_BELOW` | Gold/Silver < 70 |

### Success Criteria
- Create alert: "CCJ above $60"
- Alert triggers → Discord message received within 5 minutes
- View alert history showing trigger events

---

## Phase 5: Polish ✅
**Goal**: Authentication, user profiles, production hardening
**Status**: COMPLETE

### Deliverables

#### Backend
- [x] User model + authentication endpoints
- [x] JWT-based auth with refresh tokens
- [x] Password hashing (argon2)
- [x] User settings encryption
- [ ] API key rotation for external services (future)
- [ ] Rate limiting per user (future)
- [ ] Audit logging (future)

#### Frontend
- [x] Login page
- [x] Registration page (conditional on REGISTRATION_ENABLED)
- [x] Settings page
  - API keys (Claude, Alpha Vantage, Polygon)
  - Discord webhook URL
  - Password change
  - Session management
- [x] Profile page (integrated into Settings)
- [x] Auth context and protected routes

#### Data Model Additions
```
users
├── id (PK, UUID)
├── email (unique)
├── password_hash
├── is_active
├── is_admin
├── created_at
└── last_login_at

sessions
├── id (PK, UUID)
├── user_id (FK)
├── refresh_token_hash
├── user_agent
├── ip_address
├── expires_at
├── created_at
└── revoked_at
```

### Security Features Implemented
- Password hashing with Argon2id
- JWT access tokens (30 min default)
- Refresh tokens (30 days, SHA-256 hashed)
- Session tracking and revocation
- API key encryption (Fernet)
- Optional registration disable

### Security Hardening (Future)
- HTTPS enforcement
- CSRF protection
- Security headers (CSP, HSTS, etc.)
- Dependency vulnerability scanning
- Backup automation

### Success Criteria
- [x] Login with email/password
- [x] Settings persist across sessions
- [x] Optional: Disable registration for single-user mode

---

## Phase 6: Advanced (Future)
**Goal**: Trade tracking, position sizing, advanced AI features

### Potential Features

#### Trade Tracker
- [ ] Trade model (entry, exit, quantity, fees)
- [ ] Quick trade entry form
- [ ] Trade journal with notes
- [ ] P&L calculations (realized, unrealized)
- [ ] Performance analytics
  - Win rate
  - Average gain/loss
  - Best/worst trades
  - Performance by sector/thesis

#### Position Sizer
- [ ] Risk calculator
  - Account size input
  - Risk percentage
  - Stop loss level
  - → Suggested position size
- [ ] Kelly Criterion option
- [ ] Volatility-adjusted sizing

#### Advanced AI
- [ ] Auto-summarize market news
- [ ] Thesis challenger (devil's advocate mode)
- [ ] Portfolio review scheduling
- [ ] Voice input for quick notes
- [ ] Integration with Claude MCP (Claude Code can query your app)

#### Data Model Additions
```
trades
├── id (PK)
├── user_id (FK)
├── equity_id (FK)
├── trade_type (buy, sell, short, cover)
├── quantity
├── price
├── fees
├── executed_at
├── notes
├── thesis_id (FK to watchlist_item, optional)
└── created_at

trade_pairs (for P&L matching)
├── id (PK)
├── open_trade_id (FK)
├── close_trade_id (FK)
├── quantity_matched
├── realized_pnl
└── calculated_at
```

---

## Development Approach

### Branch Strategy
```
main (production)
  └── develop (integration)
        ├── feature/phase-0-foundation
        ├── feature/phase-1-prototype
        └── ...
```

### Per-Phase Checklist
- [ ] Create feature branch
- [ ] Implement backend changes
- [ ] Write tests (aim for 70%+ coverage on services)
- [ ] Implement frontend changes
- [ ] Manual QA
- [ ] Update documentation
- [ ] Merge to develop
- [ ] Deploy to staging (your home server)
- [ ] Validate → Merge to main

### Recommended Tools
| Purpose | Tool |
|---------|------|
| API Testing | Bruno or Insomnia |
| DB GUI | DBeaver or pgAdmin |
| Git GUI | GitKraken or CLI |
| Design | Figma (optional, for mockups) |

---

## Milestones

| Milestone | Phases | Deliverable |
|-----------|--------|-------------|
| **M1: "It Works"** | 0 + 1 | View equities, basic charts |
| **M2: "Daily Driver"** | + 2 | Watchlists, analysis, import/export |
| **M3: "Intelligent"** | + 3 | AI analysis, ratios, market overview |
| **M4: "Proactive"** | + 4 | Alerts and notifications |
| **M5: "Production"** | + 5 | Auth, settings, hardened |
| **M6: "Complete"** | + 6 | Trade tracking, position sizing |

---

## Notes & Recommendations

### Start Simple
- Phase 0+1 should be tight. Resist scope creep.
- Yahoo Finance free tier is sufficient for prototype.
- Skip Redis caching initially if it adds complexity (use in-memory).

### Data Source Strategy
- **Free tier first**: Yahoo Finance, Alpha Vantage (5 req/min)
- **Upgrade path**: Polygon.io starter ($29/mo) for real-time + more history
- **Fallback logic**: If one provider fails, try another

### AI Integration Tips
- Store API key encrypted in user_settings
- Default to Claude 3.5 Sonnet (best balance)
- Stream responses for better UX
- Include equity context (fundamentals, recent prices) in prompts
- Consider caching AI responses for repeated questions

### Home Server Considerations
- Use Traefik with Let's Encrypt for HTTPS
- Set up automatic backups (pg_dump to external drive)
- Consider Tailscale for remote access without port forwarding
- Monitor with Uptime Kuma or similar
