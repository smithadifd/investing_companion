# Issue 004: Chart Timeframe and Type Enhancements

**Status:** Open
**Created:** 2026-02-04
**Priority:** Medium
**Affects:** Equity detail page charts

## Summary

The current chart implementation only shows candlestick charts with a fixed daily timeframe. Users need the ability to:
1. Change chart timeframes (1m, 5m, 15m, 1h, 4h, 1D, 1W, 1M)
2. Toggle between candlestick and line chart views

## Current Behavior

- Charts always display daily candlesticks
- No option to switch to line chart
- Period selector (1D, 5D, 1M, etc.) only changes date range, not candle interval
- Candlestick charts on short timeframes don't make sense without proper intervals

## Files Affected

- `frontend/src/components/charts/AdvancedChart.tsx` - Main chart component
- `frontend/src/components/charts/ChartControls.tsx` - Period selector
- `frontend/src/app/equity/[symbol]/page.tsx` - Chart container
- `backend/app/services/data_providers/yahoo.py` - Data fetching (may need interval parameter)

## Proposed Solution

### Frontend Changes

1. **Add chart type toggle to ChartControls:**
   ```tsx
   <button onClick={() => setChartType('candlestick')}>Candlestick</button>
   <button onClick={() => setChartType('line')}>Line</button>
   ```

2. **Add timeframe selector:**
   - For intraday: 1m, 5m, 15m, 1h
   - For daily+: 1D, 1W, 1M

3. **Modify AdvancedChart to support line series:**
   - Use `chart.addLineSeries()` when type is 'line'
   - Use `chart.addCandlestickSeries()` when type is 'candlestick'

### Backend Changes

1. **Add interval parameter to price history endpoint:**
   ```python
   @router.get("/{symbol}/history")
   async def get_price_history(
       symbol: str,
       period: str = "1y",
       interval: str = "1d"  # New parameter
   ):
   ```

2. **Pass interval to Yahoo Finance:**
   ```python
   history = ticker.history(period=period, interval=interval)
   ```

## Data Considerations

- Yahoo Finance free tier limits intraday data to last 7-60 days depending on interval
- May need to adjust period options based on selected interval
- Intraday data has more rows, consider pagination or data limits

## Effort Estimate

- Frontend: 3-4 hours (chart type toggle, timeframe selector, series switching)
- Backend: 1-2 hours (interval parameter, validation)
- Testing: 1-2 hours

**Total: ~6-8 hours**

## Related Issues

- Issue 011 (same topic, merged here)
- Issue 012 (line chart toggle, merged here)
