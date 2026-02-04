# Issue 007: News Integration

**Status:** Open
**Created:** 2026-02-04
**Priority:** Low
**Affects:** Equity page, potentially dashboard

## Summary

Add news feed integration to show relevant financial news for tracked equities and general market news.

## Current Behavior

- No news data displayed anywhere in the app
- Users must go to external sources for news context

## Proposed Solution

### Data Provider Options

| Provider | Pros | Cons |
|----------|------|------|
| NewsAPI.org | Free tier (100 req/day), easy API | Limited financial sources |
| Alpha Vantage News | Already have key, financial focus | Limited to 5 req/min |
| Yahoo Finance | Free, comes with yfinance | Unofficial, limited data |
| Seeking Alpha | Good analysis | Paid, scraping TOS issues |
| Finnhub | Free tier, real-time news | 60 req/min free |

**Recommendation:** Start with Alpha Vantage (already integrated) or Yahoo Finance (already using yfinance).

### Implementation

1. **Backend news endpoint:**
   ```python
   @router.get("/news/{symbol}")
   async def get_equity_news(symbol: str, limit: int = 10):
       # Fetch from provider
       # Cache for 15 minutes
       return news_items
   ```

2. **News data model:**
   ```python
   class NewsItem(BaseModel):
       title: str
       summary: Optional[str]
       url: str
       source: str
       published_at: datetime
       sentiment: Optional[str]  # positive/negative/neutral
       symbols: List[str]  # Related tickers
   ```

3. **Frontend components:**
   - `NewsCard` - Individual news item
   - `NewsFeed` - List of news items
   - News tab on equity detail page
   - Optional: News section on dashboard

### UI Design

```
┌─────────────────────────────────────────┐
│ 📰 Recent News                          │
├─────────────────────────────────────────┤
│ ┌─────────────────────────────────────┐ │
│ │ AAPL Reports Record Q4 Earnings     │ │
│ │ Reuters • 2 hours ago               │ │
│ │ Apple Inc reported quarterly...     │ │
│ └─────────────────────────────────────┘ │
│ ┌─────────────────────────────────────┐ │
│ │ Apple Announces New Product Line    │ │
│ │ Bloomberg • 5 hours ago             │ │
│ └─────────────────────────────────────┘ │
└─────────────────────────────────────────┘
```

## Files Affected

- `backend/app/services/data_providers/` - New news provider
- `backend/app/api/v1/endpoints/equity.py` - News endpoint
- `backend/app/schemas/` - News schemas
- `frontend/src/components/news/` - New components
- `frontend/src/app/equity/[symbol]/page.tsx` - News tab
- `frontend/src/lib/hooks/useNews.ts` - Data fetching hook

## Effort Estimate

- Backend provider + endpoint: 3-4 hours
- Data models + caching: 1-2 hours
- Frontend components: 3-4 hours
- Integration + styling: 2-3 hours
- Testing: 1-2 hours

**Total: ~10-15 hours (1.5-2 days)**

## Future Enhancements

- Sentiment analysis integration
- News-based alerts (e.g., "notify when AAPL mentioned")
- Market-wide news feed on dashboard
- Save/bookmark news articles
