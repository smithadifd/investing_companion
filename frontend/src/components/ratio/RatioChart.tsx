'use client';

import { useEffect, useRef, useState } from 'react';
import { useTheme } from 'next-themes';
import { createChart, IChartApi, Time, LineStyle } from 'lightweight-charts';
import { useRatioHistory } from '@/lib/hooks/useRatio';
import type { Ratio } from '@/lib/api/types';

const PERIODS = [
  { label: '1M', value: '1mo' },
  { label: '3M', value: '3mo' },
  { label: '6M', value: '6mo' },
  { label: '1Y', value: '1y' },
  { label: '2Y', value: '2y' },
  { label: '5Y', value: '5y' },
];

// Helper to convert string/number to number
function toNumber(value: number | string | null): number {
  if (value === null) return 0;
  return typeof value === 'string' ? parseFloat(value) : value;
}

// Format ratio value
function formatRatioValue(value: number | string | null): string {
  const num = toNumber(value);
  if (num >= 100) return num.toFixed(1);
  if (num >= 10) return num.toFixed(2);
  return num.toFixed(4);
}

// Format change
function formatChange(value: number | string | null): string {
  if (value === null) return '-';
  const num = toNumber(value);
  const sign = num >= 0 ? '+' : '';
  if (Math.abs(num) >= 10) return `${sign}${num.toFixed(1)}`;
  if (Math.abs(num) >= 1) return `${sign}${num.toFixed(2)}`;
  return `${sign}${num.toFixed(4)}`;
}

interface RatioChartProps {
  ratio: Ratio;
}

export function RatioChart({ ratio }: RatioChartProps) {
  const [period, setPeriod] = useState('1y');
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const { resolvedTheme } = useTheme();

  const { data: history, isLoading, error } = useRatioHistory(ratio.id, period);

  useEffect(() => {
    if (!chartContainerRef.current || !history?.history.length) return;

    const isDark = resolvedTheme === 'dark';

    // Clear existing chart safely
    if (chartRef.current) {
      try {
        chartRef.current.remove();
      } catch {
        // Chart may already be disposed
      }
      chartRef.current = null;
    }

    const chart = createChart(chartContainerRef.current, {
      width: chartContainerRef.current.clientWidth,
      height: 400,
      layout: {
        background: { color: isDark ? '#262626' : '#ffffff' },
        textColor: isDark ? '#a3a3a3' : '#525252',
      },
      grid: {
        vertLines: { color: isDark ? '#404040' : '#e5e5e5' },
        horzLines: { color: isDark ? '#404040' : '#e5e5e5' },
      },
      crosshair: {
        mode: 1,
      },
      rightPriceScale: {
        borderColor: isDark ? '#404040' : '#e5e5e5',
      },
      timeScale: {
        borderColor: isDark ? '#404040' : '#e5e5e5',
        timeVisible: true,
      },
    });

    chartRef.current = chart;

    // Add ratio line
    const ratioSeries = chart.addLineSeries({
      color: '#3b82f6',
      lineWidth: 2,
      crosshairMarkerVisible: true,
      lastValueVisible: true,
      priceLineVisible: true,
    });

    const chartData = history.history.map((point) => ({
      time: point.timestamp.split('T')[0] as Time,
      value: toNumber(point.ratio_value),
    }));

    ratioSeries.setData(chartData);

    // Add horizontal line for current value
    if (history.current_value !== null) {
      ratioSeries.createPriceLine({
        price: toNumber(history.current_value),
        color: '#3b82f6',
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: 'Current',
      });
    }

    // Fit content
    chart.timeScale().fitContent();

    // Handle resize
    const handleResize = () => {
      if (chartContainerRef.current && chartRef.current) {
        chartRef.current.applyOptions({
          width: chartContainerRef.current.clientWidth,
        });
      }
    };
    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      try {
        chart.remove();
      } catch {
        // Chart may already be disposed
      }
      chartRef.current = null;
    };
  }, [history, resolvedTheme]);

  return (
    <div className="bg-white dark:bg-neutral-800 rounded-lg border border-neutral-200 dark:border-neutral-700 overflow-hidden">
      {/* Header */}
      <div className="p-4 border-b border-neutral-200 dark:border-neutral-700">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div>
            <h2 className="text-lg font-semibold text-neutral-900 dark:text-neutral-50">
              {ratio.name}
            </h2>
            <p className="text-sm text-neutral-500">
              {ratio.numerator_symbol} / {ratio.denominator_symbol}
            </p>
          </div>

          {history && (
            <div className="flex items-center gap-6">
              <div className="text-right">
                <p className="text-2xl font-bold text-neutral-900 dark:text-neutral-50">
                  {formatRatioValue(history.current_value)}
                </p>
              </div>
              <div className="grid grid-cols-3 gap-4 text-center">
                <div>
                  <p className="text-xs text-neutral-500">1D</p>
                  <p className={`text-sm font-medium ${
                    toNumber(history.change_1d) >= 0
                      ? 'text-emerald-600 dark:text-emerald-400'
                      : 'text-red-600 dark:text-red-400'
                  }`}>
                    {formatChange(history.change_1d)}
                  </p>
                </div>
                <div>
                  <p className="text-xs text-neutral-500">1W</p>
                  <p className={`text-sm font-medium ${
                    toNumber(history.change_1w) >= 0
                      ? 'text-emerald-600 dark:text-emerald-400'
                      : 'text-red-600 dark:text-red-400'
                  }`}>
                    {formatChange(history.change_1w)}
                  </p>
                </div>
                <div>
                  <p className="text-xs text-neutral-500">1M</p>
                  <p className={`text-sm font-medium ${
                    toNumber(history.change_1m) >= 0
                      ? 'text-emerald-600 dark:text-emerald-400'
                      : 'text-red-600 dark:text-red-400'
                  }`}>
                    {formatChange(history.change_1m)}
                  </p>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Period Selector */}
        <div className="flex gap-2 mt-4">
          {PERIODS.map((p) => (
            <button
              key={p.value}
              onClick={() => setPeriod(p.value)}
              className={`px-3 py-1 rounded-lg text-sm font-medium transition-colors ${
                period === p.value
                  ? 'bg-blue-600 text-white'
                  : 'bg-neutral-100 dark:bg-neutral-700 text-neutral-600 dark:text-neutral-300 hover:bg-neutral-200 dark:hover:bg-neutral-600'
              }`}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>

      {/* Chart */}
      <div className="p-4">
        {isLoading ? (
          <div className="h-[400px] flex items-center justify-center">
            <div className="animate-spin h-8 w-8 border-2 border-blue-500 border-t-transparent rounded-full"></div>
          </div>
        ) : error ? (
          <div className="h-[400px] flex items-center justify-center">
            <p className="text-red-500">Failed to load chart data</p>
          </div>
        ) : !history?.history.length ? (
          <div className="h-[400px] flex items-center justify-center">
            <p className="text-neutral-500">No data available for this period</p>
          </div>
        ) : (
          <div ref={chartContainerRef} className="w-full" />
        )}
      </div>

      {/* Description */}
      {ratio.description && (
        <div className="px-4 pb-4">
          <div className="p-3 bg-neutral-50 dark:bg-neutral-700/50 rounded-lg">
            <p className="text-sm text-neutral-600 dark:text-neutral-300">
              {ratio.description}
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
