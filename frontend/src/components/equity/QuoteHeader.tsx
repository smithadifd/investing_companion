'use client';

import { TrendingUp, TrendingDown, AlertTriangle } from 'lucide-react';
import type { EquityDetail, Quote } from '@/lib/api/types';
import {
  formatCurrency,
  formatPercent,
  formatLargeNumber,
  formatTimestamp,
} from '@/lib/utils/format';

interface QuoteHeaderProps {
  equity: EquityDetail;
}

interface QuoteProvenance {
  label: string;
  title: string;
}

/**
 * What the provenance badge should say, or `null` when the quote is fresh.
 *
 * A stale quote is a fallback: the primary did not answer. No remaining
 * provider is contractually delayed, so a source name alone never badges.
 */
function describeProvenance(quote: Quote): QuoteProvenance | null {
  if (!quote.stale) return null;
  const source = quote.source ?? null;
  return {
    label: source ? `Delayed data · via ${source}` : 'Delayed data',
    title: source
      ? `Primary data source unavailable — showing delayed data via ${source}`
      : 'Primary data source unavailable — showing delayed fallback data',
  };
}

export function QuoteHeader({ equity }: QuoteHeaderProps) {
  const { quote } = equity;

  if (!quote) {
    return (
      <div>
        <div className="flex items-baseline gap-4">
          <h1 className="text-3xl font-bold text-foreground">{equity.symbol}</h1>
          <span className="text-muted-foreground">{equity.name}</span>
        </div>
        <p className="mt-2 text-muted-foreground">Quote data unavailable</p>
      </div>
    );
  }

  const changeNum = typeof quote.change === 'string' ? parseFloat(quote.change) : quote.change;
  const isPositive = changeNum >= 0;
  const provenance = describeProvenance(quote);

  return (
    <div>
      <div className="flex items-baseline gap-4 flex-wrap">
        <h1 className="text-3xl font-bold text-foreground">{equity.symbol}</h1>
        <span className="text-muted-foreground">{equity.name}</span>
        {equity.exchange && (
          <span className="text-sm text-muted-foreground">{equity.exchange}</span>
        )}
      </div>

      <div className="mt-3 flex items-center gap-4 flex-wrap">
        <span className="text-4xl font-semibold text-foreground">
          {formatCurrency(quote.price)}
        </span>
        <div
          className={`flex items-center gap-1 ${
            isPositive ? 'text-gain' : 'text-loss'
          }`}
        >
          {isPositive ? (
            <TrendingUp className="h-5 w-5" />
          ) : (
            <TrendingDown className="h-5 w-5" />
          )}
          <span className="text-xl font-medium">
            {isPositive ? '+' : ''}
            {formatCurrency(quote.change)} ({formatPercent(quote.change_percent)})
          </span>
        </div>
      </div>

      <div className="mt-4 flex gap-6 text-sm text-muted-foreground flex-wrap">
        <div>
          <span className="opacity-70">Open:</span>{' '}
          {formatCurrency(quote.open)}
        </div>
        <div>
          <span className="opacity-70">High:</span>{' '}
          {formatCurrency(quote.high)}
        </div>
        <div>
          <span className="opacity-70">Low:</span>{' '}
          {formatCurrency(quote.low)}
        </div>
        <div>
          <span className="opacity-70">Volume:</span>{' '}
          {formatLargeNumber(quote.volume)}
        </div>
        {quote.market_cap && (
          <div>
            <span className="opacity-70">Market Cap:</span>{' '}
            {formatLargeNumber(quote.market_cap)}
          </div>
        )}
      </div>

      {(equity.sector || equity.industry) && (
        <div className="mt-3 flex gap-4 text-sm text-muted-foreground">
          {equity.sector && <span>{equity.sector}</span>}
          {equity.sector && equity.industry && <span>•</span>}
          {equity.industry && <span>{equity.industry}</span>}
        </div>
      )}

      <div className="mt-3 flex items-center gap-2 text-xs text-muted-foreground flex-wrap">
        {quote.timestamp && (
          <span className="opacity-70">
            As of {formatTimestamp(quote.timestamp)}
          </span>
        )}
        {provenance && (
          <span
            data-testid="quote-provenance"
            className="inline-flex items-center gap-1 rounded-full border px-2 py-0.5 font-medium border-amber-300 bg-amber-50 text-amber-700 dark:border-amber-700/60 dark:bg-amber-900/20 dark:text-amber-400"
            title={provenance.title}
          >
            <AlertTriangle className="h-3 w-3" />
            {provenance.label}
          </span>
        )}
      </div>
    </div>
  );
}
