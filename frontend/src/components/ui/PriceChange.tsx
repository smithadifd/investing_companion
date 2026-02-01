'use client';

import { TrendingUp, TrendingDown } from 'lucide-react';

interface PriceChangeProps {
  value: number | string;
  showIcon?: boolean;
  showSign?: boolean;
  size?: 'sm' | 'md' | 'lg';
  className?: string;
}

/**
 * Reusable component for displaying price/percentage changes with consistent styling.
 * Handles positive (green) and negative (red) values with optional icons.
 */
export function PriceChange({
  value,
  showIcon = false,
  showSign = true,
  size = 'md',
  className = '',
}: PriceChangeProps) {
  const numValue = typeof value === 'string' ? parseFloat(value) : value;
  const isPositive = numValue >= 0;

  const sizeClasses = {
    sm: 'text-xs',
    md: 'text-sm',
    lg: 'text-base',
  };

  const iconSizes = {
    sm: 'h-3 w-3',
    md: 'h-4 w-4',
    lg: 'h-5 w-5',
  };

  const colorClass = isPositive
    ? 'text-emerald-600 dark:text-emerald-400'
    : 'text-red-600 dark:text-red-400';

  const formattedValue = `${showSign && isPositive ? '+' : ''}${numValue.toFixed(2)}%`;

  return (
    <span className={`inline-flex items-center gap-1 font-medium ${colorClass} ${sizeClasses[size]} ${className}`}>
      {showIcon && (
        isPositive ? (
          <TrendingUp className={iconSizes[size]} />
        ) : (
          <TrendingDown className={iconSizes[size]} />
        )
      )}
      {formattedValue}
    </span>
  );
}

/**
 * Utility function to get the appropriate background color class for a change value.
 * Use for card backgrounds to highlight big movers.
 */
export function getChangeBackgroundClass(
  value: number | string,
  threshold = 3
): string {
  const numValue = typeof value === 'string' ? parseFloat(value) : value;
  const absValue = Math.abs(numValue);
  const isPositive = numValue >= 0;

  if (absValue >= threshold) {
    return isPositive
      ? 'bg-emerald-500/10 border-emerald-500/30'
      : 'bg-red-500/10 border-red-500/30';
  }

  return 'bg-white dark:bg-neutral-800 border-neutral-200 dark:border-neutral-700';
}

/**
 * Utility function to get hover classes that match the change background.
 */
export function getChangeHoverClass(
  value: number | string,
  threshold = 3
): string {
  const numValue = typeof value === 'string' ? parseFloat(value) : value;
  const absValue = Math.abs(numValue);
  const isPositive = numValue >= 0;

  if (absValue >= threshold) {
    return isPositive
      ? 'hover:border-emerald-500/50'
      : 'hover:border-red-500/50';
  }

  return 'hover:border-neutral-300 dark:hover:border-neutral-600';
}
