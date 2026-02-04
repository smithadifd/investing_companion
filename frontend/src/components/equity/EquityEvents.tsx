'use client';

import { useState, useEffect } from 'react';
import Link from 'next/link';
import {
  Calendar,
  DollarSign,
  TrendingUp,
  Loader2,
  ChevronRight,
  RefreshCw,
  AlertCircle,
  Trash2,
} from 'lucide-react';
import { useEquityEvents, useRefreshEquityEvents, useDeleteEquityEvents } from '@/lib/hooks/useEvents';
import { formatDistanceToNow, format } from 'date-fns';
import type { EconomicEvent, EventType } from '@/lib/api/types';
import { ConfirmModal } from '@/components/ui/ConfirmModal';

interface Props {
  symbol: string;
}

const EVENT_TYPE_CONFIG: Record<EventType, { icon: typeof Calendar; label: string; color: string }> = {
  earnings: { icon: DollarSign, label: 'Earnings', color: 'text-green-600 dark:text-green-400' },
  ex_dividend: { icon: DollarSign, label: 'Ex-Dividend', color: 'text-blue-600 dark:text-blue-400' },
  dividend_pay: { icon: DollarSign, label: 'Dividend Pay', color: 'text-blue-600 dark:text-blue-400' },
  stock_split: { icon: TrendingUp, label: 'Stock Split', color: 'text-purple-600 dark:text-purple-400' },
  custom: { icon: Calendar, label: 'Custom', color: 'text-neutral-600 dark:text-neutral-400' },
  ipo: { icon: TrendingUp, label: 'IPO', color: 'text-orange-600 dark:text-orange-400' },
  fomc: { icon: Calendar, label: 'FOMC', color: 'text-red-600 dark:text-red-400' },
  cpi: { icon: Calendar, label: 'CPI', color: 'text-red-600 dark:text-red-400' },
  ppi: { icon: Calendar, label: 'PPI', color: 'text-red-600 dark:text-red-400' },
  nfp: { icon: Calendar, label: 'Jobs Report', color: 'text-red-600 dark:text-red-400' },
  gdp: { icon: Calendar, label: 'GDP', color: 'text-red-600 dark:text-red-400' },
  pce: { icon: Calendar, label: 'PCE', color: 'text-red-600 dark:text-red-400' },
  retail_sales: { icon: Calendar, label: 'Retail Sales', color: 'text-red-600 dark:text-red-400' },
  unemployment: { icon: Calendar, label: 'Unemployment', color: 'text-red-600 dark:text-red-400' },
  ism_manufacturing: { icon: Calendar, label: 'ISM Manufacturing', color: 'text-red-600 dark:text-red-400' },
  ism_services: { icon: Calendar, label: 'ISM Services', color: 'text-red-600 dark:text-red-400' },
  housing_starts: { icon: Calendar, label: 'Housing Starts', color: 'text-red-600 dark:text-red-400' },
  consumer_confidence: { icon: Calendar, label: 'Consumer Confidence', color: 'text-red-600 dark:text-red-400' },
};

export function EquityEvents({ symbol }: Props) {
  const [includePast, setIncludePast] = useState(false);
  const [showUntrackConfirm, setShowUntrackConfirm] = useState(false);
  const [hasAutoFetched, setHasAutoFetched] = useState(false);
  const { data: events, isLoading, error, refetch } = useEquityEvents(symbol, includePast);
  const refreshMutation = useRefreshEquityEvents();
  const deleteMutation = useDeleteEquityEvents();

  const hasEvents = events && events.length > 0;

  // Auto-fetch events when component mounts if no events exist
  useEffect(() => {
    if (!isLoading && !hasEvents && !hasAutoFetched && !error) {
      setHasAutoFetched(true);
      refreshMutation.mutateAsync(symbol).then(() => {
        refetch();
      }).catch(() => {
        // Silently fail - user can manually refresh
      });
    }
  }, [isLoading, hasEvents, hasAutoFetched, error, symbol, refreshMutation, refetch]);

  // Reset auto-fetch flag when symbol changes
  useEffect(() => {
    setHasAutoFetched(false);
  }, [symbol]);

  const handleRefresh = async () => {
    try {
      await refreshMutation.mutateAsync(symbol);
      refetch();
    } catch (err) {
      // Error handled by mutation
    }
  };

  const handleUntrack = async () => {
    try {
      await deleteMutation.mutateAsync(symbol);
      setShowUntrackConfirm(false);
      refetch();
    } catch (err) {
      // Error handled by mutation
    }
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-8">
        <Loader2 className="h-6 w-6 animate-spin text-blue-500" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center py-8 text-neutral-500 dark:text-neutral-400">
        <AlertCircle className="h-5 w-5 mr-2" />
        Failed to load events
      </div>
    );
  }

  return (
    <div>
      {/* Header with controls */}
      <div className="flex flex-wrap items-center justify-between gap-2 mb-4">
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-2 cursor-pointer text-sm text-neutral-600 dark:text-neutral-400">
            <input
              type="checkbox"
              checked={includePast}
              onChange={(e) => setIncludePast(e.target.checked)}
              className="rounded border-neutral-300 dark:border-neutral-600"
            />
            Show past events
          </label>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleRefresh}
            disabled={refreshMutation.isPending}
            className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-neutral-100 dark:bg-neutral-700 text-neutral-700 dark:text-neutral-300 rounded-lg hover:bg-neutral-200 dark:hover:bg-neutral-600 transition-colors disabled:opacity-50"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${refreshMutation.isPending ? 'animate-spin' : ''}`} />
            Refresh
          </button>
          {hasEvents && (
            <button
              onClick={() => setShowUntrackConfirm(true)}
              disabled={deleteMutation.isPending}
              className="flex items-center gap-1.5 px-3 py-1.5 text-sm text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 rounded-lg transition-colors disabled:opacity-50"
            >
              <Trash2 className="h-3.5 w-3.5" />
              Untrack
            </button>
          )}
        </div>
      </div>

      {/* Events list */}
      {refreshMutation.isPending && !hasEvents ? (
        <div className="flex items-center justify-center py-8">
          <Loader2 className="h-6 w-6 animate-spin text-blue-500 mr-2" />
          <span className="text-neutral-500 dark:text-neutral-400">Loading events...</span>
        </div>
      ) : events && events.length > 0 ? (
        <div className="space-y-2">
          {events.map((event) => (
            <EventRow key={event.id} event={event} />
          ))}
        </div>
      ) : (
        <div className="text-center py-8 text-neutral-500 dark:text-neutral-400">
          <Calendar className="h-8 w-8 mx-auto mb-2 opacity-50" />
          <p className="text-sm">No upcoming events for {symbol}</p>
          <p className="text-xs mt-1">Click Refresh to check for earnings and dividend dates</p>
        </div>
      )}

      {/* Link to calendar */}
      <div className="mt-4 pt-4 border-t border-neutral-200 dark:border-neutral-700">
        <Link
          href="/calendar"
          className="flex items-center justify-center gap-2 text-sm text-blue-500 hover:text-blue-600 dark:text-blue-400 dark:hover:text-blue-300"
        >
          View full calendar
          <ChevronRight className="h-4 w-4" />
        </Link>
      </div>

      {/* Untrack confirmation modal */}
      {showUntrackConfirm && (
        <ConfirmModal
          title="Stop Tracking Events"
          message={`Are you sure you want to stop tracking events for ${symbol}? This will remove all earnings, dividend, and other auto-fetched events for this equity.`}
          confirmLabel="Untrack"
          variant="danger"
          isLoading={deleteMutation.isPending}
          onConfirm={handleUntrack}
          onCancel={() => setShowUntrackConfirm(false)}
        />
      )}
    </div>
  );
}

function EventRow({ event }: { event: EconomicEvent }) {
  const config = EVENT_TYPE_CONFIG[event.event_type] || EVENT_TYPE_CONFIG.custom;
  const Icon = config.icon;
  const eventDate = new Date(event.event_date);
  const isUpcoming = eventDate >= new Date(new Date().toDateString());

  return (
    <div className={`flex items-center gap-3 p-3 rounded-lg border transition-colors ${
      isUpcoming
        ? 'bg-white dark:bg-neutral-800 border-neutral-200 dark:border-neutral-700'
        : 'bg-neutral-50 dark:bg-neutral-800/50 border-neutral-100 dark:border-neutral-700/50 opacity-75'
    }`}>
      <div className={`p-2 rounded-lg bg-neutral-100 dark:bg-neutral-700 ${config.color}`}>
        <Icon className="h-4 w-4" />
      </div>

      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="font-medium text-neutral-900 dark:text-neutral-100 truncate">
            {event.title}
          </span>
          {event.importance === 'high' && (
            <span className="px-1.5 py-0.5 text-xs font-medium bg-red-100 dark:bg-red-900/30 text-red-600 dark:text-red-400 rounded">
              High
            </span>
          )}
        </div>
        <div className="flex items-center gap-2 text-xs text-neutral-500 dark:text-neutral-400">
          <span>{format(eventDate, 'MMM d, yyyy')}</span>
          {event.event_time && !event.all_day && (
            <>
              <span>at</span>
              <span>{event.event_time}</span>
            </>
          )}
          {isUpcoming && (
            <>
              <span className="text-neutral-300 dark:text-neutral-600">|</span>
              <span className="text-blue-500 dark:text-blue-400">
                {formatDistanceToNow(eventDate, { addSuffix: true })}
              </span>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
