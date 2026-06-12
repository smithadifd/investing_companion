'use client';

import { Layers } from 'lucide-react';
import { useExposure } from '@/lib/hooks/useDashboard';

function toNumber(value: number | string | null | undefined): number {
  if (value === null || value === undefined) return 0;
  return typeof value === 'string' ? parseFloat(value) : value;
}

function formatCurrency(value: number | string | null | undefined): string {
  if (value === null || value === undefined) return '—';
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 0,
  }).format(toNumber(value));
}

/**
 * Held exposure grouped by single-catalyst cluster. Renders nothing until the
 * user has tagged watchlist items with catalysts and holds something in one.
 */
export function CatalystExposure() {
  const { data, isLoading, error } = useExposure();

  if (isLoading || error || !data?.catalysts || data.catalysts.length === 0) {
    return null;
  }

  return (
    <div className="bg-white dark:bg-neutral-800 border border-neutral-200 dark:border-neutral-700 rounded-xl p-4">
      <h2 className="font-semibold text-neutral-900 dark:text-neutral-100 flex items-center gap-2 mb-3">
        <Layers className="h-4 w-4 text-amber-500" />
        Catalyst Exposure
      </h2>
      <p className="text-xs text-neutral-500 dark:text-neutral-400 mb-3">
        Held value per catalyst cluster. Overlapping — a holding can carry
        several catalysts. Percentages cover entered holdings only.
      </p>
      <div className="space-y-2.5">
        {data.catalysts.map((c) => (
          <div key={c.catalyst}>
            <div className="flex items-center justify-between text-sm">
              <span className="font-medium text-neutral-900 dark:text-neutral-100 capitalize">
                {c.catalyst}
              </span>
              <span className="text-neutral-500 dark:text-neutral-400">
                {formatCurrency(c.value)}
                {c.percent_of_portfolio !== null && (
                  <span className="ml-1 text-xs">
                    ({toNumber(c.percent_of_portfolio).toFixed(1)}%)
                  </span>
                )}
              </span>
            </div>
            <div className="text-xs text-neutral-500 dark:text-neutral-400">
              {c.symbols.join(', ')} · {c.position_count} position
              {c.position_count > 1 ? 's' : ''}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
