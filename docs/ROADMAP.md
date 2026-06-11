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
| 8 | Alert Trust & Quick Wins | Alert correctness + UX | 3-5 days | Every alert works |
| 9 | Extended Hours & Overnight | Pre/post-market data, futures proxy | 1-2 weeks | No more overnight blindness |
| 10 | Daily Command Center | Dashboard + notifications overhaul | 1-2 weeks | Actionable daily driver |
| 11 | Metrics That Matter | Risk, drawdown, exposure metrics | 1 week | Honest portfolio picture |

**Recommended order (2026-06-11):** 8 → 9 → 10 → 7 → 11. Phase 8 fixes the trust
foundation (crisis-playbook alerts are currently non-functional), Phase 9 builds the data layer
Phases 10 and 7 consume, and Phase 7's AI features land best once the command center gives them
surfaces to render into. Maintenance track (Next.js 16 upgrade, dependency bumps, issue #10 git
history scrub) interleaves between phases.

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
| `PERCENT_FROM_HIGH` | -10% from 52-week high (added Phase 8) |
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

### Deployment Execution (2026-02-01)
- [x] Deployed to Synology NAS
- [x] Created `docker-compose.local.yml` for local network (no Traefik)
- [x] Resolved build issues (TypeScript, Docker Compose v1, Next.js env vars)
- [x] Updated Next.js to 14.2.29 (security fix)
- [x] Disabled registration after account creation
- [ ] Set up automated backups via Task Scheduler
- [x] Configure Discord webhook for alerts (via Settings UI)

See [Session Notes](./sessions/2026-02-01-synology-deployment.md) for details.

### Dependency Maintenance (2026-02-06)
- [x] Merged safe Dependabot PRs (date-fns 4, tailwind-merge 3, lucide-react 0.563)
- [x] Bumped Docker base images: Python 3.11→3.12, Node 20→22 LTS
- [x] Aligned CI workflow with Docker versions (Python 3.12, Node 22)
- [x] Configured Dependabot ignore rules for breaking major versions
- [x] Created upgrade plan: `docs/plans/nextjs-16-upgrade.md` (Next.js 16 + React 19 + ESLint 9)
- [ ] Execute Next.js 16 upgrade (see plan)

---

## Phase 7: Advanced AI
**Goal**: AI-powered analysis, automation, and integrations
**Status**: UNBLOCKED (decision 2026-06-11) — recommended after Phase 10

### Prerequisites — RESOLVED
Original blocker: Claude Max OAuth tokens are not accepted by the Anthropic API (see
[Issue #001](./issues/001-claude-oauth-support.md)). Decision (2026-06-11): use a **standard
API key from console.anthropic.com with a hard monthly spend cap** (~$5-10). Cost controls:
- Spend cap configured in the Anthropic console (hard limit, not advisory)
- Default to Haiku for scheduled/routine summaries (morning brief, EOD recap)
- Sonnet or better only for on-demand deep analysis the user explicitly triggers
- Keep the existing 1-hour response cache; track token usage in a `usage_log` table and
  surface month-to-date spend in Settings
- API key remains per-user and optional (encrypted in `user_settings`) — AI features degrade
  gracefully when absent, consistent with the free-core principle (see Phase 8 preamble)

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

## Product Principles (codified 2026-06-11)

These govern Phases 8+ and any future feature decisions:

1. **Free core, opt-in depth.** A working install never requires a paid subscription or an
   external account. Yahoo Finance + Finnhub free tiers power the base experience. Anything
   that costs money (Anthropic API key) or requires an account the user may not have (Schwab
   brokerage for extended-hours data) is *additive*: configured per-user in Settings, with
   graceful degradation when absent. No feature gates the base experience behind a paid dep.
2. **Actionable over informational.** Every dashboard card and notification should answer
   "what, if anything, should I do?" — with a deep link to the place to act, not just data.
3. **Alerts must be trustworthy.** A silently broken alert is worse than no alert (false
   confidence during exactly the scenario it was built for). Alert-correctness bugs outrank
   new features.

---

## Phase 8: Alert Trust & Quick Wins
**Goal**: Every configured alert actually works, and acting on one takes a single click

### Deliverables

#### Alert Correctness
- [ ] Fix `percent_up`/`percent_down` ignoring `comparison_period` (#48 — closed but fix not
      verified on prod; unblocks the 4 crisis-playbook SPY/HYG alerts)
- [ ] Fix forex symbol resolution in ratios (#49 — map `USD/JPY` → yfinance `JPY=X` format)
- [ ] New condition type: `PERCENT_FROM_HIGH` (#50 — drawdown from 52-week high; completes
      the crisis-playbook tier system)
- [ ] New condition type: `TARGET_PRICE` hit (watchlist items already store `target_price`;
      nothing alerts when it's reached)
- [ ] Backtest harness: replay historical prices through the evaluator to prove conditions
      fire when they should (regression suite for alert logic)

#### Alert UX
- [ ] Alert history filtering (symbol, date range, status) — currently 1000+ unfiltered rows
- [ ] Deep links: Discord notification and dashboard feed entries link to the equity page
      with alert context (threshold vs triggered value, attached notes/thesis)
- [ ] Discord batching: multiple alerts triggering in the same check cycle send one grouped
      message (no webhook spam during a broad selloff — exactly when alerts cluster)
- [ ] Timezone setting in UI (morning pulse / EOD wrap times are currently hardcoded ET)

### Success Criteria
- "SPY -7% (1m)" crisis alert fires correctly against replayed historical data
- "CCJ hit target $95" arrives in Discord with a link that opens CCJ with the thesis visible
- A 10-alert simultaneous trigger produces one Discord message, not ten

---

## Phase 9: Extended Hours & Overnight Awareness
**Goal**: Know what happened (and what's happening) outside regular trading hours, at $0 base cost

### Background (research 2026-06-11)
True overnight (8pm-4am ET) single-stock data is Blue Ocean ATS, redistributed only at
enterprise pricing (Databento/QUODD/Bloomberg, $500+/mo) — out of scope. The pragmatic stack:
- **Pre/post-market (4am-9:30am, 4pm-8pm):** yfinance `prepost=True` (free, unofficial) and
  Finnhub free tier (real-time last price, 60 req/min, WebSocket up to 50 symbols) cover the
  base. **Schwab Trader API** (free with a brokerage account, 120 req/min, `schwab-py`) is the
  premium opt-in: real-time Level 1 quotes across all sessions.
- **Overnight (8pm-4am):** futures as proxy (ES/NQ/RTY — already fetched for the morning
  pulse) for market direction; individual-stock overnight moves are caught at 4am via
  pre-market data.

### Deliverables

#### Data Layer
- [ ] Session-aware quote model: extend provider interface with `get_extended_quote()`
      returning session (pre/regular/post), extended-hours price, and change vs regular close
- [ ] Finnhub quote provider (key already wired for news; add quotes with graceful fallback)
- [ ] Schwab provider as **opt-in authenticated provider** (per-user OAuth setup in Settings,
      `schwab-py`; app fully functional without it per free-core principle)
- [ ] Store extended-hours snapshots (new `session` column on `price_history` or a dedicated
      hypertable) so pre-market moves are queryable, not just observed
- [ ] Capture overnight futures session (ES/NQ/RTY 6pm-9:30am range) as stored snapshots

#### Features on Top
- [ ] Morning pulse v2: pre-market movers from watchlists (gap up/down vs prior close),
      overnight futures summary, earnings-reaction flags ("XYZ reported last night, -8% pre")
- [ ] Extended-hours alert checks: opt-in `check_extended_hours` flag per alert (evaluated
      during pre/post sessions via Finnhub/Schwab)
- [ ] Equity page: pre/post-market price line when outside regular hours

### Success Criteria
- 8:00 AM pulse shows "CCJ -6.2% pre-market on earnings" before the open, with a link
- An `ABOVE` alert with extended-hours enabled fires at 7 AM, not 9:35 AM
- A user with no Schwab account and no Finnhub key still gets the futures-based pulse

---

## Phase 10: Daily Command Center
**Goal**: The dashboard and notifications answer "what needs my attention right now"

### Deliverables

#### Dashboard
- [ ] "Needs attention" triage stack as the primary dashboard element: ranked cards for
      triggered alerts, target-price hits, watchlist earnings today, outsized movers with a
      thesis attached — each with context and a one-click path to act
- [ ] Deep links everywhere: every mover/event/alert card opens the equity page with the
      relevant panel (thesis, alert, calendar) focused
- [ ] Quick actions on cards: log trade, snooze/adjust alert, edit target — without leaving
      the dashboard
- [ ] Data freshness indicators (last-sync stamps; manual refresh for calendar events instead
      of waiting for the 10 PM UTC batch)

#### Notifications
- [ ] In-app notification center with parity to Discord (morning pulse and EOD wrap rendered
      in-app, not webhook-only)
- [ ] EOD wrap v2: portfolio day P&L, alert summary, after-hours movers, tomorrow's calendar
- [ ] Per-category notification routing (which events go to Discord vs in-app only)

### Success Criteria
- Opening the dashboard at 9 AM answers "what changed and what should I look at" in one screen
- Acting on a triggered alert (view → decide → log trade or adjust alert) takes ≤2 clicks

---

## Phase 11: Metrics That Matter
**Goal**: An honest picture of risk and progress, not just P&L

### Deliverables
- [ ] Position drawdown tracking: peak-since-entry and current drawdown per position
- [ ] Target progress: price vs `target_price` on watchlist items (and % to target)
- [ ] Exposure view: portfolio concentration by sector and by watchlist theme (uranium, REE,
      precious metals, …) vs cash/dry powder
- [ ] R-multiple per trade (risk defined at entry via position sizer → realized R on close)
      and expectancy in performance analytics
- [ ] Ratio precompute: nightly Celery task materializes ratio history (fixes slow first
      load; on-demand fallback stays)
- [ ] Portfolio max-drawdown and equity curve from trade history

### Success Criteria
- "What's my uranium exposure as % of portfolio?" answered by a dashboard card
- Performance page shows expectancy and average R, not just win rate

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
