# Issue 006: Data Caching and Background Updates

**Status:** Partially Resolved
**Created:** 2026-02-04
**Updated:** 2026-02-04
**Priority:** Medium (downgraded - basic caching implemented)
**Affects:** Performance, Data freshness

## Summary

Implement Redis caching for market data to improve load times and reduce Yahoo Finance API calls. Data should update in the background to keep cached values fresh.

## What's Been Done (2026-02-04)

Basic Redis caching implemented directly in `YahooFinanceProvider`:

- **Quotes**: 5-minute TTL (cache key: `quote:{symbol}`)
- **Fundamentals**: 1-hour TTL (cache key: `fundamentals:{symbol}`)

Performance improvement: ~22x faster for cached requests (440ms → 20ms).

## What Remains (Optional Enhancements)

## Proposed Enhancements

### Cache Strategy

| Data Type | TTL | Background Refresh |
|-----------|-----|-------------------|
| Quotes (price, change) | 1-5 min during market hours | Every 1 min |
| Fundamentals | 1 hour | Every 30 min |
| Historical data | 24 hours | Once daily |
| Search results | 1 hour | N/A |

### Implementation

1. **Add cache layer to data providers:**
   ```python
   class CachedYahooProvider:
       def __init__(self, yahoo: YahooFinanceProvider, redis: Redis):
           self.yahoo = yahoo
           self.redis = redis

       async def get_quote(self, symbol: str) -> Quote:
           cache_key = f"quote:{symbol}"
           cached = await self.redis.get(cache_key)
           if cached:
               return Quote.model_validate_json(cached)

           quote = await self.yahoo.get_quote(symbol)
           await self.redis.setex(cache_key, 300, quote.model_dump_json())
           return quote
   ```

2. **Background refresh task:**
   ```python
   @celery_app.task
   def refresh_watchlist_quotes():
       # Get all symbols from all watchlists
       # Batch fetch quotes
       # Update cache
   ```

3. **Add `last_updated` to responses:**
   ```python
   class QuoteResponse(BaseModel):
       # ... existing fields
       cached_at: Optional[datetime] = None
       data_age_seconds: Optional[int] = None
   ```

### Market Hours Awareness

- More aggressive caching outside market hours (9:30 AM - 4:00 PM ET)
- After-hours: 15-minute TTL
- Weekends/holidays: 1-hour TTL

## Files Affected

- `backend/app/services/data_providers/yahoo.py` - Add cache wrapper
- `backend/app/services/cache.py` - Extend caching utilities
- `backend/app/tasks/` - Background refresh tasks
- `backend/app/schemas/equity.py` - Add timestamp fields
- Frontend components - Display "Updated X ago"

## Effort Estimate

- Cache layer implementation: 3-4 hours
- Background tasks: 2-3 hours
- Timestamp tracking: 1-2 hours
- Frontend display: 1-2 hours
- Testing: 2-3 hours

**Total: ~6-10 hours (remaining work)**

## Considerations

- Memory usage: Monitor Redis memory with many symbols
- Cache invalidation: How to force refresh if needed
- Error handling: What to return if cache and API both fail (currently falls back to API)
- Rate limiting: Still need to respect Yahoo's unofficial limits

## Related Issues

- Issue 017 (last updated timestamp - optional enhancement)
