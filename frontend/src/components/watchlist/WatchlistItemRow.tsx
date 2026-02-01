'use client';

import Link from 'next/link';
import { Pencil, Trash2, Calendar } from 'lucide-react';
import { formatCurrency } from '@/lib/utils/format';
import { PriceChange } from '@/components/ui/PriceChange';
import type { WatchlistItem } from '@/lib/api/types';

interface WatchlistItemRowProps {
  item: WatchlistItem;
  onEdit: () => void;
  onRemove: () => void;
}

function parseNumber(value: number | string | null | undefined): number {
  if (value === null || value === undefined) return 0;
  return typeof value === 'string' ? parseFloat(value) : value;
}

export function WatchlistItemRow({ item, onEdit, onRemove }: WatchlistItemRowProps) {
  const quote = item.quote;
  const changePercent = quote ? parseNumber(quote.change_percent) : 0;
  const isBigMove = Math.abs(changePercent) >= 3;
  const isPositive = changePercent >= 0;

  // Determine row background for big movers
  const rowBgClass = isBigMove
    ? isPositive
      ? 'bg-emerald-500/5'
      : 'bg-red-500/5'
    : '';

  return (
    <tr className={`border-b border-neutral-200 dark:border-neutral-700 last:border-0 hover:bg-neutral-50 dark:hover:bg-neutral-700/50 transition-colors group ${rowBgClass}`}>
      <td className="p-4">
        <Link
          href={`/equity/${item.equity.symbol}`}
          className="hover:text-blue-500 transition-colors"
        >
          <div className="flex items-center gap-1.5">
            <span className="font-semibold text-neutral-900 dark:text-neutral-50">
              {item.equity.symbol}
            </span>
            {item.track_calendar && (
              <Calendar className="h-3.5 w-3.5 text-blue-400" title="Calendar tracking enabled" />
            )}
          </div>
          <div className="text-sm text-neutral-500 dark:text-neutral-400 truncate max-w-[200px]">
            {item.equity.name}
          </div>
        </Link>
      </td>
      <td className="p-4 text-right">
        <span className="font-mono text-neutral-900 dark:text-neutral-50">
          {quote ? formatCurrency(quote.price) : '--'}
        </span>
      </td>
      <td className="p-4 text-right">
        {quote ? (
          <PriceChange
            value={changePercent}
            showIcon
            size="md"
          />
        ) : (
          <span className="text-neutral-500 dark:text-neutral-400">--</span>
        )}
      </td>
      <td className="p-4 text-right hidden sm:table-cell">
        {item.target_price ? (
          <span className="font-mono text-neutral-900 dark:text-neutral-50">
            {formatCurrency(item.target_price)}
          </span>
        ) : (
          <span className="text-neutral-500 dark:text-neutral-400">--</span>
        )}
      </td>
      <td className="p-4 hidden md:table-cell">
        {item.notes ? (
          <span className="text-sm text-neutral-500 dark:text-neutral-400 line-clamp-1 max-w-[200px]">
            {item.notes}
          </span>
        ) : (
          <span className="text-neutral-500 dark:text-neutral-400 text-sm">--</span>
        )}
      </td>
      <td className="p-4">
        <div className="flex items-center justify-end gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
          <button
            onClick={onEdit}
            className="p-1.5 text-neutral-400 hover:text-neutral-900 dark:hover:text-neutral-50 hover:bg-neutral-100 dark:hover:bg-neutral-700 rounded transition-colors"
            title="Edit item"
          >
            <Pencil className="h-4 w-4" />
          </button>
          <button
            onClick={onRemove}
            className="p-1.5 text-neutral-400 hover:text-red-500 hover:bg-red-500/10 rounded transition-colors"
            title="Remove from watchlist"
          >
            <Trash2 className="h-4 w-4" />
          </button>
        </div>
      </td>
    </tr>
  );
}
