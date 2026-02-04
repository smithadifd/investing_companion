'use client';

import { useState } from 'react';
import Link from 'next/link';
import { TrendingUp, TrendingDown } from 'lucide-react';
import { useAllWatchlistMovers } from '@/lib/hooks/useWatchlist';
import { StockCard } from '@/components/ui/StockCard';

type ViewMode = 'all' | 'gainers' | 'losers';

function parseNumber(value: number | string | null | undefined): number {
  if (value === null || value === undefined) return 0;
  return typeof value === 'string' ? parseFloat(value) : value;
}

export function WatchlistMovers() {
  const [viewMode, setViewMode] = useState<ViewMode>('all');
  const { data: moversData, isLoading, error } = useAllWatchlistMovers(6);

  if (isLoading) {
    return (
      <div className="bg-white dark:bg-neutral-800 rounded-xl border border-neutral-200 dark:border-neutral-700 p-5">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-semibold text-neutral-900 dark:text-neutral-50">
            Today&apos;s Movers
          </h2>
        </div>
        <div className="space-y-3">
          {[1, 2, 3, 4, 5].map((i) => (
            <div
              key={i}
              className="h-16 bg-neutral-100 dark:bg-neutral-700 rounded-lg animate-pulse"
            />
          ))}
        </div>
      </div>
    );
  }

  if (error || !moversData) {
    return (
      <div className="bg-white dark:bg-neutral-800 rounded-xl border border-neutral-200 dark:border-neutral-700 p-5">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-semibold text-neutral-900 dark:text-neutral-50">
            Today&apos;s Movers
          </h2>
        </div>
        <div className="text-center py-8">
          <p className="text-neutral-500 dark:text-neutral-400 mb-3">
            Could not load movers data
          </p>
          <Link
            href="/watchlists"
            className="text-blue-600 dark:text-blue-400 hover:underline text-sm"
          >
            Go to Watchlists
          </Link>
        </div>
      </div>
    );
  }

  const { gainers, losers, total_items, watchlist_count } = moversData;

  if (total_items === 0) {
    return (
      <div className="bg-white dark:bg-neutral-800 rounded-xl border border-neutral-200 dark:border-neutral-700 p-5">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-semibold text-neutral-900 dark:text-neutral-50">
            Today&apos;s Movers
          </h2>
        </div>
        <div className="text-center py-8">
          <p className="text-neutral-500 dark:text-neutral-400 mb-3">
            No items in any watchlist
          </p>
          <Link
            href="/watchlists"
            className="text-blue-600 dark:text-blue-400 hover:underline text-sm"
          >
            Add some equities
          </Link>
        </div>
      </div>
    );
  }

  // Get movers based on view mode
  const getDisplayedMovers = () => {
    if (viewMode === 'gainers') return gainers;
    if (viewMode === 'losers') return losers;
    // 'all' - interleave top 3 gainers and top 3 losers
    const combined = [];
    const maxLen = Math.max(gainers.length, losers.length);
    for (let i = 0; i < maxLen && combined.length < 6; i++) {
      if (i < gainers.length && combined.length < 6) combined.push(gainers[i]);
      if (i < losers.length && combined.length < 6) combined.push(losers[i]);
    }
    return combined;
  };

  const displayedMovers = getDisplayedMovers();

  return (
    <div className="bg-white dark:bg-neutral-800 rounded-xl border border-neutral-200 dark:border-neutral-700 p-5">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="font-semibold text-neutral-900 dark:text-neutral-50">
            Today&apos;s Movers
          </h2>
          <p className="text-xs text-neutral-500 dark:text-neutral-400">
            Across {watchlist_count} watchlist{watchlist_count !== 1 ? 's' : ''} ({total_items} equities)
          </p>
        </div>
        <Link
          href="/watchlists"
          className="text-sm text-blue-600 dark:text-blue-400 hover:underline"
        >
          View All
        </Link>
      </div>

      {/* View mode tabs */}
      <div className="flex gap-1 mb-4 bg-neutral-100 dark:bg-neutral-700 rounded-lg p-1">
        <button
          onClick={() => setViewMode('all')}
          className={`flex-1 px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
            viewMode === 'all'
              ? 'bg-white dark:bg-neutral-600 shadow-sm text-neutral-900 dark:text-neutral-50'
              : 'text-neutral-500 dark:text-neutral-400 hover:text-neutral-700 dark:hover:text-neutral-200'
          }`}
        >
          All
        </button>
        <button
          onClick={() => setViewMode('gainers')}
          className={`flex-1 flex items-center justify-center gap-1 px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
            viewMode === 'gainers'
              ? 'bg-white dark:bg-neutral-600 shadow-sm text-emerald-600 dark:text-emerald-400'
              : 'text-neutral-500 dark:text-neutral-400 hover:text-neutral-700 dark:hover:text-neutral-200'
          }`}
        >
          <TrendingUp className="h-3 w-3" />
          Gainers
        </button>
        <button
          onClick={() => setViewMode('losers')}
          className={`flex-1 flex items-center justify-center gap-1 px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
            viewMode === 'losers'
              ? 'bg-white dark:bg-neutral-600 shadow-sm text-red-600 dark:text-red-400'
              : 'text-neutral-500 dark:text-neutral-400 hover:text-neutral-700 dark:hover:text-neutral-200'
          }`}
        >
          <TrendingDown className="h-3 w-3" />
          Losers
        </button>
      </div>

      {/* Movers list */}
      <div className="space-y-2">
        {displayedMovers.length === 0 ? (
          <p className="text-center text-neutral-500 dark:text-neutral-400 py-4 text-sm">
            No {viewMode === 'gainers' ? 'gainers' : viewMode === 'losers' ? 'losers' : 'movers'} today
          </p>
        ) : (
          displayedMovers.map((mover, index) => (
            <StockCard
              key={mover.symbol}
              symbol={mover.symbol}
              name={mover.name}
              price={parseNumber(mover.price)}
              changePercent={parseNumber(mover.change_percent)}
              rank={index + 1}
              highlightThreshold={3}
              subtitle={mover.watchlist_name}
            />
          ))
        )}
      </div>
    </div>
  );
}
