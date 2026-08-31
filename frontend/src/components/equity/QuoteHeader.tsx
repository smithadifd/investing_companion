'use client';

import { TrendingUp, TrendingDown, AlertTriangle, Clock } from 'lucide-react';
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

/**
 * Providers whose plan is *contractually* behind, and by how many minutes.
 *
 * These are a different thing from a degraded fallback, and the badge has to
 * say so. A quote from Massive's 15-minute Starter plan is exactly what the
 * install was configured to serve — nothing failed — so warning that the
 * "primary data source is unavailable" would be false, and false often enough
 * that the badge stops meaning anything. A fallback quote still gets the
 * warning, because there something did go wrong.
 *
 * Mirrors `delayed_quotes` / `quote_delay_minutes` on the backend providers
 * (`backend/app/services/data_providers/base.py`); the quote payload carries
 * only `source` and `stale`, so the delay minutes live here.
 */
const CONTRACTUAL_QUOTE_DELAY_MINUTES: Record<string, number> = {
  massive: 15,
};

interface QuoteProvenance {
  label: string;
  title: string;
  /** Neutral (a known, configured delay) vs. degraded (something failed). */
  contractual: boolean;
}

/**
 * What the provenance badge should say, or `null` when there is nothing to say.
 *
 * Driven by `source` first and `stale` second: the delay is a fact about the
 * plan, so a known-delayed source is labelled even if the flag went missing on
 * the way here.
 */
function describeProvenance(quote: Quote): QuoteProvenance | null {
  const source = quote.source ?? null;
  const delayMinutes = source
    ? CONTRACTUAL_QUOTE_DELAY_MINUTES[source]
    : undefined;

  if (delayMinutes !== undefined) {
    return {
      label: `${delayMinutes}-min delayed · via ${source}`,
      title: `${source} serves quotes on a ${delayMinutes}-minute delay; this is the configured data source, not a failure`,
      contractual: true,
    };
  }

  if (!quote.stale) return null;

  return {
    label: source ? `Delayed data · via ${source}` : 'Delayed data',
    title: source
      ? `Primary data source unavailable — showing delayed data via ${source}`
      : 'Primary data source unavailable — showing delayed fallback data',
    contractual: false,
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
            className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 font-medium ${
              provenance.contractual
                ? 'border-border bg-muted text-muted-foreground'
                : 'border-amber-300 bg-amber-50 text-amber-700 dark:border-amber-700/60 dark:bg-amber-900/20 dark:text-amber-400'
            }`}
            title={provenance.title}
          >
            {provenance.contractual ? (
              <Clock className="h-3 w-3" />
            ) : (
              <AlertTriangle className="h-3 w-3" />
            )}
            {provenance.label}
          </span>
        )}
      </div>
    </div>
  );
}
