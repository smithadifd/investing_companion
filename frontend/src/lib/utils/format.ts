/**
 * Formatting utilities
 */

/**
 * Format a number as currency (USD)
 */
export function formatCurrency(value: number | null | undefined): string {
  if (value == null) return '--';
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value);
}

/**
 * Format a number as a percentage
 */
export function formatPercent(value: number | null | undefined): string {
  if (value == null) return '--';
  const prefix = value >= 0 ? '+' : '';
  return `${prefix}${value.toFixed(2)}%`;
}

/**
 * Format a number with commas
 */
export function formatNumber(value: number | null | undefined): string {
  if (value == null) return '--';
  return new Intl.NumberFormat('en-US', {
    maximumFractionDigits: 2,
  }).format(value);
}

/**
 * Format a large number with abbreviation (K, M, B, T)
 */
export function formatLargeNumber(value: number | null | undefined): string {
  if (value == null) return '--';

  const absValue = Math.abs(value);

  if (absValue >= 1e12) {
    return `${(value / 1e12).toFixed(2)}T`;
  }
  if (absValue >= 1e9) {
    return `${(value / 1e9).toFixed(2)}B`;
  }
  if (absValue >= 1e6) {
    return `${(value / 1e6).toFixed(2)}M`;
  }
  if (absValue >= 1e3) {
    return `${(value / 1e3).toFixed(2)}K`;
  }

  return value.toLocaleString('en-US');
}

/**
 * Format a ratio/multiple
 */
export function formatRatio(value: number | null | undefined): string {
  if (value == null) return '--';
  return value.toFixed(2);
}

/**
 * Format a date for display
 */
export function formatDate(dateString: string): string {
  const date = new Date(dateString);
  return new Intl.DateTimeFormat('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  }).format(date);
}
