'use client';

import Link from 'next/link';
import {
  Calendar,
  TrendingUp,
  Landmark,
  DollarSign,
  ChevronRight,
  RefreshCw,
  AlertCircle,
} from 'lucide-react';
import { useUpcomingEvents } from '@/lib/hooks/useEvents';
import type { EconomicEvent, EventType } from '@/lib/api/types';

// Event type icons and colors
const EVENT_CONFIG: Record<EventType, { icon: React.ReactNode; color: string }> = {
  earnings: { icon: <TrendingUp className="h-3.5 w-3.5" />, color: 'bg-blue-500' },
  ex_dividend: { icon: <DollarSign className="h-3.5 w-3.5" />, color: 'bg-teal-500' },
  dividend_pay: { icon: <DollarSign className="h-3.5 w-3.5" />, color: 'bg-teal-400' },
  stock_split: { icon: <TrendingUp className="h-3.5 w-3.5" />, color: 'bg-pink-500' },
  fomc: { icon: <Landmark className="h-3.5 w-3.5" />, color: 'bg-purple-500' },
  cpi: { icon: <TrendingUp className="h-3.5 w-3.5" />, color: 'bg-orange-500' },
  ppi: { icon: <TrendingUp className="h-3.5 w-3.5" />, color: 'bg-orange-400' },
  nfp: { icon: <TrendingUp className="h-3.5 w-3.5" />, color: 'bg-green-500' },
  gdp: { icon: <TrendingUp className="h-3.5 w-3.5" />, color: 'bg-yellow-500' },
  pce: { icon: <TrendingUp className="h-3.5 w-3.5" />, color: 'bg-amber-500' },
  retail_sales: { icon: <TrendingUp className="h-3.5 w-3.5" />, color: 'bg-lime-500' },
  unemployment: { icon: <TrendingUp className="h-3.5 w-3.5" />, color: 'bg-red-400' },
  ism_manufacturing: { icon: <TrendingUp className="h-3.5 w-3.5" />, color: 'bg-indigo-400' },
  ism_services: { icon: <TrendingUp className="h-3.5 w-3.5" />, color: 'bg-indigo-300' },
  housing_starts: { icon: <TrendingUp className="h-3.5 w-3.5" />, color: 'bg-cyan-500' },
  consumer_confidence: { icon: <TrendingUp className="h-3.5 w-3.5" />, color: 'bg-emerald-400' },
  custom: { icon: <Calendar className="h-3.5 w-3.5" />, color: 'bg-gray-500' },
  ipo: { icon: <TrendingUp className="h-3.5 w-3.5" />, color: 'bg-rose-500' },
};

// Format date relative to today
function formatEventDate(dateStr: string): string {
  const date = new Date(dateStr + 'T00:00:00');
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const tomorrow = new Date(today);
  tomorrow.setDate(tomorrow.getDate() + 1);

  if (date.getTime() === today.getTime()) {
    return 'Today';
  }
  if (date.getTime() === tomorrow.getTime()) {
    return 'Tomorrow';
  }

  // Show day of week for this week
  const daysUntil = Math.ceil((date.getTime() - today.getTime()) / (1000 * 60 * 60 * 24));
  if (daysUntil <= 7) {
    return date.toLocaleDateString('en-US', { weekday: 'short' });
  }

  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

// Event item component
function EventItem({ event }: { event: EconomicEvent }) {
  const config = EVENT_CONFIG[event.event_type] || EVENT_CONFIG.custom;
  const dateLabel = formatEventDate(event.event_date);
  const isToday = dateLabel === 'Today';
  const isTomorrow = dateLabel === 'Tomorrow';

  return (
    <div className="flex items-center gap-3 py-2">
      <div className={`${config.color} p-1.5 rounded text-white flex-shrink-0`}>
        {config.icon}
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="font-medium text-sm text-neutral-900 dark:text-neutral-100 truncate">
            {event.equity?.symbol || event.title}
          </span>
          {event.importance === 'high' && (
            <span className="w-1.5 h-1.5 rounded-full bg-red-500 flex-shrink-0" />
          )}
        </div>
        <div className="text-xs text-neutral-500 dark:text-neutral-400 truncate">
          {event.equity ? event.title : (event.description || event.event_type.replace('_', ' '))}
        </div>
      </div>
      <div className={`text-xs font-medium flex-shrink-0 ${
        isToday
          ? 'text-blue-600 dark:text-blue-400'
          : isTomorrow
          ? 'text-amber-600 dark:text-amber-400'
          : 'text-neutral-500 dark:text-neutral-400'
      }`}>
        {dateLabel}
      </div>
    </div>
  );
}

export function UpcomingEvents() {
  const { data, isLoading, error, refetch } = useUpcomingEvents(7, { limit: 8 });

  return (
    <div className="bg-white dark:bg-neutral-800 border border-neutral-200 dark:border-neutral-700 rounded-xl p-4">
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <h2 className="font-semibold text-neutral-900 dark:text-neutral-100 flex items-center gap-2">
          <Calendar className="h-4 w-4 text-blue-500" />
          Upcoming Events
        </h2>
        <Link
          href="/calendar"
          className="text-xs text-blue-600 dark:text-blue-400 hover:underline flex items-center gap-1"
        >
          View all
          <ChevronRight className="h-3 w-3" />
        </Link>
      </div>

      {/* Content */}
      {isLoading ? (
        <div className="flex items-center justify-center py-8">
          <RefreshCw className="h-5 w-5 animate-spin text-neutral-400" />
        </div>
      ) : error ? (
        <div className="flex items-center justify-center py-8 text-neutral-500 dark:text-neutral-400">
          <AlertCircle className="h-5 w-5 mr-2" />
          <span className="text-sm">Failed to load events</span>
        </div>
      ) : !data?.events || data.events.length === 0 ? (
        <div className="text-center py-8 text-neutral-500 dark:text-neutral-400">
          <Calendar className="h-8 w-8 mx-auto mb-2 opacity-50" />
          <p className="text-sm">No upcoming events</p>
        </div>
      ) : (
        <div className="divide-y divide-neutral-100 dark:divide-neutral-700/50">
          {data.events.map((event) => (
            <EventItem key={event.id} event={event} />
          ))}
        </div>
      )}

      {/* Footer */}
      {data && data.events.length > 0 && (
        <div className="mt-3 pt-3 border-t border-neutral-100 dark:border-neutral-700/50 text-xs text-neutral-500 dark:text-neutral-400 text-center">
          Showing next {data.days_ahead} days
        </div>
      )}
    </div>
  );
}
