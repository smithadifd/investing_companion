---
title: Equity dashboard
description: Per-ticker view combining a live quote header, interactive price chart, fundamental metrics, and backend-computed technical indicators.
---

Type a ticker into the search bar, select a result, and the equity dashboard loads everything about that symbol in one place: a live quote header, an interactive price chart with overlays, a fundamentals grid, and a four-indicator technical summary. All data flows from Yahoo Finance through the backend — the frontend never calls an external API directly.

## Search

The `EquitySearchInput` component fires against `GET /api/v1/equity/search?q=<query>` on every keystroke (minimum one character). The backend checks the local `equities` table first; if no rows match the symbol or name, it falls through to `YahooFinanceProvider.search()`. Results show the ticker symbol and company name in a dropdown. Selecting a result navigates to `/equity/[symbol]`.

## Quote header

`QuoteHeader` renders at the top of every equity page and draws from `GET /api/v1/equity/{symbol}` (the `EquityDetailResponse` shape). It shows:

- Current price and day change (absolute and percent), color-coded green/red
- Intraday open, high, low, and volume
- Market cap (when present in the quote)
- Sector and industry, sourced from the `Equity` database row

The quote itself is cached in Redis (key scoped to the symbol) with a TTL controlled by the `QUOTE_CACHE_TTL` setting. If Redis is unavailable, the service fetches live from Yahoo on every request.

## Price chart

The chart is rendered by `AdvancedChart`, which uses **lightweight-charts** (the TradingView open-source library) — not the TradingView widget embed. It supports two display modes: candlestick and line, toggled via `ChartControls`.

History is fetched from `GET /api/v1/equity/{symbol}/history` with `period` and `interval` query parameters. The `PeriodSelector` component offers eight periods: 1D, 5D, 1M, 3M, 6M, 1Y, 2Y, and 5Y. When you change period, the page automatically selects a sensible interval — 5-minute bars for 1D, hourly for 1M, daily for anything 3M and longer.

Overlay indicators are toggleable from the chart controls toolbar:

- **SMA** — simple moving averages at 20, 50, and 200 periods
- **EMA** — exponential moving averages at 12 and 26 periods
- **Bollinger Bands** — standard 20-period bands
- **RSI** — 14-period, rendered in a sub-pane below the price series
- **MACD** — 12/26/9, also in a sub-pane

All overlays require the 1D interval. Switching to an intraday interval (5m, 15m, 1h) hides the indicator data; a note in the UI explains why.

Technical indicator data for the chart comes from `GET /api/v1/equity/{symbol}/technicals?period=<period>`, which calls `TechnicalAnalysisService.calculate_all()` on the raw OHLCV history on the backend.

## Fundamentals tab

Selecting the Fundamentals tab shows `FundamentalsCard`, a grid of 13 metrics sourced from `GET /api/v1/equity/{symbol}` (the `fundamentals` field of `EquityDetailResponse`):

| Metric | Field |
| --- | --- |
| Market Cap | `market_cap` |
| P/E Ratio | `pe_ratio` |
| Forward P/E | `forward_pe` |
| PEG Ratio | `peg_ratio` |
| EPS (TTM) | `eps_ttm` |
| Dividend Yield | `dividend_yield` |
| Beta | `beta` |
| P/B Ratio | `price_to_book` |
| P/S Ratio | `price_to_sales` |
| 52W High | `week_52_high` |
| 52W Low | `week_52_low` |
| Avg Volume | `avg_volume` |
| Profit Margin | `profit_margin` |

All values come from Yahoo Finance via `YahooFinanceProvider.get_fundamentals()` and are cached separately from the quote. Fields that Yahoo does not return for a given ticker render as `--`.

The Fundamentals tab also includes a peer comparison panel (`PeerComparison`) that finds other equities in the same sector.

## Technical indicators summary

Below the chart (still on the Technical Analysis tab), `TechnicalSummaryCard` displays a four-cell snapshot driven by `GET /api/v1/equity/{symbol}/technicals/summary`. The backend runs `TechnicalAnalysisService.get_summary()` against one year of daily history and returns current values for:

- **RSI (14)** — with an `overbought`/`oversold`/`neutral` signal label
- **MACD** — current MACD line value shown alongside the signal line value
- **SMA 50** — price level with an up/down arrow indicating whether the current price is above or below
- **SMA 200** — same format as SMA 50

All indicator math runs in Python on the backend, not in the chart library.

## Related pages

- [Data flow](/architecture/data-flow/) — how live quote and history requests move from frontend to Yahoo and back
- [Data sources](/design-decisions/data-sources/) — why Yahoo Finance, rate limits, and caching strategy
- [Domain model](/architecture/domain-model/) — the `Equity` and `EquityFundamentals` database tables
