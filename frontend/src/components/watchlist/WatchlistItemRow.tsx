'use client';

import Link from 'next/link';
import { TrendingUp, TrendingDown, Pencil, Trash2, MoreHorizontal } from 'lucide-react';
import { formatCurrency, formatPercent } from '@/lib/utils/format';
import type { WatchlistItem } from '@/lib/api/types';

interface WatchlistItemRowProps {
  item: WatchlistItem;
  onEdit: () => void;
  onRemove: () => void;
}

export function WatchlistItemRow({ item, onEdit, onRemove }: WatchlistItemRowProps) {
  const quote = item.quote;
  const change = quote ? Number(quote.change_percent) : 0;
  const isPositive = change >= 0;

  return (
    <tr className="border-b border-border last:border-0 hover:bg-muted/30 transition-colors group">
      <td className="p-4">
        <Link
          href={`/equity/${item.equity.symbol}`}
          className="hover:text-blue-500 transition-colors"
        >
          <div className="font-semibold text-foreground">
            {item.equity.symbol}
          </div>
          <div className="text-sm text-muted-foreground truncate max-w-[200px]">
            {item.equity.name}
          </div>
        </Link>
      </td>
      <td className="p-4 text-right">
        <span className="font-mono text-foreground">
          {quote ? formatCurrency(quote.price) : '--'}
        </span>
      </td>
      <td className="p-4 text-right">
        {quote ? (
          <div className="flex items-center justify-end gap-1">
            {isPositive ? (
              <TrendingUp className="h-4 w-4 text-emerald-500" />
            ) : (
              <TrendingDown className="h-4 w-4 text-red-500" />
            )}
            <span
              className={`font-mono ${
                isPositive ? 'text-emerald-500' : 'text-red-500'
              }`}
            >
              {formatPercent(quote.change_percent)}
            </span>
          </div>
        ) : (
          <span className="text-muted-foreground">--</span>
        )}
      </td>
      <td className="p-4 text-right hidden sm:table-cell">
        {item.target_price ? (
          <span className="font-mono text-foreground">
            {formatCurrency(item.target_price)}
          </span>
        ) : (
          <span className="text-muted-foreground">--</span>
        )}
      </td>
      <td className="p-4 hidden md:table-cell">
        {item.notes ? (
          <span className="text-sm text-muted-foreground line-clamp-1 max-w-[200px]">
            {item.notes}
          </span>
        ) : (
          <span className="text-muted-foreground text-sm">--</span>
        )}
      </td>
      <td className="p-4">
        <div className="flex items-center justify-end gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
          <button
            onClick={onEdit}
            className="p-1.5 text-muted-foreground hover:text-foreground hover:bg-muted rounded transition-colors"
            title="Edit item"
          >
            <Pencil className="h-4 w-4" />
          </button>
          <button
            onClick={onRemove}
            className="p-1.5 text-muted-foreground hover:text-red-500 hover:bg-red-500/10 rounded transition-colors"
            title="Remove from watchlist"
          >
            <Trash2 className="h-4 w-4" />
          </button>
        </div>
      </td>
    </tr>
  );
}
