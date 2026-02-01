'use client';

import Link from 'next/link';
import { useWatchlists, useWatchlist } from '@/lib/hooks/useWatchlist';
import { StockCard } from '@/components/ui/StockCard';
import type { WatchlistItem } from '@/lib/api/types';

interface MoverItem {
  symbol: string;
  name: string;
  price: number;
  changePercent: number;
}

function parseNumber(value: number | string | null | undefined): number {
  if (value === null || value === undefined) return 0;
  return typeof value === 'string' ? parseFloat(value) : value;
}

function getMovers(items: WatchlistItem[]): MoverItem[] {
  return items
    .filter((item) => item.quote)
    .map((item) => ({
      symbol: item.equity.symbol,
      name: item.equity.name,
      price: parseNumber(item.quote?.price),
      changePercent: parseNumber(item.quote?.change_percent),
    }))
    .sort((a, b) => Math.abs(b.changePercent) - Math.abs(a.changePercent));
}

export function WatchlistMovers() {
  const { data: watchlists, isLoading: watchlistsLoading } = useWatchlists();

  // Find the default watchlist
  const defaultWatchlist = watchlists?.find((w) => w.is_default);
  const watchlistId = defaultWatchlist?.id ?? null;

  const {
    data: watchlist,
    isLoading: watchlistLoading,
    error,
  } = useWatchlist(watchlistId, true);

  const isLoading = watchlistsLoading || watchlistLoading;

  if (isLoading) {
    return (
      <div className="bg-white dark:bg-neutral-800 rounded-xl border border-neutral-200 dark:border-neutral-700 p-5">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-semibold text-neutral-900 dark:text-neutral-50">
            Watchlist Movers
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

  if (error || !watchlist) {
    return (
      <div className="bg-white dark:bg-neutral-800 rounded-xl border border-neutral-200 dark:border-neutral-700 p-5">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-semibold text-neutral-900 dark:text-neutral-50">
            Watchlist Movers
          </h2>
        </div>
        <div className="text-center py-8">
          <p className="text-neutral-500 dark:text-neutral-400 mb-3">
            {!defaultWatchlist
              ? 'No default watchlist set'
              : 'Could not load watchlist'}
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

  const movers = getMovers(watchlist.items);

  if (movers.length === 0) {
    return (
      <div className="bg-white dark:bg-neutral-800 rounded-xl border border-neutral-200 dark:border-neutral-700 p-5">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-semibold text-neutral-900 dark:text-neutral-50">
            Watchlist Movers
          </h2>
          <Link
            href={`/watchlists/${watchlist.id}`}
            className="text-sm text-blue-600 dark:text-blue-400 hover:underline"
          >
            View All
          </Link>
        </div>
        <div className="text-center py-8">
          <p className="text-neutral-500 dark:text-neutral-400 mb-3">
            No items in watchlist
          </p>
          <Link
            href={`/watchlists/${watchlist.id}`}
            className="text-blue-600 dark:text-blue-400 hover:underline text-sm"
          >
            Add some equities
          </Link>
        </div>
      </div>
    );
  }

  // Show top 6 movers
  const topMovers = movers.slice(0, 6);

  return (
    <div className="bg-white dark:bg-neutral-800 rounded-xl border border-neutral-200 dark:border-neutral-700 p-5">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="font-semibold text-neutral-900 dark:text-neutral-50">
            Watchlist Movers
          </h2>
          <p className="text-xs text-neutral-500 dark:text-neutral-400">
            {watchlist.name}
          </p>
        </div>
        <Link
          href={`/watchlists/${watchlist.id}`}
          className="text-sm text-blue-600 dark:text-blue-400 hover:underline"
        >
          View All ({watchlist.items.length})
        </Link>
      </div>
      <div className="space-y-2">
        {topMovers.map((mover, index) => (
          <StockCard
            key={mover.symbol}
            symbol={mover.symbol}
            name={mover.name}
            price={mover.price}
            changePercent={mover.changePercent}
            rank={index + 1}
            highlightThreshold={3}
          />
        ))}
      </div>
    </div>
  );
}
