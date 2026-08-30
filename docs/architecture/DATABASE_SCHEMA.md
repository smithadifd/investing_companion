# Database Schema Design

## Overview

PostgreSQL 15+ with TimescaleDB extension for time-series data. Uses SQLAlchemy 2.0 with async support.

---

## Entity Relationship Diagram

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│     users       │────<│   watchlists    │────<│ watchlist_items │
└─────────────────┘     └─────────────────┘     └────────┬────────┘
        │                                                 │
        │               ┌─────────────────┐               │
        │               │    equities     │───────────────┘
        │               └────────┬────────┘
        │                        │
        │               ┌────────┴────────┐
        │               │                 │
        │     ┌─────────┴───────┐ ┌───────┴─────────┐
        │     │ equity_         │ │  price_history  │
        │     │ fundamentals    │ │  (hypertable)   │
        │     └─────────────────┘ └─────────────────┘
        │
        │     ┌─────────────────┐     ┌─────────────────┐
        └────<│     alerts      │────>│  alert_history  │
              └─────────────────┘     └─────────────────┘
                      │
              ┌───────┴───────┐
              │               │
        ┌─────┴─────┐   ┌─────┴─────┐
        │ equities  │   │  ratios   │
        └───────────┘   └───────────┘

┌─────────────────┐     ┌─────────────────┐
│ market_indices  │     │  user_settings  │
└─────────────────┘     └─────────────────┘

┌─────────────────┐     ┌─────────────────┐
│     trades      │────>│   trade_pairs   │  (Phase 6)
└─────────────────┘     └─────────────────┘
        │
        │  cash_balance / NAV are FOLDS over both, never stored
        v
┌──────────────────────┐     ┌─────────────────┐
│  cash_transactions   │────>│    accounts     │
└──────────────────────┘     └─────────────────┘
```

---

## Core Tables

### equities
Primary entity for stocks, ETFs, and other securities.

```sql
CREATE TABLE equities (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL UNIQUE,
    name VARCHAR(255) NOT NULL,
    exchange VARCHAR(50),
    asset_type VARCHAR(20) NOT NULL DEFAULT 'stock',
        -- ENUM: stock, etf, crypto, forex, commodity, index
    sector VARCHAR(100),
    industry VARCHAR(100),
    country VARCHAR(50) DEFAULT 'US',
    currency VARCHAR(10) DEFAULT 'USD',
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_equities_symbol ON equities(symbol);
CREATE INDEX idx_equities_sector ON equities(sector);
CREATE INDEX idx_equities_asset_type ON equities(asset_type);
```

### equity_fundamentals
One-to-one with equities. Cached fundamental data.

```sql
CREATE TABLE equity_fundamentals (
    id SERIAL PRIMARY KEY,
    equity_id INTEGER UNIQUE REFERENCES equities(id) ON DELETE CASCADE,

    -- Valuation
    market_cap BIGINT,
    enterprise_value BIGINT,
    pe_ratio DECIMAL(10, 2),
    forward_pe DECIMAL(10, 2),
    peg_ratio DECIMAL(10, 2),
    price_to_book DECIMAL(10, 2),
    price_to_sales DECIMAL(10, 2),

    -- Profitability
    eps_ttm DECIMAL(10, 2),
    eps_forward DECIMAL(10, 2),
    revenue_ttm BIGINT,
    net_income_ttm BIGINT,
    profit_margin DECIMAL(5, 2),
    operating_margin DECIMAL(5, 2),
    roe DECIMAL(5, 2),
    roa DECIMAL(5, 2),

    -- Dividends
    dividend_yield DECIMAL(5, 2),
    dividend_per_share DECIMAL(10, 4),
    payout_ratio DECIMAL(5, 2),
    ex_dividend_date DATE,

    -- Trading
    beta DECIMAL(5, 2),
    week_52_high DECIMAL(12, 2),
    week_52_low DECIMAL(12, 2),
    avg_volume_10d BIGINT,
    avg_volume_3m BIGINT,
    shares_outstanding BIGINT,
    float_shares BIGINT,
    short_ratio DECIMAL(5, 2),

    -- Metadata
    data_source VARCHAR(50),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_fundamentals_equity ON equity_fundamentals(equity_id);
```

### price_history
TimescaleDB hypertable for OHLCV data.

```sql
CREATE TABLE price_history (
    equity_id INTEGER NOT NULL REFERENCES equities(id) ON DELETE CASCADE,
    timestamp TIMESTAMPTZ NOT NULL,
    open DECIMAL(16, 6) NOT NULL,
    high DECIMAL(16, 6) NOT NULL,
    low DECIMAL(16, 6) NOT NULL,
    close DECIMAL(16, 6) NOT NULL,
    adj_close DECIMAL(16, 6),
    volume BIGINT,

    PRIMARY KEY (equity_id, timestamp)
);

-- Convert to hypertable (TimescaleDB)
SELECT create_hypertable('price_history', 'timestamp');

-- Compression policy (compress chunks older than 7 days)
ALTER TABLE price_history SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'equity_id'
);
SELECT add_compression_policy('price_history', INTERVAL '7 days');

-- Retention policy (optional, keep 10 years)
-- SELECT add_retention_policy('price_history', INTERVAL '10 years');

CREATE INDEX idx_price_history_equity_time ON price_history(equity_id, timestamp DESC);
```

---

## User & Authentication Tables (Phase 5)

### users

```sql
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    display_name VARCHAR(100),
    is_active BOOLEAN DEFAULT TRUE,
    is_admin BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    last_login_at TIMESTAMPTZ
);

CREATE INDEX idx_users_email ON users(email);
```

### user_settings

```sql
CREATE TABLE user_settings (
    id SERIAL PRIMARY KEY,
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    key VARCHAR(100) NOT NULL,
    value TEXT,  -- Encrypted for sensitive values
    is_encrypted BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(user_id, key)
);

-- Pre-auth fallback (single-user mode, user_id = NULL)
CREATE INDEX idx_settings_user_key ON user_settings(user_id, key);
```

**Common Settings Keys:**
| Key | Description | Encrypted |
|-----|-------------|-----------|
| `claude_api_key` | Anthropic API key | Yes |
| `polygon_api_key` | Polygon.io key | Yes |
| `alpha_vantage_key` | Alpha Vantage key | Yes |
| `discord_webhook` | Discord notification URL | Yes |
| `default_watchlist_id` | Default watchlist | No |
| `theme` | light/dark/system | No |
| `quote_refresh_interval` | Seconds between refreshes | No |

---

## Watchlist Tables

### watchlists

```sql
CREATE TABLE watchlists (
    id SERIAL PRIMARY KEY,
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,  -- NULL in single-user mode
    name VARCHAR(100) NOT NULL,
    description TEXT,
    is_default BOOLEAN DEFAULT FALSE,
    display_order INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_watchlists_user ON watchlists(user_id);
```

### watchlist_items

```sql
CREATE TABLE watchlist_items (
    id SERIAL PRIMARY KEY,
    watchlist_id INTEGER NOT NULL REFERENCES watchlists(id) ON DELETE CASCADE,
    equity_id INTEGER NOT NULL REFERENCES equities(id) ON DELETE CASCADE,
    notes TEXT,
    target_price DECIMAL(12, 2),
    stop_loss DECIMAL(12, 2),
    thesis TEXT,
    tags VARCHAR(255)[],  -- Array of tags
    added_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(watchlist_id, equity_id)
);

CREATE INDEX idx_watchlist_items_watchlist ON watchlist_items(watchlist_id);
CREATE INDEX idx_watchlist_items_equity ON watchlist_items(equity_id);
```

---

## Ratios Table

### ratios

```sql
CREATE TABLE ratios (
    id SERIAL PRIMARY KEY,
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,  -- NULL for system ratios
    name VARCHAR(100) NOT NULL,
    numerator_symbol VARCHAR(20) NOT NULL,
    denominator_symbol VARCHAR(20),  -- NULL for single-asset (e.g., DXY)
    description TEXT,
    category VARCHAR(50) NOT NULL,  -- commodity, equity, macro, crypto
    is_system BOOLEAN DEFAULT FALSE,  -- Pre-loaded ratios
    is_favorite BOOLEAN DEFAULT FALSE,
    display_order INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_ratios_user ON ratios(user_id);
CREATE INDEX idx_ratios_category ON ratios(category);
CREATE INDEX idx_ratios_favorite ON ratios(is_favorite) WHERE is_favorite = TRUE;
```

**System Ratios Seed Data:**
```sql
INSERT INTO ratios (name, numerator_symbol, denominator_symbol, category, is_system) VALUES
('Gold/Silver', 'GLD', 'SLV', 'commodity', TRUE),
('Gold/Bitcoin', 'GLD', 'BITO', 'crypto', TRUE),
('SPY/QQQ', 'SPY', 'QQQ', 'equity', TRUE),
('Value/Growth', 'VTV', 'VUG', 'equity', TRUE),
('Copper/Gold', 'CPER', 'GLD', 'macro', TRUE),
('Long/Short Bonds', 'TLT', 'SHY', 'macro', TRUE),
('US Dollar Index', 'UUP', NULL, 'macro', TRUE),
('Emerging/Developed', 'EEM', 'EFA', 'equity', TRUE),
('Small/Large Cap', 'IWM', 'SPY', 'equity', TRUE),
('Energy/S&P', 'XLE', 'SPY', 'equity', TRUE);
```

---

## Alerts Tables

### alerts

```sql
CREATE TYPE alert_condition_type AS ENUM (
    'ABOVE',
    'BELOW',
    'CROSSES_ABOVE',
    'CROSSES_BELOW',
    'PERCENT_UP',
    'PERCENT_DOWN'
);

CREATE TABLE alerts (
    id SERIAL PRIMARY KEY,
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL,

    -- Target (one of these should be set)
    equity_id INTEGER REFERENCES equities(id) ON DELETE CASCADE,
    ratio_id INTEGER REFERENCES ratios(id) ON DELETE CASCADE,

    -- Condition
    condition_type alert_condition_type NOT NULL,
    threshold_value DECIMAL(16, 6) NOT NULL,
    comparison_period_hours INTEGER,  -- For percent change

    -- Settings
    is_active BOOLEAN DEFAULT TRUE,
    cooldown_minutes INTEGER DEFAULT 60,
    notes TEXT,

    -- State
    last_triggered_at TIMESTAMPTZ,
    last_checked_at TIMESTAMPTZ,
    last_value DECIMAL(16, 6),

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    CONSTRAINT alert_target_check CHECK (
        (equity_id IS NOT NULL AND ratio_id IS NULL) OR
        (equity_id IS NULL AND ratio_id IS NOT NULL)
    )
);

CREATE INDEX idx_alerts_user ON alerts(user_id);
CREATE INDEX idx_alerts_active ON alerts(is_active) WHERE is_active = TRUE;
CREATE INDEX idx_alerts_equity ON alerts(equity_id) WHERE equity_id IS NOT NULL;
CREATE INDEX idx_alerts_ratio ON alerts(ratio_id) WHERE ratio_id IS NOT NULL;
```

### alert_history

```sql
CREATE TABLE alert_history (
    id SERIAL PRIMARY KEY,
    alert_id INTEGER NOT NULL REFERENCES alerts(id) ON DELETE CASCADE,
    triggered_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    triggered_value DECIMAL(16, 6) NOT NULL,
    threshold_value DECIMAL(16, 6) NOT NULL,
    notification_sent BOOLEAN DEFAULT FALSE,
    notification_channel VARCHAR(50),
    notification_error TEXT
);

CREATE INDEX idx_alert_history_alert ON alert_history(alert_id);
CREATE INDEX idx_alert_history_time ON alert_history(triggered_at DESC);
```

---

## Market Reference Tables

### market_indices

```sql
CREATE TABLE market_indices (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL UNIQUE,
    name VARCHAR(100) NOT NULL,
    region VARCHAR(50),  -- US, Europe, Asia, Global
    asset_class VARCHAR(50),  -- equity, bond, commodity, currency
    category VARCHAR(50),  -- major, sector, style
    display_order INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE
);

-- Seed data
INSERT INTO market_indices (symbol, name, region, asset_class, category, display_order) VALUES
-- Major US
('SPY', 'S&P 500', 'US', 'equity', 'major', 1),
('QQQ', 'NASDAQ 100', 'US', 'equity', 'major', 2),
('DIA', 'Dow Jones', 'US', 'equity', 'major', 3),
('IWM', 'Russell 2000', 'US', 'equity', 'major', 4),
-- Sectors
('XLF', 'Financials', 'US', 'equity', 'sector', 10),
('XLE', 'Energy', 'US', 'equity', 'sector', 11),
('XLK', 'Technology', 'US', 'equity', 'sector', 12),
('XLV', 'Healthcare', 'US', 'equity', 'sector', 13),
('XLI', 'Industrials', 'US', 'equity', 'sector', 14),
('XLP', 'Consumer Staples', 'US', 'equity', 'sector', 15),
('XLY', 'Consumer Discretionary', 'US', 'equity', 'sector', 16),
('XLU', 'Utilities', 'US', 'equity', 'sector', 17),
('XLB', 'Materials', 'US', 'equity', 'sector', 18),
('XLRE', 'Real Estate', 'US', 'equity', 'sector', 19),
('XLC', 'Communications', 'US', 'equity', 'sector', 20),
-- International
('EFA', 'EAFE (Developed)', 'Global', 'equity', 'major', 30),
('EEM', 'Emerging Markets', 'Global', 'equity', 'major', 31),
-- Bonds
('TLT', '20+ Year Treasury', 'US', 'bond', 'major', 40),
('IEF', '7-10 Year Treasury', 'US', 'bond', 'major', 41),
('LQD', 'Investment Grade Corp', 'US', 'bond', 'major', 42),
('HYG', 'High Yield Corp', 'US', 'bond', 'major', 43),
-- Commodities
('GLD', 'Gold', 'Global', 'commodity', 'major', 50),
('SLV', 'Silver', 'Global', 'commodity', 'major', 51),
('USO', 'Oil', 'Global', 'commodity', 'major', 52),
('UNG', 'Natural Gas', 'Global', 'commodity', 'major', 53),
-- Currency
('UUP', 'US Dollar', 'Global', 'currency', 'major', 60);
```

---

## Trade Tracking Tables (Phase 6)

### trades

The enum is named `trade_type_enum` and its values are **lowercase** — this
block previously declared `trade_type` with uppercase values, which never
matched the live type created by `20260201_004_add_trades_tables.py`.

```sql
CREATE TYPE trade_type_enum AS ENUM (
    'buy', 'sell', 'short', 'cover',
    -- added by 20260830_001 (total-return build)
    'dividend',    -- equity-scoped cash-in:      quantity = shares it paid on,
                   --                             price = per-share amount,
                   --                             fees = withholding
    'split',       -- equity-scoped share adjust: quantity = ratio (4 = 4:1,
                   --                             0.25 = 1:4 reverse), price = 0,
                   --                             account_id NULL (a split
                   --                             belongs to the security)
    'deposit',     -- account-scoped cash-in  -> cash_transactions, NOT trades
    'withdrawal'   -- account-scoped cash-out -> cash_transactions, NOT trades
);

CREATE TABLE trades (
    id SERIAL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    equity_id INTEGER NOT NULL REFERENCES equities(id) ON DELETE CASCADE,

    trade_type trade_type_enum NOT NULL,
    quantity NUMERIC(18, 8) NOT NULL,
    -- Deliberately NOT check-constrained: a zero cost basis is legitimate
    -- (vested RSU, gifted lot) and a `split` row's price is a designed 0.
    price NUMERIC(18, 8) NOT NULL,
    fees NUMERIC(12, 2) NOT NULL DEFAULT 0,

    executed_at TIMESTAMPTZ NOT NULL,
    -- NULL = the unassigned position bucket. SET NULL so deleting an account
    -- keeps its trade history.
    account_id INTEGER REFERENCES accounts(id) ON DELETE SET NULL,

    notes TEXT,
    watchlist_item_id INTEGER REFERENCES watchlist_items(id) ON DELETE SET NULL,

    -- Provenance / adoption (20260724_001)
    source VARCHAR(50) NOT NULL DEFAULT 'manual',
    is_synthetic BOOLEAN NOT NULL DEFAULT false,
    basis_is_estimated BOOLEAN NOT NULL DEFAULT false,
    source_import_run_id INTEGER REFERENCES broker_import_runs(id) ON DELETE SET NULL,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT ck_trades_quantity_positive CHECK (quantity > 0)
);

CREATE INDEX ix_trades_user_id ON trades(user_id);
CREATE INDEX ix_trades_equity_id ON trades(equity_id);
CREATE INDEX ix_trades_account_id ON trades(account_id);
CREATE INDEX idx_trades_user_equity ON trades(user_id, equity_id);
CREATE INDEX idx_trades_executed_at ON trades(executed_at);
CREATE INDEX idx_trades_user_executed ON trades(user_id, executed_at);
CREATE INDEX idx_trades_user_account_equity ON trades(user_id, account_id, equity_id);
CREATE UNIQUE INDEX uq_trades_synthetic_adoption
    ON trades(user_id, account_id, equity_id, source_import_run_id)
    WHERE is_synthetic;
```

Further shape rules (a `split` must have `price = 0` and no account; a
`dividend` must name an account; `deposit`/`withdrawal` must never appear here)
are enforced at the API layer today and are written as DB CHECKs held in
`backend/alembic/deferred/20260830_003_add_trade_type_shape_checks.py` pending
a prod-data inspection.

### trade_pairs
For P&L calculation, matching opens with closes.

```sql
CREATE TABLE trade_pairs (
    id SERIAL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    equity_id INTEGER NOT NULL REFERENCES equities(id),

    open_trade_id INTEGER NOT NULL REFERENCES trades(id),
    close_trade_id INTEGER NOT NULL REFERENCES trades(id),

    quantity_matched DECIMAL(16, 6) NOT NULL,
    realized_pnl DECIMAL(16, 2) NOT NULL,
    holding_period_days INTEGER,

    calculated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_trade_pairs_user ON trade_pairs(user_id);
CREATE INDEX idx_trade_pairs_equity ON trade_pairs(equity_id);
```

### cash_transactions

Per-account cash ledger — deposits and withdrawals only. Added by
`20260830_002` (total-return build, Surface 2).

**There is no stored balance anywhere.** `cash_balance` is a fold over this
table plus `trades` (see `backend/app/services/cash.py`), the same
derived-not-stored pattern as positions and `trade_pairs`. A dividend is NOT
double-entered: its single record is the `trades` row, and its cash leg is
computed, never written here.

```sql
CREATE TABLE cash_transactions (
    id SERIAL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    -- NOT NULL with CASCADE, unlike trades.account_id: cash that belongs to no
    -- account is meaningless, and its history describes nothing else.
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,

    -- Reuses trade_type_enum; the CHECK below is what narrows it to cash.
    kind trade_type_enum NOT NULL,
    -- Unsigned magnitude; direction lives in `kind`.
    amount NUMERIC(18, 2) NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL,
    notes TEXT,

    -- Provenance, mirroring trades
    source VARCHAR(50) NOT NULL DEFAULT 'manual',
    source_import_run_id INTEGER REFERENCES broker_import_runs(id) ON DELETE SET NULL,
    -- The broker's own (account-scoped) transaction id; NULL for a hand entry.
    -- THIS is the backfill's idempotency key, not source_import_run_id, which
    -- is a different value on every pull.
    external_transaction_id VARCHAR(64),

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT ck_cash_transactions_amount_positive CHECK (amount > 0),
    CONSTRAINT ck_cash_transactions_kind_is_cash
        CHECK (kind IN ('deposit', 'withdrawal'))
);

CREATE INDEX ix_cash_transactions_user_id ON cash_transactions(user_id);
CREATE INDEX ix_cash_transactions_account_id ON cash_transactions(account_id);
CREATE INDEX idx_cash_transactions_user_account_time
    ON cash_transactions(user_id, account_id, occurred_at);
CREATE UNIQUE INDEX uq_cash_transactions_external_id
    ON cash_transactions(user_id, external_transaction_id)
    WHERE external_transaction_id IS NOT NULL;
```

---

## Migrations Strategy

Using Alembic for schema versioning.

```bash
# Initialize
alembic init alembic

# Create migration
alembic revision --autogenerate -m "add_equity_tables"

# Apply migrations
alembic upgrade head

# Rollback
alembic downgrade -1
```

**Migration Naming Convention:**
```
{phase}_{sequence}_{description}.py

Examples:
p1_001_create_equities.py
p1_002_create_price_history.py
p2_001_create_watchlists.py
```

---

## Performance Considerations

1. **TimescaleDB Compression**: Price history compressed after 7 days
2. **Indexes**: Covering indexes for common query patterns
3. **Partitioning**: Handled by TimescaleDB for price_history
4. **Connection Pooling**: Use SQLAlchemy's pool (pool_size=5, max_overflow=10)
5. **Query Optimization**: EXPLAIN ANALYZE for slow queries

---

## Backup Strategy

```bash
# Daily backup script
pg_dump -Fc investing_companion > backup_$(date +%Y%m%d).dump

# Restore
pg_restore -d investing_companion backup_20250131.dump
```

Recommended: Automate with cron, store on external drive or cloud.
