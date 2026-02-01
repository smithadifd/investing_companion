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
| 6 | Trade Tracker | Trades + P&L + Sizing | 1-2 weeks | Track performance |
| 6.5 | Calendar & Events | Earnings, macro events | 1 week | Event-aware trading |
| 6.6 | Deployment Prep | Security, Synology deploy | 1 week | Production-ready |
| 7 | Advanced AI | AI integrations | TBD | AI-powered automation |

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

## Phase 6: Trade Tracker ✅
**Goal**: Trade tracking, position sizing, performance analytics
**Status**: COMPLETE

### Deliverables

#### Backend
- [x] Trade model + CRUD endpoints
- [x] Trade matching service (FIFO for P&L calculation)
- [x] Performance analytics service
- [x] Position sizing calculator service
- [x] Portfolio summary endpoint

#### Frontend
- [x] Trades page with filterable list
- [x] Quick trade entry form
  - Select equity (with search)
  - Trade type (buy, sell, short, cover)
  - Quantity, price, fees
  - Date/time picker
  - Optional notes
- [x] Trade detail/edit modal
- [x] Quick add feature (Buy More/Sell buttons on positions)
- [x] P&L dashboard
  - Realized vs unrealized P&L
  - P&L by equity, sector
- [x] Performance analytics page
  - Win rate
  - Average gain/loss
  - Best/worst trades
  - Streak tracking
  - Profit factor
  - Performance by sector/equity
- [x] Position sizer tool with tooltips
  - Account size input
  - Risk percentage
  - Stop loss level
  - → Suggested position size

#### UI Improvements
- [x] Hamburger slide-out menu for mobile navigation
- [x] Responsive header with desktop horizontal nav

#### Data Model Additions
```
trades
├── id (PK)
├── user_id (FK)
├── equity_id (FK)
├── trade_type (enum: buy, sell, short, cover)
├── quantity (decimal)
├── price (decimal)
├── fees (decimal, default 0)
├── executed_at (timestamp)
├── notes (text, nullable)
├── watchlist_item_id (FK, nullable - links to thesis)
├── created_at
└── updated_at

trade_pairs (for P&L matching)
├── id (PK)
├── user_id (FK)
├── equity_id (FK)
├── open_trade_id (FK)
├── close_trade_id (FK)
├── quantity_matched (decimal)
├── realized_pnl (decimal)
├── holding_period_days (int)
└── calculated_at

positions (materialized view or calculated)
├── user_id
├── equity_id
├── quantity (net shares held)
├── avg_cost_basis
├── current_value
├── unrealized_pnl
└── last_updated
```

### Position Sizer Formulas
| Method | Formula |
|--------|---------|
| Fixed Risk | Position Size = (Account × Risk%) / (Entry - Stop) |
| Kelly Criterion | f* = (bp - q) / b where b=win/loss ratio, p=win rate, q=1-p |
| ATR-based | Position Size = (Account × Risk%) / (ATR × Multiplier) |

### Success Criteria
- [x] Log a buy trade for CCJ at $52.50
- [x] Log a sell trade for partial position
- [x] View realized P&L for the closed portion
- [x] View unrealized P&L for remaining position
- [x] See win rate and average gain across all trades
- [x] Calculate position size for a new trade with 2% risk

---

## Phase 6.5: Calendar & Events ✅
**Goal**: Economic calendar, earnings tracking, and event-aware trading
**Status**: COMPLETE

### Deliverables

#### Backend
- [x] Economic event model + CRUD endpoints
- [x] Earnings calendar service (via Yahoo Finance)
- [x] Macro events data source integration
- [x] Event aggregation endpoint (combines earnings + macro)
- [x] Watchlist events aggregation endpoint
- [x] Celery task for refreshing watchlist events (with rate limiting)

#### Frontend
- [x] Calendar page with month/week/list views
- [x] Event type filters (earnings, FOMC, CPI, etc.)
- [x] Watchlist events toggle (show only tracked equities)
- [x] Dashboard upcoming events widget
- [x] Equity detail events section
- [x] Per-item calendar tracking toggle on watchlist items
- [ ] (Stretch) Chart event markers

#### Data Model
```
economic_events
├── id (PK)
├── event_type (enum: earnings, fomc, cpi, nfp, gdp, etc.)
├── equity_id (FK, nullable - for earnings)
├── event_date (date)
├── event_time (time, nullable)
├── title
├── description (nullable)
├── actual_value (nullable - filled after event)
├── forecast_value (nullable)
├── previous_value (nullable)
├── importance (low, medium, high)
├── source (yahoo, manual, api)
├── created_at
└── updated_at
```

#### Event Types
| Type | Source | Frequency |
|------|--------|-----------|
| Earnings | Yahoo Finance | Per equity |
| FOMC | Manual/API | 8x/year |
| CPI | Manual/API | Monthly |
| NFP (Jobs) | Manual/API | Monthly |
| GDP | Manual/API | Quarterly |
| Ex-Dividend | Yahoo Finance | Per equity |
| Stock Split | Yahoo Finance | Per equity |

### Success Criteria
- [x] View calendar showing FOMC meetings for the year
- [x] See CCJ earnings date on equity detail page
- [x] Dashboard shows "Earnings this week" for watchlist items
- [x] Filter calendar to show only watchlist earnings
- [ ] (Stretch) See earnings marker on equity price chart

---

## Phase 6.6: Deployment Readiness ✅
**Goal**: Security hardening, production configuration, Synology deployment
**Status**: COMPLETE

### Deliverables

#### Security Hardening
- [x] Remove default secrets (fail if not configured in production)
- [x] Add login rate limiting (20/IP, 5/email per 15 min)
- [x] Add security headers middleware (X-Frame-Options, CSP, etc.)
- [x] Fix resource leaks (ThreadPoolExecutor shutdown)
- [ ] Add session cleanup task (future)

#### Production Configuration
- [x] Create docker-compose.prod.yml
- [x] Add Traefik configuration for HTTPS (Let's Encrypt)
- [x] Add init container for migrations
- [x] Create .env.production.example
- [x] Create production Dockerfiles (multi-stage builds)
- [x] Add next.config.js for standalone output

#### Database Seeding
- [x] Create production seed script (seed_demo_data.py)
- [x] Pre-load default ratios (10 common financial ratios)
- [x] Pre-load major macro events calendar (FOMC, CPI, NFP, GDP)

#### Backup & Monitoring
- [x] Add pg_dump backup script with rotation
- [x] Add restore script
- [x] Enhanced health endpoint (checks DB, Redis)

#### Documentation
- [x] Create DEPLOYMENT.md (Synology guide)
- [x] Create BACKUP.md
- [x] Create SECURITY.md

### Success Criteria
- [x] Application starts with production configuration
- [x] No hardcoded secrets or weak defaults in production
- [x] HTTPS configured with Let's Encrypt via Traefik
- [x] Backup scripts ready for automated daily backups
- [x] Health endpoint reports accurate system status

---

## Phase 7: Advanced AI (Future)
**Goal**: AI-powered analysis, automation, and integrations
**Depends on**: Resolving Claude OAuth/API access (see [Issue #001](./issues/001-claude-oauth-support.md))

### Prerequisites
Before starting Phase 7, one of the following must be completed:
1. Set up a Claude API proxy (OpenClawd, CLIProxyAPI)
2. Subscribe to standard Anthropic API billing
3. Anthropic adds OAuth token support for third-party integrations

### Potential Features

#### AI Trade Analysis
- [ ] Trade review (AI analyzes your entry/exit decisions)
- [ ] Pattern recognition (common mistakes, strengths)
- [ ] Trade journaling prompts (AI asks follow-up questions)

#### Market Intelligence
- [ ] Auto-summarize market news
- [ ] Earnings call summarization
- [ ] SEC filing analysis (10-K, 10-Q highlights)

#### Thesis Challenger
- [ ] Devil's advocate mode (challenges your investment thesis)
- [ ] Counter-argument generation
- [ ] Risk factor identification

#### Automation
- [ ] Scheduled portfolio reviews (weekly/monthly summaries)
- [ ] Alert-triggered analysis (AI comments on triggered alerts)
- [ ] Voice input for quick notes

#### Integrations
- [ ] Claude MCP server (Claude Code can query your portfolio)
- [ ] Export to Obsidian/Notion (AI-formatted summaries)

### Success Criteria
- AI reviews a completed trade and provides feedback
- Weekly portfolio summary generated automatically
- Ask AI "What are the risks to my uranium thesis?"
- Claude Code can query "What's my current exposure to energy sector?"

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
| **M6: "Trader"** | + 6 | Trade tracking, P&L, position sizing |
| **M6.5: "Event-Aware"** | + 6.5 | Calendar, earnings, macro events |
| **M6.6: "Deployed"** | + 6.6 | Security hardened, Synology ready |
| **M7: "Complete"** | + 7 | AI automation, integrations |

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
