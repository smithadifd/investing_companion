'use client';

import { useState } from 'react';
import { X, Calendar, Clock, Trash2, ExternalLink, Loader2, EyeOff } from 'lucide-react';
import type { EconomicEvent, EventType } from '@/lib/api/types';
import { useDeleteEvent, useDeleteEquityEvents } from '@/lib/hooks/useEvents';
import { ConfirmModal } from '@/components/ui/ConfirmModal';

// Event type configuration
const EVENT_TYPE_CONFIG: Record<EventType, { label: string; color: string }> = {
  earnings: { label: 'Earnings', color: 'bg-blue-500' },
  ex_dividend: { label: 'Ex-Dividend', color: 'bg-teal-500' },
  dividend_pay: { label: 'Dividend Payment', color: 'bg-teal-400' },
  stock_split: { label: 'Stock Split', color: 'bg-pink-500' },
  fomc: { label: 'FOMC Meeting', color: 'bg-purple-500' },
  cpi: { label: 'CPI Release', color: 'bg-orange-500' },
  ppi: { label: 'PPI Release', color: 'bg-orange-400' },
  nfp: { label: 'Jobs Report (NFP)', color: 'bg-green-500' },
  gdp: { label: 'GDP Release', color: 'bg-yellow-500' },
  pce: { label: 'PCE Price Index', color: 'bg-amber-500' },
  retail_sales: { label: 'Retail Sales', color: 'bg-lime-500' },
  unemployment: { label: 'Unemployment', color: 'bg-red-400' },
  ism_manufacturing: { label: 'ISM Manufacturing', color: 'bg-indigo-400' },
  ism_services: { label: 'ISM Services', color: 'bg-indigo-300' },
  housing_starts: { label: 'Housing Starts', color: 'bg-cyan-500' },
  consumer_confidence: { label: 'Consumer Confidence', color: 'bg-emerald-400' },
  custom: { label: 'Custom Event', color: 'bg-gray-500' },
  ipo: { label: 'IPO', color: 'bg-rose-500' },
};

interface Props {
  event: EconomicEvent;
  onClose: () => void;
  onDeleted?: () => void;
}

export function EventDetailModal({ event, onClose, onDeleted }: Props) {
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [showUntrackConfirm, setShowUntrackConfirm] = useState(false);
  const deleteMutation = useDeleteEvent();
  const untrackMutation = useDeleteEquityEvents();

  const config = EVENT_TYPE_CONFIG[event.event_type] || EVENT_TYPE_CONFIG.custom;
  const eventDate = new Date(event.event_date + 'T00:00:00');

  // Only allow delete for custom events (user-created)
  const canDelete = event.source === 'manual' && event.user_id !== null;

  // Allow untracking for equity events that aren't custom
  const canUntrack = event.equity && event.source !== 'manual';

  const handleDelete = async () => {
    try {
      await deleteMutation.mutateAsync(event.id);
      setShowDeleteConfirm(false);
      onDeleted?.();
      onClose();
    } catch (error) {
      console.error('Failed to delete event:', error);
    }
  };

  const handleUntrack = async () => {
    if (!event.equity) return;
    try {
      await untrackMutation.mutateAsync(event.equity.symbol);
      setShowUntrackConfirm(false);
      onDeleted?.();
      onClose();
    } catch (error) {
      console.error('Failed to untrack equity:', error);
    }
  };

  // Format value for display
  const formatValue = (value: number | string | null | undefined) => {
    if (value === null || value === undefined) return '—';
    const num = typeof value === 'string' ? parseFloat(value) : value;
    return num.toFixed(2);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/50"
        onClick={onClose}
      />

      {/* Modal */}
      <div className="relative bg-white dark:bg-neutral-800 rounded-xl shadow-xl w-full max-w-lg mx-4 overflow-hidden">
        {/* Header */}
        <div className={`${config.color} px-6 py-4`}>
          <div className="flex items-start justify-between">
            <div className="flex items-center gap-3">
              <div className="text-white/90 text-sm font-medium uppercase tracking-wide">
                {config.label}
              </div>
            </div>
            <button
              onClick={onClose}
              className="p-1 hover:bg-white/20 rounded-lg transition-colors"
            >
              <X className="h-5 w-5 text-white" />
            </button>
          </div>
          <h2 className="text-xl font-bold text-white mt-2">
            {event.title}
          </h2>
          {event.equity && (
            <a
              href={`/equity/${event.equity.symbol}`}
              className="inline-flex items-center gap-1 text-white/90 hover:text-white text-sm mt-1"
            >
              {event.equity.symbol} - {event.equity.name}
              <ExternalLink className="h-3 w-3" />
            </a>
          )}
        </div>

        {/* Content */}
        <div className="p-6 space-y-4">
          {/* Date and time */}
          <div className="flex items-center gap-6">
            <div className="flex items-center gap-2 text-neutral-700 dark:text-neutral-300">
              <Calendar className="h-5 w-5 text-neutral-500" />
              <span className="font-medium">
                {eventDate.toLocaleDateString('en-US', {
                  weekday: 'long',
                  year: 'numeric',
                  month: 'long',
                  day: 'numeric',
                })}
              </span>
            </div>
            {event.event_time && !event.all_day && (
              <div className="flex items-center gap-2 text-neutral-700 dark:text-neutral-300">
                <Clock className="h-5 w-5 text-neutral-500" />
                <span>{event.event_time}</span>
              </div>
            )}
          </div>

          {/* Importance badge */}
          <div className="flex items-center gap-2">
            <span className="text-sm text-neutral-600 dark:text-neutral-400">Importance:</span>
            <span className={`text-xs px-2 py-1 rounded font-medium ${
              event.importance === 'high'
                ? 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400'
                : event.importance === 'medium'
                ? 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400'
                : 'bg-neutral-100 text-neutral-600 dark:bg-neutral-700 dark:text-neutral-400'
            }`}>
              {event.importance.charAt(0).toUpperCase() + event.importance.slice(1)}
            </span>
            {!event.is_confirmed && (
              <span className="text-xs px-2 py-1 rounded bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-400">
                Tentative
              </span>
            )}
          </div>

          {/* Description */}
          {event.description && (
            <div>
              <h3 className="text-sm font-medium text-neutral-500 dark:text-neutral-400 mb-1">
                Description
              </h3>
              <p className="text-neutral-700 dark:text-neutral-300">
                {event.description}
              </p>
            </div>
          )}

          {/* Economic data values */}
          {(event.actual_value !== null || event.forecast_value !== null || event.previous_value !== null) && (
            <div>
              <h3 className="text-sm font-medium text-neutral-500 dark:text-neutral-400 mb-2">
                Economic Data
              </h3>
              <div className="grid grid-cols-3 gap-4">
                <div className="text-center p-3 bg-neutral-50 dark:bg-neutral-700/50 rounded-lg">
                  <div className="text-xs text-neutral-500 dark:text-neutral-400 uppercase tracking-wide mb-1">
                    Previous
                  </div>
                  <div className="text-lg font-semibold text-neutral-900 dark:text-neutral-100">
                    {formatValue(event.previous_value)}
                  </div>
                </div>
                <div className="text-center p-3 bg-neutral-50 dark:bg-neutral-700/50 rounded-lg">
                  <div className="text-xs text-neutral-500 dark:text-neutral-400 uppercase tracking-wide mb-1">
                    Forecast
                  </div>
                  <div className="text-lg font-semibold text-neutral-900 dark:text-neutral-100">
                    {formatValue(event.forecast_value)}
                  </div>
                </div>
                <div className="text-center p-3 bg-neutral-50 dark:bg-neutral-700/50 rounded-lg">
                  <div className="text-xs text-neutral-500 dark:text-neutral-400 uppercase tracking-wide mb-1">
                    Actual
                  </div>
                  <div className="text-lg font-semibold text-neutral-900 dark:text-neutral-100">
                    {formatValue(event.actual_value)}
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Source info */}
          <div className="pt-4 border-t border-neutral-200 dark:border-neutral-700">
            <div className="flex items-center justify-between text-xs text-neutral-500 dark:text-neutral-400">
              <span>Source: {event.source}</span>
              <span>
                Updated: {new Date(event.updated_at).toLocaleDateString()}
              </span>
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="px-6 py-4 bg-neutral-50 dark:bg-neutral-900/50 flex justify-between">
          <div className="flex gap-2">
            {canDelete && (
              <button
                onClick={() => setShowDeleteConfirm(true)}
                disabled={deleteMutation.isPending}
                className="flex items-center gap-2 px-4 py-2 text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 rounded-lg transition-colors disabled:opacity-50"
              >
                {deleteMutation.isPending ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Trash2 className="h-4 w-4" />
                )}
                Delete
              </button>
            )}
            {canUntrack && (
              <button
                onClick={() => setShowUntrackConfirm(true)}
                disabled={untrackMutation.isPending}
                className="flex items-center gap-2 px-4 py-2 text-orange-600 dark:text-orange-400 hover:bg-orange-50 dark:hover:bg-orange-900/20 rounded-lg transition-colors disabled:opacity-50"
              >
                {untrackMutation.isPending ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <EyeOff className="h-4 w-4" />
                )}
                Untrack {event.equity?.symbol}
              </button>
            )}
          </div>
          <button
            onClick={onClose}
            className="px-4 py-2 border border-neutral-300 dark:border-neutral-600 rounded-lg hover:bg-neutral-100 dark:hover:bg-neutral-700 transition-colors"
          >
            Close
          </button>
        </div>
      </div>

      {/* Delete Confirmation Modal */}
      {showDeleteConfirm && (
        <ConfirmModal
          title="Delete Event"
          message={`Are you sure you want to delete "${event.title}"? This cannot be undone.`}
          confirmLabel="Delete"
          variant="danger"
          isLoading={deleteMutation.isPending}
          onConfirm={handleDelete}
          onCancel={() => setShowDeleteConfirm(false)}
        />
      )}

      {/* Untrack Confirmation Modal */}
      {showUntrackConfirm && event.equity && (
        <ConfirmModal
          title={`Stop Tracking ${event.equity.symbol}`}
          message={`Are you sure you want to stop tracking ${event.equity.symbol}? This will remove all earnings, dividend, and other auto-fetched events for this equity from the calendar.`}
          confirmLabel="Untrack"
          variant="danger"
          isLoading={untrackMutation.isPending}
          onConfirm={handleUntrack}
          onCancel={() => setShowUntrackConfirm(false)}
        />
      )}
    </div>
  );
}
