'use client';

import Link from 'next/link';
import {
  BellOff,
  CalendarClock,
  CheckCircle2,
  ChevronRight,
  ClipboardList,
  Crosshair,
} from 'lucide-react';
import { useTradeReadiness } from '@/lib/hooks/useDashboard';
import type { TradeReadinessItem } from '@/lib/api/types';

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

// Tier chip colors, matching the playbook page
const TIER_CHIPS: Record<string, string> = {
  yellow: 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400',
  orange: 'bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-400',
  red: 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400',
};

function PositionContext({ item }: { item: TradeReadinessItem }) {
  if (item.positions.length === 0) {
    return <span>No position</span>;
  }
  return (
    <span>
      {item.positions
        .map(
          // Number(toFixed) trims fractional shares to 2dp without "50.00"
          (p) =>
            `Holding ${Number(toNumber(p.quantity).toFixed(2))} ${p.symbol} @ $${toNumber(
              p.avg_cost_basis
            ).toFixed(2)}`
        )
        .join(' · ')}
    </span>
  );
}

function ReadinessRow({ item }: { item: TradeReadinessItem }) {
  const isHit = item.signal === 'hit';
  const distance = toNumber(item.distance_percent);

  return (
    <div className="py-2.5">
      <div className="flex items-center gap-3">
        <div
          className={`p-1.5 rounded text-white flex-shrink-0 ${
            isHit ? 'bg-emerald-600' : 'bg-amber-500'
          }`}
        >
          {isHit ? (
            <CheckCircle2 className="h-3.5 w-3.5" />
          ) : (
            <Crosshair className="h-3.5 w-3.5" />
          )}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-medium text-sm text-neutral-900 dark:text-neutral-100">
              {item.name}
            </span>
            {item.tier && (
              <span
                className={`text-[10px] px-1.5 py-0.5 rounded-full capitalize ${
                  TIER_CHIPS[item.tier] ??
                  'bg-neutral-100 text-neutral-600 dark:bg-neutral-700 dark:text-neutral-300'
                }`}
              >
                {item.tier}
              </span>
            )}
          </div>
          <div className="text-xs text-neutral-500 dark:text-neutral-400 truncate">
            {item.action}
          </div>
        </div>
        <div
          className={`text-xs font-medium flex-shrink-0 ${
            isHit
              ? 'text-emerald-600 dark:text-emerald-400'
              : 'text-amber-600 dark:text-amber-400'
          }`}
        >
          {isHit
            ? `Ready · hit ${formatTimeAgo(item.last_triggered_at)}`
            : item.distance_percent !== null
              ? `${distance > 0 ? '+' : ''}${distance.toFixed(1)}% away`
              : 'Approaching'}
        </div>
      </div>

      {/* Context line: position + cautions */}
      <div className="flex items-center gap-3 flex-wrap mt-1 ml-9 text-xs text-neutral-500 dark:text-neutral-400">
        <PositionContext item={item} />
        {item.upcoming_events.map((event) => (
          <span
            key={`${event.symbol}-${event.title}-${event.event_date}`}
            className="flex items-center gap-1 text-amber-600 dark:text-amber-400"
          >
            <CalendarClock className="h-3 w-3" />
            {event.symbol ? `${event.symbol} ` : ''}
            {event.title.toLowerCase().includes('earnings') ? 'earnings' : event.title}{' '}
            in {event.days_away}d
          </span>
        ))}
        {item.inactive_alert_count > 0 && (
          <span className="flex items-center gap-1 text-red-600 dark:text-red-400">
            <BellOff className="h-3 w-3" />
            {item.inactive_alert_count} alert
            {item.inactive_alert_count > 1 ? 's' : ''} disabled
          </span>
        )}
      </div>
    </div>
  );
}

export function TradeReadiness() {
  const { data, isLoading, error } = useTradeReadiness();

  // Only surfaces when a standing order is actionable - stays hidden otherwise
  if (isLoading || error || !data?.items || data.items.length === 0) {
    return null;
  }

  return (
    <div className="bg-white dark:bg-neutral-800 border border-emerald-300 dark:border-emerald-700/60 rounded-xl p-4 mb-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <h2 className="font-semibold text-neutral-900 dark:text-neutral-100 flex items-center gap-2">
          <ClipboardList className="h-4 w-4 text-emerald-500" />
          Trade Readiness
        </h2>
        <Link
          href="/playbook"
          className="text-xs text-blue-600 dark:text-blue-400 hover:underline flex items-center gap-1"
        >
          Open playbook
          <ChevronRight className="h-3 w-3" />
        </Link>
      </div>

      {/* Items */}
      <div className="divide-y divide-neutral-100 dark:divide-neutral-700/50">
        {data.items.map((item) => (
          <ReadinessRow key={item.trigger_id} item={item} />
        ))}
      </div>
    </div>
  );
}
