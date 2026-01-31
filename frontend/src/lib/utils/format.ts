/**
 * Formatting utilities
 * Note: API may return numbers as strings (from Python Decimal), so we convert first
 */

/**
 * Safely convert value to number
 */
function toNumber(value: unknown): number | null {
  if (value == null) return null;
  const num = typeof value === 'string' ? parseFloat(value) : Number(value);
  return isNaN(num) ? null : num;
}

/**
 * Format a number as currency (USD)
 */
export function formatCurrency(value: number | string | null | undefined): string {
  const num = toNumber(value);
  if (num == null) return '--';
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(num);
}

/**
 * Format a number as a percentage
 */
export function formatPercent(value: number | string | null | undefined): string {
  const num = toNumber(value);
  if (num == null) return '--';
  const prefix = num >= 0 ? '+' : '';
  return `${prefix}${num.toFixed(2)}%`;
}

/**
 * Format a number with commas
 */
export function formatNumber(value: number | string | null | undefined): string {
  const num = toNumber(value);
  if (num == null) return '--';
  return new Intl.NumberFormat('en-US', {
    maximumFractionDigits: 2,
  }).format(num);
}

/**
 * Format a large number with abbreviation (K, M, B, T)
 */
export function formatLargeNumber(value: number | string | null | undefined): string {
  const num = toNumber(value);
  if (num == null) return '--';

  const absValue = Math.abs(num);

  if (absValue >= 1e12) {
    return `${(num / 1e12).toFixed(2)}T`;
  }
  if (absValue >= 1e9) {
    return `${(num / 1e9).toFixed(2)}B`;
  }
  if (absValue >= 1e6) {
    return `${(num / 1e6).toFixed(2)}M`;
  }
  if (absValue >= 1e3) {
    return `${(num / 1e3).toFixed(2)}K`;
  }

  return num.toLocaleString('en-US');
}

/**
 * Format a ratio/multiple
 */
export function formatRatio(value: number | string | null | undefined): string {
  const num = toNumber(value);
  if (num == null) return '--';
  return num.toFixed(2);
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
