'use client';

import { ExternalLink } from 'lucide-react';
import { formatDistanceToNow } from 'date-fns';
import type { NewsItem } from '@/lib/api/types';
import { NewsSentimentBadge } from './NewsSentimentBadge';

// Generic placeholder images that shouldn't be displayed
const PLACEHOLDER_IMAGES = [
  'yimg.com/rz/stage/p/yahoo_finance',
  'static2.finnhub.io/press/logo',
];

function isPlaceholderImage(url: string | null): boolean {
  if (!url) return true;
  return PLACEHOLDER_IMAGES.some((pattern) => url.includes(pattern));
}

interface Props {
  item: NewsItem;
  showSymbols?: boolean;
}

export function NewsCard({ item, showSymbols = false }: Props) {
  const publishedDate = new Date(item.published_at);
  const hasImage = !isPlaceholderImage(item.image_url);

  return (
    <a
      href={item.url}
      target="_blank"
      rel="noopener noreferrer"
      className="block p-4 rounded-lg border border-neutral-200 dark:border-neutral-700 bg-white dark:bg-neutral-800 hover:border-blue-300 dark:hover:border-blue-600 transition-colors group"
    >
      <div className="flex items-start gap-3">
        {hasImage && item.image_url && (
          <img
            src={item.image_url}
            alt=""
            className="w-16 h-16 rounded-lg object-cover flex-shrink-0 hidden sm:block"
          />
        )}
        <div className="flex-1 min-w-0">
          <div className="flex items-start justify-between gap-2">
            <h3 className="font-medium text-neutral-900 dark:text-neutral-100 group-hover:text-blue-600 dark:group-hover:text-blue-400 transition-colors line-clamp-2 text-sm">
              {item.title}
            </h3>
            <ExternalLink className="h-3.5 w-3.5 flex-shrink-0 text-neutral-400 dark:text-neutral-500 opacity-0 group-hover:opacity-100 transition-opacity mt-0.5" />
          </div>

          {item.summary && (
            <p className="text-xs text-neutral-500 dark:text-neutral-400 line-clamp-2 mt-1">
              {item.summary}
            </p>
          )}

          <div className="flex flex-wrap items-center gap-2 mt-2">
            <span className="text-xs text-neutral-500 dark:text-neutral-400">
              {item.source}
            </span>
            <span className="text-neutral-300 dark:text-neutral-600 text-xs">|</span>
            <span className="text-xs text-neutral-500 dark:text-neutral-400">
              {formatDistanceToNow(publishedDate, { addSuffix: true })}
            </span>
            <NewsSentimentBadge sentiment={item.sentiment} />
            {showSymbols && item.symbols.length > 0 && (
              <>
                <span className="text-neutral-300 dark:text-neutral-600 text-xs">|</span>
                {item.symbols.slice(0, 3).map((sym) => (
                  <span
                    key={sym}
                    className="px-1.5 py-0.5 text-xs font-medium bg-blue-100 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400 rounded"
                  >
                    {sym}
                  </span>
                ))}
                {item.symbols.length > 3 && (
                  <span className="text-xs text-neutral-400 dark:text-neutral-500">
                    +{item.symbols.length - 3}
                  </span>
                )}
              </>
            )}
          </div>
        </div>
      </div>
    </a>
  );
}
