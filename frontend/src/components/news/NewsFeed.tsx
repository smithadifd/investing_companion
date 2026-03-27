'use client';

import { Loader2, Newspaper } from 'lucide-react';
import type { NewsItem } from '@/lib/api/types';
import { NewsCard } from './NewsCard';

interface Props {
  items: NewsItem[] | undefined;
  isLoading: boolean;
  error: Error | null;
  emptyMessage?: string;
  showSymbols?: boolean;
}

export function NewsFeed({
  items,
  isLoading,
  error,
  emptyMessage = 'No news available',
  showSymbols = false,
}: Props) {
  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-8">
        <Loader2 className="h-6 w-6 animate-spin text-blue-500" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="text-center py-8 text-neutral-500 dark:text-neutral-400">
        <p className="text-sm">Failed to load news</p>
        <p className="text-xs mt-1">{error.message}</p>
      </div>
    );
  }

  if (!items || items.length === 0) {
    return (
      <div className="text-center py-8 text-neutral-500 dark:text-neutral-400">
        <Newspaper className="h-8 w-8 mx-auto mb-2 opacity-50" />
        <p className="text-sm">{emptyMessage}</p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {items.map((item) => (
        <NewsCard key={item.id} item={item} showSymbols={showSymbols} />
      ))}
    </div>
  );
}
