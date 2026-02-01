# Phase 6.5: Calendar & Events

**Goal**: Add economic calendar, earnings tracking, and event-aware trading capabilities.

**Status**: PLANNED

---

## Overview

Phase 6.5 adds event awareness to the investing companion, helping users track:
- Earnings dates for equities they follow
- Major macro economic events (FOMC, CPI, NFP, GDP)
- Dividend ex-dates and stock splits
- Custom events/reminders

This enables better trade planning around catalysts and risk management during volatile periods.

---

## Data Sources

### Earnings & Corporate Events
**Primary**: Yahoo Finance (via yfinance)
- `ticker.calendar` - Upcoming earnings, ex-dividend dates
- `ticker.actions` - Historical dividends, splits

**Limitations**:
- Only provides next upcoming earnings (not historical calendar)
- Ex-dividend dates available
- No earnings surprise data in free tier

### Macro Economic Events
**Primary**: Manual seed + user additions
- Pre-seed known FOMC meeting dates (published yearly)
- Pre-seed typical CPI/NFP release schedule
- Allow users to add custom events

**Future Enhancement**: Alpha Vantage economic calendar API (requires paid tier)

---

## Data Model

### Economic Events Table
```sql
CREATE TABLE economic_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type VARCHAR(50) NOT NULL,  -- earnings, fomc, cpi, nfp, gdp, ex_dividend, split, custom
    equity_id UUID REFERENCES equities(id) ON DELETE CASCADE,  -- NULL for macro events
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,  -- NULL for system events

    event_date DATE NOT NULL,
    event_time TIME,  -- NULL if time unknown
    all_day BOOLEAN DEFAULT TRUE,

    title VARCHAR(255) NOT NULL,
    description TEXT,

    -- For economic releases
    actual_value DECIMAL(20, 4),
    forecast_value DECIMAL(20, 4),
    previous_value DECIMAL(20, 4),

    -- Metadata
    importance VARCHAR(10) DEFAULT 'medium',  -- low, medium, high
    source VARCHAR(50) DEFAULT 'manual',  -- yahoo, manual, alpha_vantage
    is_confirmed BOOLEAN DEFAULT TRUE,  -- earnings dates can be tentative

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    CONSTRAINT valid_importance CHECK (importance IN ('low', 'medium', 'high')),
    CONSTRAINT valid_event_type CHECK (event_type IN (
        'earnings', 'fomc', 'cpi', 'nfp', 'gdp', 'pce', 'retail_sales',
        'ex_dividend', 'split', 'ipo', 'custom'
    ))
);

-- Indexes
CREATE INDEX idx_economic_events_date ON economic_events(event_date);
CREATE INDEX idx_economic_events_equity ON economic_events(equity_id) WHERE equity_id IS NOT NULL;
CREATE INDEX idx_economic_events_user ON economic_events(user_id) WHERE user_id IS NOT NULL;
CREATE INDEX idx_economic_events_type ON economic_events(event_type);
```

### Event Types

| Type | Scope | Source | Auto-Refresh |
|------|-------|--------|--------------|
| `earnings` | Per equity | Yahoo Finance | Yes (daily) |
| `ex_dividend` | Per equity | Yahoo Finance | Yes (daily) |
| `split` | Per equity | Yahoo Finance | Yes (daily) |
| `fomc` | Global | Seed data | No (manual yearly) |
| `cpi` | Global | Seed data | No (manual yearly) |
| `nfp` | Global | Seed data | No (manual yearly) |
| `gdp` | Global | Seed data | No (manual yearly) |
| `pce` | Global | Seed data | No (manual yearly) |
| `retail_sales` | Global | Seed data | No (manual yearly) |
| `custom` | Per user | User input | No |

---

## API Endpoints

### Events CRUD
```
GET    /api/v1/events                    # List events with filters
GET    /api/v1/events/{id}               # Get single event
POST   /api/v1/events                    # Create custom event
PUT    /api/v1/events/{id}               # Update event
DELETE /api/v1/events/{id}               # Delete event (custom only)
```

### Specialized Endpoints
```
GET    /api/v1/events/calendar           # Calendar view (by month/week)
GET    /api/v1/events/upcoming           # Next N days of events
GET    /api/v1/events/watchlist          # Events for watchlist equities
GET    /api/v1/equity/{symbol}/events    # Events for specific equity
```

### Query Parameters
| Param | Type | Description |
|-------|------|-------------|
| `start_date` | date | Filter events from this date |
| `end_date` | date | Filter events until this date |
| `event_types` | string[] | Filter by event type(s) |
| `equity_id` | uuid | Filter by equity |
| `watchlist_id` | uuid | Filter by watchlist equities |
| `importance` | string | Filter by importance level |
| `include_past` | bool | Include past events (default false for upcoming) |

---

## Backend Implementation

### 1. Model (`backend/app/db/models/economic_event.py`)
- SQLAlchemy model matching schema above
- Enum for event types
- Enum for importance levels

### 2. Schemas (`backend/app/schemas/economic_event.py`)
- `EconomicEventCreate` - For creating custom events
- `EconomicEventUpdate` - For updating events
- `EconomicEventResponse` - Response with equity info
- `CalendarResponse` - Grouped by date for calendar view
- `UpcomingEventsResponse` - For dashboard widget

### 3. Service (`backend/app/services/economic_event.py`)
- CRUD operations
- Calendar aggregation logic
- Watchlist event aggregation
- Event deduplication (prevent duplicate earnings entries)

### 4. Yahoo Integration (`backend/app/services/data_providers/yahoo.py`)
- Add `get_calendar(symbol)` method
- Returns earnings date, ex-dividend date
- Cache for 24 hours

### 5. Celery Task (`backend/app/tasks/events.py`)
- Daily task to refresh earnings dates for tracked equities
- Runs at market close (4 PM ET)
- Only refreshes equities in active watchlists

### 6. Seed Script (`backend/scripts/seed_events.py`)
- Pre-load 2025-2026 FOMC meeting dates
- Pre-load typical CPI/NFP release schedule
- Idempotent (safe to run multiple times)

---

## Frontend Implementation

### 1. Calendar Page (`/calendar`)
- Month view (default)
- Week view
- List/agenda view
- Event type color coding
- Click event for details modal
- Filter sidebar:
  - Event types (checkboxes)
  - Importance level
  - Watchlist only toggle

### 2. Dashboard Widget
- "Upcoming Events" card
- Shows next 7 days
- Prioritizes high importance + watchlist earnings
- Quick link to full calendar

### 3. Equity Detail Integration
- Events tab or section on equity page
- Shows upcoming: earnings, ex-dividend, splits
- Shows past events with actual values (if available)

### 4. Watchlist Integration
- Optional column showing next event date
- "Events" badge on watchlist items with upcoming events

### 5. (Stretch) Chart Markers
- Vertical lines on price chart for past events
- Earnings: blue
- Dividends: green
- FOMC: orange
- Hover for details

---

## UI Components

### EventCard
```tsx
interface EventCardProps {
  event: EconomicEvent;
  showEquity?: boolean;  // Show equity name for aggregated views
  compact?: boolean;     // For dashboard widget
}
```

### CalendarView
```tsx
interface CalendarViewProps {
  events: EconomicEvent[];
  view: 'month' | 'week' | 'list';
  onDateSelect: (date: Date) => void;
  onEventClick: (event: EconomicEvent) => void;
}
```

### EventFilters
```tsx
interface EventFiltersProps {
  selectedTypes: EventType[];
  watchlistOnly: boolean;
  importance: Importance | 'all';
  onFilterChange: (filters: EventFilters) => void;
}
```

---

## Event Type Styling

| Type | Color | Icon |
|------|-------|------|
| Earnings | Blue (#3B82F6) | 📊 Chart |
| FOMC | Purple (#8B5CF6) | 🏛️ Bank |
| CPI | Orange (#F97316) | 📈 Trending |
| NFP | Green (#22C55E) | 👥 People |
| GDP | Yellow (#EAB308) | 💰 Money |
| Ex-Dividend | Teal (#14B8A6) | 💵 Dollar |
| Split | Pink (#EC4899) | ✂️ Scissors |
| Custom | Gray (#6B7280) | 📌 Pin |

---

## Seed Data: 2025-2026 FOMC Meetings

```python
FOMC_DATES_2025 = [
    ("2025-01-28", "2025-01-29"),  # Jan 28-29
    ("2025-03-18", "2025-03-19"),  # Mar 18-19
    ("2025-05-06", "2025-05-07"),  # May 6-7
    ("2025-06-17", "2025-06-18"),  # Jun 17-18
    ("2025-07-29", "2025-07-30"),  # Jul 29-30
    ("2025-09-16", "2025-09-17"),  # Sep 16-17
    ("2025-11-04", "2025-11-05"),  # Nov 4-5
    ("2025-12-16", "2025-12-17"),  # Dec 16-17
]

# Note: 2026 dates typically released in late 2025
```

---

## Implementation Order

### Step 1: Database & Model
1. Create migration for economic_events table
2. Create SQLAlchemy model
3. Create Pydantic schemas

### Step 2: Core Service
1. Implement CRUD operations
2. Implement calendar aggregation
3. Add Yahoo calendar integration

### Step 3: API Endpoints
1. Basic CRUD endpoints
2. Calendar endpoint
3. Upcoming events endpoint
4. Equity events endpoint
5. Watchlist events endpoint

### Step 4: Seed Data
1. Create seed script for FOMC dates
2. Add typical macro event schedule

### Step 5: Frontend - Calendar Page
1. Calendar layout with month view
2. Event cards and details modal
3. Filter sidebar
4. Week and list views

### Step 6: Frontend - Integrations
1. Dashboard widget
2. Equity detail events section
3. Watchlist events indicator

### Step 7: Background Tasks
1. Daily earnings refresh task
2. Add to Celery Beat schedule

### Step 8: (Stretch) Chart Markers
1. Chart event overlay component
2. Integration with existing charts

---

## Success Criteria

- [ ] View calendar showing FOMC meetings for 2025
- [ ] See next earnings date for any equity
- [ ] Dashboard shows upcoming events for watchlist items
- [ ] Add custom event (e.g., "Quarterly portfolio review")
- [ ] Filter calendar to show only earnings
- [ ] Filter calendar to show only watchlist equities
- [ ] Events auto-refresh daily for tracked equities

### Stretch Goals
- [ ] Event markers visible on equity price chart
- [ ] Earnings history with surprise data
- [ ] Event notifications via alerts system

---

## Testing Checklist

### Backend
- [ ] Event CRUD operations
- [ ] Calendar date range queries
- [ ] Watchlist event aggregation
- [ ] Yahoo calendar data parsing
- [ ] Seed script idempotency

### Frontend
- [ ] Calendar navigation (month/week/list)
- [ ] Event filtering
- [ ] Event creation modal
- [ ] Dashboard widget display
- [ ] Mobile responsiveness

---

## Future Enhancements (Phase 7+)

1. **Alpha Vantage Integration**: Real economic calendar API
2. **Earnings Whisper**: Expected vs actual tracking
3. **Event Alerts**: Notify before important events
4. **AI Integration**: "What events should I watch this week?"
5. **Historical Analysis**: How did price react to past earnings?
