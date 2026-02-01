'use client';

import { Loader2 } from 'lucide-react';
import Link from 'next/link';
import { usePeers } from '@/lib/hooks/useEquity';
import {
  formatCurrency,
  formatLargeNumber,
  formatRatio,
  formatPercent,
} from '@/lib/utils/format';
import type { EquityDetail } from '@/lib/api/types';

interface PeerComparisonProps {
  symbol: string;
  currentEquity: EquityDetail;
}

interface ComparisonMetric {
  label: string;
  key: string;
  format: (value: number | string | null | undefined) => string;
  getValue: (equity: EquityDetail) => number | string | null | undefined;
  higherIsBetter?: boolean; // For highlighting
}

function toNumber(value: unknown): number | null {
  if (value == null) return null;
  const num = typeof value === 'string' ? parseFloat(value) : Number(value);
  return isNaN(num) ? null : num;
}

function formatPercentValue(value: number | string | null | undefined): string {
  const num = toNumber(value);
  if (num == null) return '--';
  return `${(num * 100).toFixed(2)}%`;
}

const COMPARISON_METRICS: ComparisonMetric[] = [
  {
    label: 'Price',
    key: 'price',
    format: formatCurrency,
    getValue: (e) => e.quote?.price,
  },
  {
    label: 'Market Cap',
    key: 'market_cap',
    format: formatLargeNumber,
    getValue: (e) => e.fundamentals?.market_cap,
  },
  {
    label: 'P/E Ratio',
    key: 'pe_ratio',
    format: formatRatio,
    getValue: (e) => e.fundamentals?.pe_ratio,
    higherIsBetter: false,
  },
  {
    label: 'Forward P/E',
    key: 'forward_pe',
    format: formatRatio,
    getValue: (e) => e.fundamentals?.forward_pe,
    higherIsBetter: false,
  },
  {
    label: 'PEG Ratio',
    key: 'peg_ratio',
    format: formatRatio,
    getValue: (e) => e.fundamentals?.peg_ratio,
    higherIsBetter: false,
  },
  {
    label: 'P/B Ratio',
    key: 'price_to_book',
    format: formatRatio,
    getValue: (e) => e.fundamentals?.price_to_book,
    higherIsBetter: false,
  },
  {
    label: 'Dividend Yield',
    key: 'dividend_yield',
    format: formatPercentValue,
    getValue: (e) => e.fundamentals?.dividend_yield,
    higherIsBetter: true,
  },
  {
    label: 'Profit Margin',
    key: 'profit_margin',
    format: formatPercentValue,
    getValue: (e) => e.fundamentals?.profit_margin,
    higherIsBetter: true,
  },
  {
    label: 'Beta',
    key: 'beta',
    format: formatRatio,
    getValue: (e) => e.fundamentals?.beta,
  },
  {
    label: 'EPS (TTM)',
    key: 'eps_ttm',
    format: formatCurrency,
    getValue: (e) => e.fundamentals?.eps_ttm,
    higherIsBetter: true,
  },
  {
    label: 'Day Change',
    key: 'change_percent',
    format: (v) => formatPercent(v),
    getValue: (e) => e.quote?.change_percent,
    higherIsBetter: true,
  },
];

function getBestValue(
  values: (number | null)[],
  higherIsBetter: boolean | undefined
): number | null {
  const validValues = values.filter((v) => v !== null) as number[];
  if (validValues.length === 0) return null;

  if (higherIsBetter === undefined) return null;
  return higherIsBetter
    ? Math.max(...validValues)
    : Math.min(...validValues);
}

export function PeerComparison({ symbol, currentEquity }: PeerComparisonProps) {
  const { data: peers, isLoading, error } = usePeers(symbol, 4);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="h-6 w-6 animate-spin text-blue-500" />
        <span className="ml-2 text-neutral-500 dark:text-neutral-400">
          Loading peer comparison...
        </span>
      </div>
    );
  }

  if (error || !peers || peers.length === 0) {
    return (
      <div className="text-center py-12 text-neutral-500 dark:text-neutral-400">
        No peer data available for comparison.
      </div>
    );
  }

  // Combine current equity with peers for the table
  const allEquities = [currentEquity, ...peers];

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-neutral-200 dark:border-neutral-700">
            <th className="text-left p-3 font-medium text-neutral-500 dark:text-neutral-400 sticky left-0 bg-white dark:bg-neutral-800 z-10">
              Metric
            </th>
            {allEquities.map((equity, idx) => (
              <th
                key={equity.symbol}
                className={`text-right p-3 font-medium min-w-[100px] ${
                  idx === 0
                    ? 'text-blue-500 bg-blue-500/5'
                    : 'text-neutral-900 dark:text-neutral-50'
                }`}
              >
                <Link
                  href={`/equity/${equity.symbol}`}
                  className="hover:underline"
                >
                  {equity.symbol}
                </Link>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {COMPARISON_METRICS.map((metric) => {
            const values = allEquities.map((e) => toNumber(metric.getValue(e)));
            const bestValue = getBestValue(values, metric.higherIsBetter);

            return (
              <tr
                key={metric.key}
                className="border-b border-neutral-100 dark:border-neutral-700/50 hover:bg-neutral-50 dark:hover:bg-neutral-700/30"
              >
                <td className="p-3 text-neutral-600 dark:text-neutral-300 sticky left-0 bg-white dark:bg-neutral-800 z-10">
                  {metric.label}
                </td>
                {allEquities.map((equity, idx) => {
                  const value = metric.getValue(equity);
                  const numValue = toNumber(value);
                  const isBest =
                    bestValue !== null &&
                    numValue !== null &&
                    numValue === bestValue;

                  return (
                    <td
                      key={equity.symbol}
                      className={`text-right p-3 font-mono ${
                        idx === 0 ? 'bg-blue-500/5' : ''
                      } ${
                        isBest && metric.higherIsBetter !== undefined
                          ? 'text-emerald-500 font-semibold'
                          : 'text-neutral-900 dark:text-neutral-50'
                      }`}
                    >
                      {metric.format(value)}
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>

      <div className="mt-4 text-xs text-neutral-500 dark:text-neutral-400">
        <span className="text-emerald-500">Green values</span> indicate the best
        among peers for that metric. Peers are selected from the{' '}
        <span className="font-medium">{currentEquity.sector || 'same'}</span>{' '}
        sector.
      </div>
    </div>
  );
}
