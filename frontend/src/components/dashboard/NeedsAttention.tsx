'use client';

import Link from 'next/link';
import { Bell, ChevronRight, Crosshair, Target, Zap } from 'lucide-react';
import { useNeedsAttention } from '@/lib/hooks/useDashboard';
import type { NeedsAttentionItem } from '@/lib/api/types';

// Helper to convert string/number to number
function toNumber(value: number | string | null | undefined): number {
  if (value === null || value === undefined) return 0;
  return typeof value === 'string' ? parseFloat(value) : value;
}

// Format time ago
function formatTimeAgo(dateString: string | null): string {
  if (!dateString) return '';
  const date = new Date(dateString);
  const now = new Date();
  const seconds = Math.floor((now.getTime() - date.getTime()) / 1000);

  if (seconds < 60) return 'just now';
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

function AttentionRow({ item }: { item: NeedsAttentionItem }) {
  if (item.kind === 'alert_triggered') {
    return (
      <div className="flex items-center gap-3 py-2">
        <div className="bg-red-500 p-1.5 rounded text-white flex-shrink-0">
          <Bell className="h-3.5 w-3.5" />
        </div>
        <div className="flex-1 min-w-0">
          <span className="font-medium text-sm text-neutral-900 dark:text-neutral-100">
            {item.title} triggered
          </span>
          {item.detail && (
            <div className="text-xs text-neutral-500 dark:text-neutral-400 truncate">
              {item.detail}
            </div>
          )}
        </div>
        <div className="text-xs font-medium text-red-600 dark:text-red-400 flex-shrink-0">
          {formatTimeAgo(item.last_triggered_at)}
        </div>
      </div>
    );
  }

  if (item.kind === 'alert_approaching') {
    const distance = toNumber(item.distance_percent);
    return (
      <div className="flex items-center gap-3 py-2">
        <div className="bg-amber-500 p-1.5 rounded text-white flex-shrink-0">
          <Crosshair className="h-3.5 w-3.5" />
        </div>
        <div className="flex-1 min-w-0">
          <span className="font-medium text-sm text-neutral-900 dark:text-neutral-100">
            {item.title}
          </span>
          {item.last_checked_value !== null && (
            <div className="text-xs text-neutral-500 dark:text-neutral-400">
              last {toNumber(item.last_checked_value).toFixed(2)}
            </div>
          )}
        </div>
        <div className="text-xs font-medium text-amber-600 dark:text-amber-400 flex-shrink-0">
          {distance > 0 ? '+' : ''}
          {distance.toFixed(1)}% away
        </div>
      </div>
    );
  }

  // target_near
  return (
    <div className="flex items-center gap-3 py-2">
      <div className="bg-blue-500 p-1.5 rounded text-white flex-shrink-0">
        <Target className="h-3.5 w-3.5" />
      </div>
      <div className="flex-1 min-w-0">
        <span className="font-medium text-sm text-neutral-900 dark:text-neutral-100">
          {item.symbol}
        </span>
        <div className="text-xs text-neutral-500 dark:text-neutral-400 truncate">
          target ${toNumber(item.target_price).toFixed(2)}
          {item.detail ? ` · ${item.detail}` : ''}
        </div>
      </div>
      <div className="text-xs font-medium text-blue-600 dark:text-blue-400 flex-shrink-0">
        {Math.abs(toNumber(item.distance_percent)).toFixed(1)}% to target
      </div>
    </div>
  );
}

export function NeedsAttention() {
  const { data, isLoading, error } = useNeedsAttention();

  // Decisions-first section: stay out of the way unless something needs one
  if (isLoading || error || !data?.items || data.items.length === 0) {
    return null;
  }

  return (
    <div className="bg-white dark:bg-neutral-800 border border-amber-300 dark:border-amber-700/60 rounded-xl p-4 mb-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <h2 className="font-semibold text-neutral-900 dark:text-neutral-100 flex items-center gap-2">
          <Zap className="h-4 w-4 text-amber-500" />
          Needs Attention
        </h2>
        <Link
          href="/alerts"
          className="text-xs text-blue-600 dark:text-blue-400 hover:underline flex items-center gap-1"
        >
          View alerts
          <ChevronRight className="h-3 w-3" />
        </Link>
      </div>

      {/* Items */}
      <div className="divide-y divide-neutral-100 dark:divide-neutral-700/50">
        {data.items.map((item, index) => (
          <AttentionRow key={`${item.kind}-${item.title}-${index}`} item={item} />
        ))}
      </div>
    </div>
  );
}
