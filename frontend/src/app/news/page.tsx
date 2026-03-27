'use client';

import { useState } from 'react';
import { Newspaper } from 'lucide-react';
import { useWatchlistNews, useMarketNews } from '@/lib/hooks/useNews';
import { NewsFeed } from '@/components/news/NewsFeed';

type NewsView = 'watchlist' | 'market';

export default function NewsPage() {
  const [view, setView] = useState<NewsView>('watchlist');

  const {
    data: watchlistData,
    isLoading: watchlistLoading,
    error: watchlistError,
  } = useWatchlistNews(20);

  const {
    data: marketData,
    isLoading: marketLoading,
    error: marketError,
  } = useMarketNews(20);

  const isWatchlist = view === 'watchlist';

  return (
    <div className="min-h-[calc(100vh-4rem)] bg-neutral-50 dark:bg-neutral-900">
      <div className="max-w-4xl mx-auto px-4 sm:px-6 py-8">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 mb-6">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-lg bg-blue-100 dark:bg-blue-900/30">
              <Newspaper className="h-6 w-6 text-blue-600 dark:text-blue-400" />
            </div>
            <div>
              <h1 className="text-2xl font-bold text-neutral-900 dark:text-neutral-50">
                News
              </h1>
              <p className="text-sm text-neutral-500 dark:text-neutral-400">
                Financial news for your watchlist and the market
              </p>
            </div>
          </div>

          {/* View toggle */}
          <div className="flex gap-1 p-1 bg-neutral-100 dark:bg-neutral-800 rounded-lg border border-neutral-200 dark:border-neutral-700">
            <button
              onClick={() => setView('watchlist')}
              className={`px-3 py-1.5 text-sm font-medium rounded-md transition-colors ${
                isWatchlist
                  ? 'bg-white dark:bg-neutral-700 text-neutral-900 dark:text-neutral-100 shadow-sm'
                  : 'text-neutral-600 dark:text-neutral-400 hover:text-neutral-900 dark:hover:text-neutral-200'
              }`}
            >
              Watchlist
            </button>
            <button
              onClick={() => setView('market')}
              className={`px-3 py-1.5 text-sm font-medium rounded-md transition-colors ${
                !isWatchlist
                  ? 'bg-white dark:bg-neutral-700 text-neutral-900 dark:text-neutral-100 shadow-sm'
                  : 'text-neutral-600 dark:text-neutral-400 hover:text-neutral-900 dark:hover:text-neutral-200'
              }`}
            >
              Market
            </button>
          </div>
        </div>

        {/* News feed */}
        <NewsFeed
          items={isWatchlist ? watchlistData?.items : marketData?.items}
          isLoading={isWatchlist ? watchlistLoading : marketLoading}
          error={isWatchlist ? watchlistError : marketError}
          emptyMessage={
            isWatchlist
              ? 'No news for your watchlist symbols. Add equities to a watchlist to see related news.'
              : 'No market news available'
          }
          showSymbols={true}
        />
      </div>
    </div>
  );
}
