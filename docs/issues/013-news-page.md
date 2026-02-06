# Issue 013: News Page & Catalyst Integration

## Status: Planned (Future)

## Problem
Discord notification summaries would benefit from brief catalyst/news notes next to big movers (e.g., "CCJ +4.2% - Kazatomprom cut 2026 guidance"). Currently there is no news data source integrated.

## Proposed Solution
Add a News page to the app and integrate a news data provider that can surface relevant headlines for watchlist symbols.

### Phase 1: News Data Provider
- Evaluate providers: Polygon.io (already have optional key), Benzinga, Alpha Vantage news, Finnhub
- Build a `NewsService` in `backend/app/services/news.py`
- Store/cache recent headlines per symbol
- API endpoint: `GET /api/v1/news?symbol=CCJ&limit=5`

### Phase 2: News Page
- Frontend page at `/news`
- Show recent headlines for all watchlist symbols
- Filter by watchlist / theme
- Link to original source

### Phase 3: Notification Integration
- When formatting Discord summaries, look up most recent headline for big movers
- Add brief catalyst note in parentheses: `CCJ +4.2% (Kazatomprom guidance cut)`
- Keep it short - truncate to ~40 chars

## Priority
Low - nice-to-have enhancement for notification quality. Core notification rewrite works without this.

## Dependencies
- Requires a news API key (Polygon free tier includes some news, or add Finnhub)
- Notification formatter already has placeholder pattern for catalyst notes
