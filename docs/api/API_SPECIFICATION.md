# API Specification

Base URL: `/api/v1`

## Overview

RESTful API with JSON request/response bodies. Authentication via JWT Bearer tokens (Phase 5+).

---

## Common Response Formats

### Success Response
```json
{
  "data": { ... },
  "meta": {
    "timestamp": "2025-01-31T12:00:00Z",
    "request_id": "uuid"
  }
}
```

### List Response
```json
{
  "data": [ ... ],
  "meta": {
    "total": 100,
    "page": 1,
    "per_page": 20,
    "pages": 5
  }
}
```

### Error Response
```json
{
  "error": {
    "code": "EQUITY_NOT_FOUND",
    "message": "Equity with symbol 'XYZ' not found",
    "details": { ... }
  }
}
```

---

## Endpoints by Phase

### Phase 1: Prototype

#### Equities

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/equity/search` | Search equities by name/symbol |
| GET | `/equity/{symbol}` | Get equity details |
| GET | `/equity/{symbol}/quote` | Get current quote |
| GET | `/equity/{symbol}/history` | Get price history |

**GET /equity/search**
```
Query Params:
  q: string (required) - Search query
  limit: int (default: 20) - Max results
  asset_type: string - Filter by type (stock, etf, etc.)

Response:
{
  "data": [
    {
      "symbol": "AAPL",
      "name": "Apple Inc.",
      "exchange": "NASDAQ",
      "asset_type": "stock"
    }
  ]
}
```

**GET /equity/{symbol}**
```
Response:
{
  "data": {
    "symbol": "AAPL",
    "name": "Apple Inc.",
    "exchange": "NASDAQ",
    "asset_type": "stock",
    "sector": "Technology",
    "industry": "Consumer Electronics",
    "quote": { ... },           // Embedded current quote
    "fundamentals": { ... }     // Embedded fundamentals
  }
}
```

**GET /equity/{symbol}/quote**
```
Response:
{
  "data": {
    "symbol": "AAPL",
    "price": 185.50,
    "change": 2.30,
    "change_percent": 1.26,
    "open": 183.00,
    "high": 186.20,
    "low": 182.80,
    "volume": 52000000,
    "market_cap": 2850000000000,
    "timestamp": "2025-01-31T16:00:00Z"
  }
}
```

**GET /equity/{symbol}/history**
```
Query Params:
  period: string - 1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, 10y, max
  interval: string - 1m, 5m, 15m, 30m, 1h, 1d, 1wk, 1mo

Response:
{
  "data": {
    "symbol": "AAPL",
    "interval": "1d",
    "history": [
      {
        "timestamp": "2025-01-30T00:00:00Z",
        "open": 182.00,
        "high": 184.50,
        "low": 181.20,
        "close": 183.20,
        "volume": 48000000
      }
    ]
  }
}
```

---

### Phase 2: MVP

#### Watchlists

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/watchlists` | List all watchlists |
| POST | `/watchlists` | Create watchlist |
| GET | `/watchlists/{id}` | Get watchlist with items |
| PUT | `/watchlists/{id}` | Update watchlist |
| DELETE | `/watchlists/{id}` | Delete watchlist |
| POST | `/watchlists/{id}/items` | Add item to watchlist |
| PUT | `/watchlists/{id}/items/{item_id}` | Update watchlist item |
| DELETE | `/watchlists/{id}/items/{item_id}` | Remove item |

**POST /watchlists**
```
Request:
{
  "name": "Uranium Plays",
  "description": "Nuclear renaissance thesis",
  "is_default": false
}

Response:
{
  "data": {
    "id": 1,
    "name": "Uranium Plays",
    "description": "Nuclear renaissance thesis",
    "is_default": false,
    "item_count": 0,
    "created_at": "2025-01-31T12:00:00Z"
  }
}
```

**POST /watchlists/{id}/items**
```
Request:
{
  "symbol": "CCJ",
  "notes": "Largest pure-play uranium producer",
  "target_price": 75.00,
  "thesis": "Supply deficit + demand growth from AI data centers"
}

Response:
{
  "data": {
    "id": 1,
    "watchlist_id": 1,
    "equity": {
      "symbol": "CCJ",
      "name": "Cameco Corporation",
      "price": 52.30
    },
    "notes": "Largest pure-play uranium producer",
    "target_price": 75.00,
    "thesis": "Supply deficit + demand growth from AI data centers",
    "added_at": "2025-01-31T12:00:00Z"
  }
}
```

#### Import/Export

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/import/watchlist` | Import watchlist from file |
| GET | `/export/watchlist/{id}` | Export watchlist |

**POST /import/watchlist**
```
Content-Type: multipart/form-data
  file: (CSV or JSON file)
  watchlist_id: int (optional, creates new if not provided)

CSV Format:
symbol,notes,target_price,thesis
AAPL,Core holding,200,Long-term compounder
CCJ,Uranium play,75,Nuclear thesis

Response:
{
  "data": {
    "watchlist_id": 1,
    "imported": 10,
    "skipped": 2,
    "errors": [
      {"symbol": "INVALID", "error": "Symbol not found"}
    ]
  }
}
```

#### Analysis

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/equity/{symbol}/technicals` | Get technical indicators |
| GET | `/equity/{symbol}/fundamentals` | Get fundamental analysis |
| GET | `/equity/{symbol}/peers` | Get peer comparison |

**GET /equity/{symbol}/technicals**
```
Query Params:
  indicators: string[] - sma_20, sma_50, sma_200, rsi, macd, bollinger

Response:
{
  "data": {
    "symbol": "AAPL",
    "indicators": {
      "sma_20": 182.50,
      "sma_50": 178.30,
      "sma_200": 172.00,
      "rsi_14": 58.5,
      "macd": {
        "macd": 2.1,
        "signal": 1.8,
        "histogram": 0.3
      }
    },
    "signals": {
      "trend": "bullish",
      "above_sma_200": true,
      "rsi_condition": "neutral"
    }
  }
}
```

---

### Phase 3: Intelligence

#### AI Analysis

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/ai/analyze` | AI analysis of equity/watchlist |
| GET | `/ai/analyze/stream` | SSE streaming analysis |

**POST /ai/analyze**
```
Request:
{
  "type": "equity",  // or "watchlist", "ratio", "custom"
  "target": "CCJ",   // symbol or watchlist_id
  "prompt": "What's the bull and bear case?",
  "include_context": true  // Include fundamentals, technicals
}

Response (non-streaming):
{
  "data": {
    "analysis": "## Bull Case\n\n...",
    "context_used": ["fundamentals", "technicals", "price_history"],
    "model": "claude-3-5-sonnet-20241022",
    "tokens_used": 1500
  }
}
```

**GET /ai/analyze/stream**
```
Query Params: Same as POST body

Response: Server-Sent Events
event: message
data: {"content": "## Bull Case\n\n"}

event: message
data: {"content": "Cameco is positioned..."}

event: done
data: {"tokens_used": 1500}
```

#### Ratios

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/ratios` | List all ratios |
| POST | `/ratios` | Create custom ratio |
| GET | `/ratios/{id}` | Get ratio details |
| GET | `/ratios/{id}/history` | Get ratio price history |
| PUT | `/ratios/{id}` | Update ratio |
| DELETE | `/ratios/{id}` | Delete ratio |
| POST | `/ratios/{id}/favorite` | Toggle favorite |

**GET /ratios/{id}/history**
```
Query Params:
  period: string - 1mo, 3mo, 6mo, 1y, 5y

Response:
{
  "data": {
    "ratio": {
      "id": 1,
      "name": "Gold/Silver",
      "numerator": "GLD",
      "denominator": "SLV"
    },
    "current_value": 84.5,
    "history": [
      {"timestamp": "2025-01-30", "value": 83.2},
      {"timestamp": "2025-01-29", "value": 84.0}
    ],
    "stats": {
      "high_52w": 92.0,
      "low_52w": 78.5,
      "avg_5y": 82.0
    }
  }
}
```

#### Market Overview

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/market/indices` | Get major indices |
| GET | `/market/sectors` | Get sector performance |
| GET | `/market/movers` | Get top gainers/losers |

**GET /market/sectors**
```
Query Params:
  period: string - 1d, 1w, 1mo, ytd, 1y

Response:
{
  "data": {
    "period": "1d",
    "sectors": [
      {"name": "Energy", "symbol": "XLE", "change_percent": 2.5, "rank": 1},
      {"name": "Financials", "symbol": "XLF", "change_percent": 1.2, "rank": 2},
      {"name": "Technology", "symbol": "XLK", "change_percent": -0.5, "rank": 11}
    ]
  }
}
```

---

### Phase 4: Alerts

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/alerts` | List all alerts |
| POST | `/alerts` | Create alert |
| GET | `/alerts/{id}` | Get alert details |
| PUT | `/alerts/{id}` | Update alert |
| DELETE | `/alerts/{id}` | Delete alert |
| POST | `/alerts/{id}/toggle` | Toggle active status |
| GET | `/alerts/{id}/history` | Get trigger history |

**POST /alerts**
```
Request:
{
  "name": "CCJ above $60",
  "equity_symbol": "CCJ",  // or "ratio_id": 1
  "condition_type": "ABOVE",
  "threshold_value": 60.00,
  "cooldown_minutes": 60,
  "notes": "Consider trimming position"
}

Response:
{
  "data": {
    "id": 1,
    "name": "CCJ above $60",
    "equity": {"symbol": "CCJ", "name": "Cameco"},
    "condition_type": "ABOVE",
    "threshold_value": 60.00,
    "is_active": true,
    "current_price": 52.30,
    "created_at": "2025-01-31T12:00:00Z"
  }
}
```

---

### Phase 5: Authentication

#### Auth Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/auth/register` | Create account |
| POST | `/auth/login` | Get JWT tokens |
| POST | `/auth/refresh` | Refresh access token |
| POST | `/auth/logout` | Revoke refresh token |
| GET | `/auth/me` | Get current user |
| PUT | `/auth/password` | Change password |
| GET | `/auth/sessions` | List active sessions |
| DELETE | `/auth/sessions/{id}` | Revoke session |

**POST /auth/login**
```
Request:
{
  "email": "user@example.com",
  "password": "securepassword"
}

Response:
{
  "data": {
    "access_token": "eyJ...",
    "refresh_token": "eyJ...",
    "token_type": "bearer",
    "expires_in": 1800
  }
}
```

**POST /auth/refresh**
```
Request:
{
  "refresh_token": "eyJ..."
}

Response:
{
  "data": {
    "access_token": "eyJ...",
    "token_type": "bearer",
    "expires_in": 1800
  }
}
```

#### Settings Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/settings` | Get user settings |
| PUT | `/settings` | Update settings |
| GET | `/settings/ai` | Get AI-specific settings |
| PUT | `/settings/ai` | Update AI settings |

**PUT /settings/ai**
```
Request:
{
  "claude_api_key": "sk-...",
  "discord_webhook_url": "https://discord.com/api/webhooks/..."
}
```

---

### Phase 6: Trades

#### Trade Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/trades` | List trades with filters |
| POST | `/trades` | Record trade |
| GET | `/trades/{id}` | Get trade details |
| PUT | `/trades/{id}` | Update trade |
| DELETE | `/trades/{id}` | Delete trade |

**POST /trades**
```
Request:
{
  "symbol": "CCJ",
  "trade_type": "BUY",  // BUY, SELL, SHORT, COVER
  "quantity": 100,
  "price": 52.30,
  "fees": 0.00,
  "executed_at": "2025-01-31T10:30:00Z",
  "notes": "Adding to uranium position"
}

Response:
{
  "data": {
    "id": "uuid",
    "equity": {"symbol": "CCJ", "name": "Cameco Corporation"},
    "trade_type": "BUY",
    "quantity": 100,
    "price": 52.30,
    "total_value": 5230.00,
    "fees": 0.00,
    "executed_at": "2025-01-31T10:30:00Z",
    "notes": "Adding to uranium position",
    "created_at": "2025-01-31T10:35:00Z"
  }
}
```

**GET /trades**
```
Query Params:
  symbol: string - Filter by equity symbol
  trade_type: string - Filter by type (BUY, SELL, etc.)
  start_date: date - Filter from date
  end_date: date - Filter to date
  limit: int - Max results (default 50, max 500)
  offset: int - Pagination offset
```

#### Portfolio Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/portfolio/positions` | Get current positions |
| GET | `/portfolio/summary` | Get P&L summary |
| GET | `/portfolio/performance` | Get performance metrics |

**GET /portfolio/positions**
```
Response:
{
  "data": [
    {
      "equity": {"symbol": "CCJ", "name": "Cameco", "current_price": 55.20},
      "quantity": 100,
      "avg_cost_basis": 52.30,
      "current_value": 5520.00,
      "unrealized_pnl": 290.00,
      "unrealized_pnl_percent": 5.54,
      "first_purchase": "2025-01-15T10:30:00Z"
    }
  ],
  "meta": {
    "total_value": 15230.00,
    "total_unrealized_pnl": 850.00
  }
}
```

**GET /portfolio/performance**
```
Response:
{
  "data": {
    "total_trades": 45,
    "winning_trades": 28,
    "losing_trades": 17,
    "win_rate": 0.622,
    "avg_win": 450.00,
    "avg_loss": -180.00,
    "profit_factor": 2.50,
    "total_realized_pnl": 4250.00,
    "best_trade": {"symbol": "NVDA", "pnl": 1200.00},
    "worst_trade": {"symbol": "COIN", "pnl": -350.00},
    "current_streak": {"type": "win", "count": 3}
  }
}
```

#### Position Sizing

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/tools/position-size` | Calculate position size |

**POST /tools/position-size**
```
Request:
{
  "account_size": 50000.00,
  "risk_percent": 2.0,
  "entry_price": 52.30,
  "stop_loss_price": 48.00
}

Response:
{
  "data": {
    "risk_amount": 1000.00,
    "position_size": 232,
    "position_value": 12133.60,
    "potential_loss": 998.16,
    "risk_reward_1_to_2": 60.60,
    "risk_reward_1_to_3": 65.20
  }
}
```

---

### Phase 6.5: Calendar & Events (Planned)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/events` | List events with filters |
| POST | `/events` | Create custom event |
| GET | `/events/{id}` | Get event details |
| PUT | `/events/{id}` | Update event |
| DELETE | `/events/{id}` | Delete custom event |
| GET | `/events/calendar` | Calendar view by month/week |
| GET | `/events/upcoming` | Next N days of events |
| GET | `/events/watchlist` | Events for watchlist equities |
| GET | `/equity/{symbol}/events` | Events for specific equity |

**GET /events/upcoming**
```
Query Params:
  days: int - Number of days ahead (default 7)
  event_types: string[] - Filter by types
  watchlist_only: bool - Only watchlist equities
  importance: string - Filter by importance

Response:
{
  "data": [
    {
      "id": "uuid",
      "event_type": "earnings",
      "equity": {"symbol": "CCJ", "name": "Cameco"},
      "event_date": "2025-02-05",
      "title": "Q4 2024 Earnings",
      "importance": "high",
      "is_confirmed": true
    },
    {
      "id": "uuid",
      "event_type": "fomc",
      "event_date": "2025-01-29",
      "title": "FOMC Meeting Day 2",
      "importance": "high"
    }
  ]
}
```

---

## Authentication (Phase 5+)

All endpoints except `/auth/*` require authentication.

```
Authorization: Bearer <access_token>
```

Access tokens expire in 15 minutes. Use refresh token to get new access token.

Single-user mode: Authentication can be disabled via environment variable for simpler setups.

---

## Rate Limiting

| Tier | Limit |
|------|-------|
| Unauthenticated | 30 req/min |
| Authenticated | 100 req/min |
| AI endpoints | 10 req/min |

Response headers:
```
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 95
X-RateLimit-Reset: 1706706000
```

---

## WebSocket (Future)

For real-time updates:

```
ws://localhost:8000/ws/quotes

// Subscribe to quotes
{"action": "subscribe", "symbols": ["AAPL", "CCJ"]}

// Receive updates
{"symbol": "AAPL", "price": 185.60, "timestamp": "..."}
```
