'use client';

import type { Fundamentals } from '@/lib/api/types';
import {
  formatCurrency,
  formatLargeNumber,
  formatRatio,
} from '@/lib/utils/format';

interface FundamentalsCardProps {
  fundamentals: Fundamentals;
}

type FormatFn = (value: number | string | null | undefined) => string;

interface MetricItem {
  label: string;
  value: number | string | null;
  format: FormatFn;
}

function toNumber(value: unknown): number | null {
  if (value == null) return null;
  const num = typeof value === 'string' ? parseFloat(value) : Number(value);
  return isNaN(num) ? null : num;
}

function formatPercentValue(value: number | string | null | undefined): string {
  const num = toNumber(value);
  if (num == null) return '--';
  // Yahoo Finance returns dividend_yield as decimal (0.004 = 0.4%)
  // Values > 1 are already in percentage form, don't multiply
  const pct = num > 1 ? num : num * 100;
  return `${pct.toFixed(2)}%`;
}

export function FundamentalsCard({ fundamentals }: FundamentalsCardProps) {
  const metrics: MetricItem[] = [
    { label: 'Market Cap', value: fundamentals.market_cap, format: formatLargeNumber },
    { label: 'P/E Ratio', value: fundamentals.pe_ratio, format: formatRatio },
    { label: 'Forward P/E', value: fundamentals.forward_pe, format: formatRatio },
    { label: 'PEG Ratio', value: fundamentals.peg_ratio, format: formatRatio },
    { label: 'EPS (TTM)', value: fundamentals.eps_ttm, format: formatCurrency },
    { label: 'Dividend Yield', value: fundamentals.dividend_yield, format: formatPercentValue },
    { label: 'Beta', value: fundamentals.beta, format: formatRatio },
    { label: 'P/B Ratio', value: fundamentals.price_to_book, format: formatRatio },
    { label: 'P/S Ratio', value: fundamentals.price_to_sales, format: formatRatio },
    { label: '52W High', value: fundamentals.week_52_high, format: formatCurrency },
    { label: '52W Low', value: fundamentals.week_52_low, format: formatCurrency },
    { label: 'Avg Volume', value: fundamentals.avg_volume, format: formatLargeNumber },
    { label: 'Profit Margin', value: fundamentals.profit_margin, format: formatPercentValue },
  ];

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-5 gap-4">
      {metrics.map(({ label, value, format }) => (
        <div
          key={label}
          className="p-4 bg-muted rounded-lg hover:bg-muted/80 transition-colors"
        >
          <div className="text-sm text-muted-foreground">{label}</div>
          <div className="text-lg font-semibold text-foreground">{format(value)}</div>
        </div>
      ))}
    </div>
  );
}
