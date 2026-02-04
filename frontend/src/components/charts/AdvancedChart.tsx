'use client';

import { useEffect, useRef } from 'react';
import { useTheme } from 'next-themes';
import {
  createChart,
  IChartApi,
  ColorType,
  Time,
  LineStyle,
  UTCTimestamp,
} from 'lightweight-charts';
import type { OHLCVData, TechnicalIndicators } from '@/lib/api/types';
import type { ChartType } from './ChartControls';

/**
 * Convert timestamp string to TradingView Time format.
 * For intraday data (contains 'T'), use Unix timestamp.
 * For daily data, use date string.
 */
function toChartTime(timestamp: string): Time {
  if (timestamp.includes('T')) {
    // Intraday: use Unix timestamp (seconds since epoch)
    return Math.floor(new Date(timestamp).getTime() / 1000) as UTCTimestamp;
  }
  // Daily: use date string
  return timestamp as Time;
}

/**
 * Deduplicate chart data by timestamp, keeping the last occurrence.
 * TradingView requires unique, ascending timestamps.
 */
function deduplicateByTime<T extends { time: Time }>(data: T[]): T[] {
  const seen = new Map<string | number, T>();
  for (const item of data) {
    seen.set(item.time as string | number, item);
  }
  return Array.from(seen.values());
}

interface AdvancedChartProps {
  data: OHLCVData[];
  technicals?: TechnicalIndicators;
  height?: number;
  chartType?: ChartType;
  showSMA?: boolean;
  showEMA?: boolean;
  showBollingerBands?: boolean;
  showRSI?: boolean;
  showMACD?: boolean;
}

interface ChartColors {
  background: string;
  text: string;
  grid: string;
  border: string;
}

const INDICATOR_COLORS = {
  sma20: '#f59e0b', // amber
  sma50: '#3b82f6', // blue
  sma200: '#8b5cf6', // purple
  ema12: '#10b981', // emerald
  ema26: '#ec4899', // pink
  bbUpper: '#6366f1', // indigo
  bbLower: '#6366f1',
  bbMiddle: '#6366f1',
  rsi: '#f59e0b',
  macdLine: '#3b82f6',
  macdSignal: '#ef4444',
  macdHistogramPositive: '#22c55e',
  macdHistogramNegative: '#ef4444',
};

export function AdvancedChart({
  data,
  technicals,
  height = 400,
  chartType = 'candlestick',
  showSMA = true,
  showEMA = false,
  showBollingerBands = false,
  showRSI = true,
  showMACD = true,
}: AdvancedChartProps) {
  const mainContainerRef = useRef<HTMLDivElement>(null);
  const rsiContainerRef = useRef<HTMLDivElement>(null);
  const macdContainerRef = useRef<HTMLDivElement>(null);

  const mainChartRef = useRef<IChartApi | null>(null);
  const rsiChartRef = useRef<IChartApi | null>(null);
  const macdChartRef = useRef<IChartApi | null>(null);

  const { resolvedTheme } = useTheme();

  const getColors = (): ChartColors => {
    const isDark = resolvedTheme === 'dark';
    return {
      background: isDark ? '#1f2937' : '#ffffff',
      text: isDark ? '#9ca3af' : '#333333',
      grid: isDark ? '#374151' : '#f0f0f0',
      border: isDark ? '#374151' : '#e0e0e0',
    };
  };

  // Main price chart
  useEffect(() => {
    if (!mainContainerRef.current || data.length === 0) return;

    const colors = getColors();
    const chart = createChart(mainContainerRef.current, {
      width: mainContainerRef.current.clientWidth,
      height,
      layout: {
        background: { type: ColorType.Solid, color: colors.background },
        textColor: colors.text,
      },
      grid: {
        vertLines: { color: colors.grid },
        horzLines: { color: colors.grid },
      },
      crosshair: { mode: 1 },
      rightPriceScale: { borderColor: colors.border },
      timeScale: {
        borderColor: colors.border,
        timeVisible: true,
        secondsVisible: false,
        tickMarkFormatter: (time: UTCTimestamp) => {
          const date = new Date(time * 1000);
          const hours = date.getHours();
          const minutes = date.getMinutes();
          // For intraday data, show 12-hour time
          if (hours !== 0 || minutes !== 0) {
            const hour12 = hours % 12 || 12;
            const ampm = hours < 12 ? 'AM' : 'PM';
            const minStr = minutes.toString().padStart(2, '0');
            return `${hour12}:${minStr} ${ampm}`;
          }
          // For daily data, show date
          return `${date.getMonth() + 1}/${date.getDate()}`;
        },
      },
    });

    // Price series - candlestick or line based on chartType
    if (chartType === 'line') {
      const lineSeries = chart.addLineSeries({
        color: '#3b82f6',
        lineWidth: 2,
        crosshairMarkerVisible: true,
        lastValueVisible: true,
        priceLineVisible: true,
      });

      const lineData = deduplicateByTime(
        data.map((item) => ({
          time: toChartTime(item.timestamp),
          value: Number(item.close),
        }))
      );
      lineSeries.setData(lineData);
    } else {
      const candlestickSeries = chart.addCandlestickSeries({
        upColor: '#22c55e',
        downColor: '#ef4444',
        borderDownColor: '#ef4444',
        borderUpColor: '#22c55e',
        wickDownColor: '#ef4444',
        wickUpColor: '#22c55e',
      });

      const chartData = deduplicateByTime(
        data.map((item) => ({
          time: toChartTime(item.timestamp),
          open: Number(item.open),
          high: Number(item.high),
          low: Number(item.low),
          close: Number(item.close),
        }))
      );
      candlestickSeries.setData(chartData);
    }

    // Volume series
    const volumeSeries = chart.addHistogramSeries({
      color: '#26a69a',
      priceFormat: { type: 'volume' },
      priceScaleId: 'volume',
    });
    volumeSeries.priceScale().applyOptions({
      scaleMargins: { top: 0.85, bottom: 0 },
    });
    const volumeData = deduplicateByTime(
      data
        .filter((item) => item.volume != null)
        .map((item) => ({
          time: toChartTime(item.timestamp),
          value: item.volume as number,
          color: Number(item.close) >= Number(item.open) ? '#22c55e50' : '#ef444450',
        }))
    );
    volumeSeries.setData(volumeData);

    // Add indicator overlays if technicals data available
    if (technicals && technicals.timestamps.length > 0) {
      const timestamps = technicals.timestamps.map(t => toChartTime(t));

      // SMA overlays
      if (showSMA) {
        addLineSeries(chart, timestamps, technicals.sma_20, INDICATOR_COLORS.sma20, 'SMA 20', 1);
        addLineSeries(chart, timestamps, technicals.sma_50, INDICATOR_COLORS.sma50, 'SMA 50', 1);
        addLineSeries(chart, timestamps, technicals.sma_200, INDICATOR_COLORS.sma200, 'SMA 200', 2);
      }

      // EMA overlays
      if (showEMA) {
        addLineSeries(chart, timestamps, technicals.ema_12, INDICATOR_COLORS.ema12, 'EMA 12', 1);
        addLineSeries(chart, timestamps, technicals.ema_26, INDICATOR_COLORS.ema26, 'EMA 26', 1);
      }

      // Bollinger Bands
      if (showBollingerBands) {
        addLineSeries(chart, timestamps, technicals.bb_upper, INDICATOR_COLORS.bbUpper, 'BB Upper', 1, LineStyle.Dashed);
        addLineSeries(chart, timestamps, technicals.bb_middle, INDICATOR_COLORS.bbMiddle, 'BB Middle', 1);
        addLineSeries(chart, timestamps, technicals.bb_lower, INDICATOR_COLORS.bbLower, 'BB Lower', 1, LineStyle.Dashed);
      }
    }

    chart.timeScale().fitContent();
    mainChartRef.current = chart;

    const handleResize = () => {
      if (mainContainerRef.current) {
        chart.applyOptions({ width: mainContainerRef.current.clientWidth });
      }
    };
    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      chart.remove();
    };
  }, [data, technicals, height, chartType, showSMA, showEMA, showBollingerBands, resolvedTheme]);

  // RSI sub-chart
  useEffect(() => {
    if (!rsiContainerRef.current || !technicals || !showRSI) return;

    const colors = getColors();
    const chart = createChart(rsiContainerRef.current, {
      width: rsiContainerRef.current.clientWidth,
      height: 120,
      layout: {
        background: { type: ColorType.Solid, color: colors.background },
        textColor: colors.text,
      },
      grid: {
        vertLines: { color: colors.grid },
        horzLines: { color: colors.grid },
      },
      crosshair: { mode: 1 },
      rightPriceScale: {
        borderColor: colors.border,
        scaleMargins: { top: 0.1, bottom: 0.1 },
      },
      timeScale: {
        borderColor: colors.border,
        timeVisible: true,
        secondsVisible: false,
        visible: !showMACD, // Only show time scale on bottom chart
      },
    });

    const timestamps = technicals.timestamps.map(t => toChartTime(t));

    // RSI line
    const rsiSeries = chart.addLineSeries({
      color: INDICATOR_COLORS.rsi,
      lineWidth: 2,
      priceFormat: { type: 'custom', formatter: (price: number) => price.toFixed(1) },
    });

    const rsiData = deduplicateByTime(
      timestamps.map((time, i) => ({
        time,
        value: technicals.rsi[i] ?? undefined,
      })).filter(d => d.value !== undefined) as { time: Time; value: number }[]
    );
    rsiSeries.setData(rsiData);

    // Overbought/oversold lines
    const overboughtLine = chart.addLineSeries({
      color: '#ef4444',
      lineWidth: 1,
      lineStyle: LineStyle.Dashed,
      crosshairMarkerVisible: false,
      lastValueVisible: false,
      priceLineVisible: false,
    });
    overboughtLine.setData(deduplicateByTime(timestamps.map(time => ({ time, value: 70 }))));

    const oversoldLine = chart.addLineSeries({
      color: '#22c55e',
      lineWidth: 1,
      lineStyle: LineStyle.Dashed,
      crosshairMarkerVisible: false,
      lastValueVisible: false,
      priceLineVisible: false,
    });
    oversoldLine.setData(deduplicateByTime(timestamps.map(time => ({ time, value: 30 }))));

    chart.timeScale().fitContent();
    rsiChartRef.current = chart;

    const handleResize = () => {
      if (rsiContainerRef.current) {
        chart.applyOptions({ width: rsiContainerRef.current.clientWidth });
      }
    };
    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      chart.remove();
    };
  }, [technicals, showRSI, showMACD, resolvedTheme]);

  // MACD sub-chart
  useEffect(() => {
    if (!macdContainerRef.current || !technicals || !showMACD) return;

    const colors = getColors();
    const chart = createChart(macdContainerRef.current, {
      width: macdContainerRef.current.clientWidth,
      height: 120,
      layout: {
        background: { type: ColorType.Solid, color: colors.background },
        textColor: colors.text,
      },
      grid: {
        vertLines: { color: colors.grid },
        horzLines: { color: colors.grid },
      },
      crosshair: { mode: 1 },
      rightPriceScale: {
        borderColor: colors.border,
        scaleMargins: { top: 0.1, bottom: 0.1 },
      },
      timeScale: {
        borderColor: colors.border,
        timeVisible: true,
        secondsVisible: false,
      },
    });

    const timestamps = technicals.timestamps.map(t => toChartTime(t));

    // MACD histogram
    const histogramSeries = chart.addHistogramSeries({
      priceFormat: { type: 'custom', formatter: (price: number) => price.toFixed(3) },
      priceScaleId: 'macd',
    });
    const histogramData = deduplicateByTime(
      timestamps.map((time, i) => {
        const value = technicals.macd_histogram[i];
        return {
          time,
          value: value ?? 0,
          color: (value ?? 0) >= 0 ? INDICATOR_COLORS.macdHistogramPositive + '80' : INDICATOR_COLORS.macdHistogramNegative + '80',
        };
      }).filter((_, i) => technicals.macd_histogram[i] !== null)
    );
    histogramSeries.setData(histogramData);

    // MACD line
    const macdLine = chart.addLineSeries({
      color: INDICATOR_COLORS.macdLine,
      lineWidth: 2,
      priceScaleId: 'macd',
      priceFormat: { type: 'custom', formatter: (price: number) => price.toFixed(3) },
    });
    const macdData = deduplicateByTime(
      timestamps.map((time, i) => ({
        time,
        value: technicals.macd[i] ?? undefined,
      })).filter(d => d.value !== undefined) as { time: Time; value: number }[]
    );
    macdLine.setData(macdData);

    // Signal line
    const signalLine = chart.addLineSeries({
      color: INDICATOR_COLORS.macdSignal,
      lineWidth: 2,
      priceScaleId: 'macd',
      priceFormat: { type: 'custom', formatter: (price: number) => price.toFixed(3) },
    });
    const signalData = deduplicateByTime(
      timestamps.map((time, i) => ({
        time,
        value: technicals.macd_signal[i] ?? undefined,
      })).filter(d => d.value !== undefined) as { time: Time; value: number }[]
    );
    signalLine.setData(signalData);

    chart.timeScale().fitContent();
    macdChartRef.current = chart;

    const handleResize = () => {
      if (macdContainerRef.current) {
        chart.applyOptions({ width: macdContainerRef.current.clientWidth });
      }
    };
    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      chart.remove();
    };
  }, [technicals, showMACD, resolvedTheme]);

  // Sync time scales
  useEffect(() => {
    const charts = [mainChartRef.current, rsiChartRef.current, macdChartRef.current].filter(Boolean) as IChartApi[];
    if (charts.length < 2) return;

    let isSyncing = false;

    const syncTimeRange = (sourceChart: IChartApi) => {
      if (isSyncing) return; // Prevent recursive sync

      const timeRange = sourceChart.timeScale().getVisibleRange();
      if (!timeRange) return; // Skip if range not yet available

      isSyncing = true;
      charts.forEach(chart => {
        if (chart !== sourceChart) {
          try {
            chart.timeScale().setVisibleRange(timeRange);
          } catch {
            // Chart might be disposed or not ready
          }
        }
      });
      isSyncing = false;
    };

    const handlers: (() => void)[] = charts.map(chart => {
      const handler = () => syncTimeRange(chart);
      chart.timeScale().subscribeVisibleTimeRangeChange(handler);
      return handler;
    });

    return () => {
      charts.forEach((chart, i) => {
        try {
          chart.timeScale().unsubscribeVisibleTimeRangeChange(handlers[i]);
        } catch {
          // Chart might already be disposed
        }
      });
    };
  }, [technicals, showRSI, showMACD]);

  if (data.length === 0) {
    return (
      <div
        className="flex items-center justify-center bg-neutral-100 dark:bg-neutral-800 rounded-lg"
        style={{ height }}
      >
        <span className="text-neutral-500 dark:text-neutral-400">No data available</span>
      </div>
    );
  }

  return (
    <div className="space-y-1">
      {/* Main chart */}
      <div ref={mainContainerRef} className="w-full rounded-lg overflow-hidden" />

      {/* RSI sub-chart */}
      {showRSI && technicals && (
        <div className="relative">
          <div className="absolute left-2 top-1 text-xs text-neutral-500 dark:text-neutral-400 z-10">
            RSI (14)
          </div>
          <div ref={rsiContainerRef} className="w-full rounded-lg overflow-hidden" />
        </div>
      )}

      {/* MACD sub-chart */}
      {showMACD && technicals && (
        <div className="relative">
          <div className="absolute left-2 top-1 text-xs text-neutral-500 dark:text-neutral-400 z-10">
            MACD (12, 26, 9)
          </div>
          <div ref={macdContainerRef} className="w-full rounded-lg overflow-hidden" />
        </div>
      )}
    </div>
  );
}

// Helper function to add line series
function addLineSeries(
  chart: IChartApi,
  timestamps: Time[],
  values: (number | null)[],
  color: string,
  title: string,
  lineWidth: 1 | 2 | 3 | 4 = 1,
  lineStyle: LineStyle = LineStyle.Solid
) {
  const series = chart.addLineSeries({
    color,
    lineWidth,
    lineStyle,
    crosshairMarkerVisible: true,
    lastValueVisible: false,
    priceLineVisible: false,
    title,
  });

  const data = deduplicateByTime(
    timestamps.map((time, i) => ({
      time,
      value: values[i] ?? undefined,
    })).filter(d => d.value !== undefined) as { time: Time; value: number }[]
  );

  series.setData(data);
  return series;
}
