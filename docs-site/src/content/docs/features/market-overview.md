---
title: Market overview and ratios
description: How the market overview page pulls index, sector, and mover data, and how the ratio library lets you track any two symbols divided against each other.
---

Two separate pages feed the broad-market picture. The market overview page is read-only — a live snapshot you check to orient yourself. The ratios page is interactive — you pick (or create) pairs of symbols, chart them over time, and optionally set alerts on them.

## Market overview

`GET /api/v1/market/overview` returns everything in a single call. The backend fires all four sub-queries concurrently via `asyncio.gather`, so latency is bounded by the slowest upstream rather than the sum of all.

The response shape, `MarketOverviewResponse`, has five fields:

```text
indices               — IndexQuote[]
sectors               — SectorPerformance[]
gainers               — MarketMover[]
losers                — MarketMover[]
currencies_commodities — CurrencyCommodity[]
```

**Indices** covers five symbols hardcoded in `market_service.py`: `^GSPC` (S&P 500), `^DJI` (Dow Jones), `^IXIC` (Nasdaq), `^RUT` (Russell 2000), and `^VIX`. Each index card on the page links through to the equity detail view for that symbol.

**Sectors** uses the eleven SPDR Select Sector ETFs (XLK, XLF, XLV, XLE, XLY, XLP, XLI, XLB, XLU, XLRE, XLC). The service sorts them by `change_percent` descending before returning, which is why the heatmap always shows the best-performing sector first. The color scale runs from deep red (below -2%) to deep green (above +2%), with neutral gray at zero.

**Top movers** is derived from a fixed watchlist of roughly 50 large-cap US stocks. The service fetches quotes for all of them, sorts by percentage change, and returns the top 5 gainers and bottom 5 losers. There is no index-level scan — if a small-cap stock moved 40% today, it will not appear here.

**Currencies, commodities, and crypto** covers the US Dollar Index (`DX-Y.NYB`), EUR/USD, gold (`GC=F`), silver (`SI=F`), crude oil (`CL=F`), natural gas (`NG=F`), Bitcoin (`BTC-USD`), and Ethereum (`ETH-USD`). These are grouped visually by the `category` field returned in each `CurrencyCommodity` object.

All data comes from the Yahoo Finance provider. The endpoint requires authentication; there is no caching at the API layer, so each request fetches live data.

## Ratio library

A ratio is any two symbols divided against each other: `numerator_price / denominator_price`. The value itself is dimensionless — what matters is whether it's rising or falling and by how much.

The use case is relative performance. SPY/QQQ rising means broad market is outperforming tech. Gold/Silver rising means gold is outperforming silver. You can track these relationships over months or years without caring about the absolute price of either leg.

### System ratios vs custom ratios

Eight ratios ship pre-seeded with `is_system = true`. They cannot be deleted, and only `is_favorite` can be changed on them:

| Name | Numerator | Denominator | Category |
| --- | --- | --- | --- |
| Gold/Silver | GC=F | SI=F | commodity |
| Gold/Bitcoin | GC=F | BTC-USD | crypto |
| SPY/QQQ | SPY | QQQ | equity |
| Value/Growth | VTV | VUG | equity |
| Copper/Gold | HG=F | GC=F | macro |
| TLT/IEF | TLT | IEF | macro |
| Small Cap/Large Cap | IWM | SPY | equity |
| EM/US | VWO | VTI | equity |

Custom ratios are created via `POST /api/v1/ratios` with `name`, `numerator_symbol`, `denominator_symbol`, `category`, and an optional `description`. Symbols are uppercased automatically on write. Custom ratios support full updates (name, description, is_favorite) and can be deleted. System ratios block delete requests — the endpoint returns 404 if `is_system = true`.

The `/ratios` page auto-initializes system ratios on first load: if `GET /api/v1/ratios` returns an empty list, the frontend calls `POST /api/v1/ratios/initialize` immediately.

### How a ratio is computed

The current quote — returned by `GET /api/v1/ratios/{id}/quote` — is:

```text
current_value = numerator.price / denominator.price
```

The previous-close ratio (`numerator.previous_close / denominator.previous_close`) is used to derive the 1-day change and percentage. Both quotes are fetched concurrently.

Historical data — `GET /api/v1/ratios/{id}/history?period=1y` — follows the same pattern but across full price series. The service fetches daily history for both symbols, aligns them by calendar date, and divides close prices element-wise. Valid periods are `1mo`, `3mo`, `6mo`, `1y`, `2y`, `5y`, and `max`. The response includes pre-calculated `change_1d`, `change_1w`, and `change_1m` absolute differences alongside the full `history` array of `RatioDataPoint` objects.

See [data flow](/architecture/data-flow/) for the broader quote fetch pattern (Flow 1) and how ratio alerts reuse the same quote logic (Flow 4).

### RatioChart component

`RatioChart` (in `frontend/src/components/ratio/RatioChart.tsx`) renders using `lightweight-charts` — the same library TradingView uses internally. It creates a single line series with a dashed price line marking the current value.

The period selector exposes six buttons: 1M, 3M, 6M, 1Y, 2Y, 5Y. Changing the period re-fetches from `GET /api/v1/ratios/{id}/history` and rebuilds the chart in place. The chart respects the active theme (light/dark) and resizes when the window width changes.

Above the chart, the component shows the current ratio value alongside three change figures (1D, 1W, 1M) derived from the history response. There are no overlays or secondary series — just the ratio line.

### Alerts on ratios

Price alerts can target a ratio by `ratio_id` instead of a plain symbol. The same `condition_type` values apply. See [alerts](/features/alerts/) for the full threshold and notification configuration.
