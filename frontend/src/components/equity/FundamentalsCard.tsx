'use client';

import type { Fundamentals } from '@/lib/api/types';
import {
  formatCurrency,
  formatLargeNumber,
  formatRatio,
  formatPercent,
} from '@/lib/utils/format';

interface FundamentalsCardProps {
  fundamentals: Fundamentals;
}

interface MetricItem {
  label: string;
  value: number | null;
  format: (value: number | null) => string;
}

export function FundamentalsCard({ fundamentals }: FundamentalsCardProps) {
  const metrics: MetricItem[] = [
    { label: 'Market Cap', value: fundamentals.market_cap, format: formatLargeNumber },
    { label: 'P/E Ratio', value: fundamentals.pe_ratio, format: formatRatio },
    { label: 'Forward P/E', value: fundamentals.forward_pe, format: formatRatio },
    { label: 'PEG Ratio', value: fundamentals.peg_ratio, format: formatRatio },
    { label: 'EPS (TTM)', value: fundamentals.eps_ttm, format: formatCurrency },
    {
      label: 'Dividend Yield',
      value: fundamentals.dividend_yield ? fundamentals.dividend_yield * 100 : null,
      format: (v) => (v != null ? `${v.toFixed(2)}%` : '--'),
    },
    { label: 'Beta', value: fundamentals.beta, format: formatRatio },
    { label: 'P/B Ratio', value: fundamentals.price_to_book, format: formatRatio },
    { label: 'P/S Ratio', value: fundamentals.price_to_sales, format: formatRatio },
    { label: '52W High', value: fundamentals.week_52_high, format: formatCurrency },
    { label: '52W Low', value: fundamentals.week_52_low, format: formatCurrency },
    { label: 'Avg Volume', value: fundamentals.avg_volume, format: formatLargeNumber },
    {
      label: 'Profit Margin',
      value: fundamentals.profit_margin ? fundamentals.profit_margin * 100 : null,
      format: (v) => (v != null ? `${v.toFixed(2)}%` : '--'),
    },
  ];

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-5 gap-4">
      {metrics.map(({ label, value, format }) => (
        <div
          key={label}
          className="p-4 bg-gray-50 rounded-lg hover:bg-gray-100 transition-colors"
        >
          <div className="text-sm text-gray-500">{label}</div>
          <div className="text-lg font-semibold text-gray-900">{format(value)}</div>
        </div>
      ))}
    </div>
  );
}
