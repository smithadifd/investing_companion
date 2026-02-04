'use client';

import Link from 'next/link';
import { PriceChange, getChangeBackgroundClass, getChangeHoverClass } from './PriceChange';

interface StockCardProps {
  symbol: string;
  name: string;
  price: number;
  changePercent: number;
  /** Rank/position number to display (optional) */
  rank?: number;
  /** Threshold for highlighting big moves (default: 3%) */
  highlightThreshold?: number;
  /** Whether to link to equity detail page (default: true) */
  linkToEquity?: boolean;
  /** Additional class names */
  className?: string;
  /** Optional subtitle text (e.g., watchlist name) */
  subtitle?: string;
}

/**
 * Reusable card component for displaying stock information with price changes.
 * Used in watchlist movers, market movers, and similar lists.
 */
export function StockCard({
  symbol,
  name,
  price,
  changePercent,
  rank,
  highlightThreshold = 3,
  linkToEquity = true,
  className = '',
  subtitle,
}: StockCardProps) {
  const bgClass = getChangeBackgroundClass(changePercent, highlightThreshold);
  const hoverClass = getChangeHoverClass(changePercent, highlightThreshold);

  const content = (
    <div
      className={`flex items-center justify-between p-3 rounded-lg border transition-all hover:shadow-md ${bgClass} ${hoverClass} ${className}`}
    >
      <div className="flex items-center gap-3">
        {rank !== undefined && (
          <span className="text-sm text-neutral-400 w-4">{rank}</span>
        )}
        <div>
          <p className="font-semibold text-neutral-900 dark:text-neutral-50">
            {symbol}
          </p>
          <p className="text-xs text-neutral-500 dark:text-neutral-400 truncate max-w-[120px]">
            {name}
          </p>
          {subtitle && (
            <p className="text-[10px] text-neutral-400 dark:text-neutral-500 truncate max-w-[120px]">
              {subtitle}
            </p>
          )}
        </div>
      </div>
      <div className="text-right">
        <p className="font-medium text-neutral-900 dark:text-neutral-50">
          ${price.toFixed(2)}
        </p>
        <PriceChange value={changePercent} size="sm" />
      </div>
    </div>
  );

  if (linkToEquity) {
    return <Link href={`/equity/${symbol}`}>{content}</Link>;
  }

  return content;
}

/**
 * Compact version for inline/row displays
 */
export function StockCardCompact({
  symbol,
  name,
  price,
  changePercent,
  linkToEquity = true,
}: Omit<StockCardProps, 'rank' | 'highlightThreshold' | 'className'>) {
  const isPositive = changePercent >= 0;
  const bgClass = isPositive ? 'bg-emerald-500/10' : 'bg-red-500/10';
  const borderClass = isPositive ? 'border-emerald-500/20' : 'border-red-500/20';
  const hoverBorderClass = isPositive
    ? 'hover:border-emerald-500/40'
    : 'hover:border-red-500/40';

  const content = (
    <div
      className={`flex-1 p-2 rounded-lg ${bgClass} border ${borderClass} ${hoverBorderClass} transition-colors`}
    >
      <div className="flex items-center justify-between">
        <span
          className={`text-xs ${
            isPositive
              ? 'text-emerald-600 dark:text-emerald-400'
              : 'text-red-600 dark:text-red-400'
          }`}
        >
          {name}
        </span>
        <PriceChange value={changePercent} size="sm" showSign />
      </div>
      <p className="font-semibold text-neutral-900 dark:text-neutral-50 truncate">
        {symbol}
      </p>
    </div>
  );

  if (linkToEquity) {
    return <Link href={`/equity/${symbol}`}>{content}</Link>;
  }

  return content;
}
