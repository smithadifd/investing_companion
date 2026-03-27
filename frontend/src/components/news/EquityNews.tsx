'use client';

import Link from 'next/link';
import { ChevronRight } from 'lucide-react';
import { useSymbolNews } from '@/lib/hooks/useNews';
import { NewsFeed } from './NewsFeed';

interface Props {
  symbol: string;
}

export function EquityNews({ symbol }: Props) {
  const { data, isLoading, error } = useSymbolNews(symbol);

  return (
    <div>
      <NewsFeed
        items={data?.items}
        isLoading={isLoading}
        error={error}
        emptyMessage={`No recent news for ${symbol}`}
      />

      {/* Link to full news page */}
      <div className="mt-4 pt-4 border-t border-neutral-200 dark:border-neutral-700">
        <Link
          href="/news"
          className="flex items-center justify-center gap-2 text-sm text-blue-500 hover:text-blue-600 dark:text-blue-400 dark:hover:text-blue-300"
        >
          View all news
          <ChevronRight className="h-4 w-4" />
        </Link>
      </div>
    </div>
  );
}
