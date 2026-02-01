'use client';

import Link from 'next/link';
import { useMarketOverview } from '@/lib/hooks/useMarket';
import type { IndexQuote } from '@/lib/api/types';

function parseNumber(value: number | string): number {
  return typeof value === 'string' ? parseFloat(value) : value;
}

function IndexCard({ index }: { index: IndexQuote }) {
  const price = parseNumber(index.price);
  const changePercent = parseNumber(index.change_percent);
  const isPositive = changePercent >= 0;

  // VIX is inverted - high VIX is "bad" (fear), low VIX is "good" (complacency)
  const isVix = index.symbol === '^VIX';
  const colorClass = isVix
    ? changePercent >= 0
      ? 'text-red-600 dark:text-red-400'
      : 'text-emerald-600 dark:text-emerald-400'
    : isPositive
    ? 'text-emerald-600 dark:text-emerald-400'
    : 'text-red-600 dark:text-red-400';

  return (
    <div className="flex flex-col p-3 rounded-lg bg-neutral-50 dark:bg-neutral-700/50">
      <span className="text-xs text-neutral-500 dark:text-neutral-400 truncate">
        {index.name}
      </span>
      <span className="text-lg font-semibold text-neutral-900 dark:text-neutral-50">
        {price.toLocaleString(undefined, {
          minimumFractionDigits: 2,
          maximumFractionDigits: 2,
        })}
      </span>
      <span className={`text-sm font-medium ${colorClass}`}>
        {isPositive ? '+' : ''}
        {changePercent.toFixed(2)}%
      </span>
    </div>
  );
}

export function MarketSnapshot() {
  const { data: marketData, isLoading, error } = useMarketOverview();

  if (isLoading) {
    return (
      <div className="bg-white dark:bg-neutral-800 rounded-xl border border-neutral-200 dark:border-neutral-700 p-5">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-semibold text-neutral-900 dark:text-neutral-50">
            Market Snapshot
          </h2>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {[1, 2, 3, 4].map((i) => (
            <div
              key={i}
              className="h-20 bg-neutral-100 dark:bg-neutral-700 rounded-lg animate-pulse"
            />
          ))}
        </div>
      </div>
    );
  }

  if (error || !marketData) {
    return (
      <div className="bg-white dark:bg-neutral-800 rounded-xl border border-neutral-200 dark:border-neutral-700 p-5">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-semibold text-neutral-900 dark:text-neutral-50">
            Market Snapshot
          </h2>
        </div>
        <p className="text-neutral-500 dark:text-neutral-400 text-sm text-center py-4">
          Could not load market data
        </p>
      </div>
    );
  }

  // Show S&P 500, Nasdaq, Dow, and VIX
  const keyIndices = ['S&P 500', 'Nasdaq', 'Dow Jones', 'VIX'];
  const displayIndices = marketData.indices.filter((idx) =>
    keyIndices.includes(idx.name)
  );

  // Get top gainer and loser
  const topGainer = marketData.gainers[0];
  const topLoser = marketData.losers[0];

  return (
    <div className="bg-white dark:bg-neutral-800 rounded-xl border border-neutral-200 dark:border-neutral-700 p-5">
      <div className="flex items-center justify-between mb-4">
        <h2 className="font-semibold text-neutral-900 dark:text-neutral-50">
          Market Snapshot
        </h2>
        <Link
          href="/market"
          className="text-sm text-blue-600 dark:text-blue-400 hover:underline"
        >
          Full Overview
        </Link>
      </div>

      {/* Main indices */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4">
        {displayIndices.map((index) => (
          <IndexCard key={index.symbol} index={index} />
        ))}
      </div>

      {/* Top movers row */}
      {(topGainer || topLoser) && (
        <div className="flex gap-3 pt-3 border-t border-neutral-200 dark:border-neutral-700">
          {topGainer && (
            <Link
              href={`/equity/${topGainer.symbol}`}
              className="flex-1 p-2 rounded-lg bg-emerald-500/10 border border-emerald-500/20 hover:border-emerald-500/40 transition-colors"
            >
              <div className="flex items-center justify-between">
                <span className="text-xs text-emerald-600 dark:text-emerald-400">
                  Top Gainer
                </span>
                <span className="text-xs font-medium text-emerald-600 dark:text-emerald-400">
                  +{parseNumber(topGainer.change_percent).toFixed(2)}%
                </span>
              </div>
              <p className="font-semibold text-neutral-900 dark:text-neutral-50 truncate">
                {topGainer.symbol}
              </p>
            </Link>
          )}
          {topLoser && (
            <Link
              href={`/equity/${topLoser.symbol}`}
              className="flex-1 p-2 rounded-lg bg-red-500/10 border border-red-500/20 hover:border-red-500/40 transition-colors"
            >
              <div className="flex items-center justify-between">
                <span className="text-xs text-red-600 dark:text-red-400">
                  Top Loser
                </span>
                <span className="text-xs font-medium text-red-600 dark:text-red-400">
                  {parseNumber(topLoser.change_percent).toFixed(2)}%
                </span>
              </div>
              <p className="font-semibold text-neutral-900 dark:text-neutral-50 truncate">
                {topLoser.symbol}
              </p>
            </Link>
          )}
        </div>
      )}
    </div>
  );
}
