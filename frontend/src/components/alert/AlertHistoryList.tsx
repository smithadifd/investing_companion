'use client';

import { CheckCircle2, XCircle, Clock, TrendingUp, TrendingDown } from 'lucide-react';
import type { AlertHistory } from '@/lib/api/types';

// Helper to convert string/number to number
function toNumber(value: number | string | null | undefined): number {
  if (value === null || value === undefined) return 0;
  return typeof value === 'string' ? parseFloat(value) : value;
}

// Format value
function formatValue(value: number | string | null): string {
  const num = toNumber(value);
  if (num >= 1000) return num.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  if (num >= 1) return num.toFixed(2);
  return num.toFixed(4);
}

// Format date/time
function formatDateTime(dateString: string): string {
  const date = new Date(dateString);
  const now = new Date();
  const isToday = date.toDateString() === now.toDateString();

  if (isToday) {
    return `Today at ${date.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })}`;
  }

  const yesterday = new Date(now);
  yesterday.setDate(yesterday.getDate() - 1);
  const isYesterday = date.toDateString() === yesterday.toDateString();

  if (isYesterday) {
    return `Yesterday at ${date.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })}`;
  }

  return date.toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

interface AlertHistoryListProps {
  history: AlertHistory[];
}

export function AlertHistoryList({ history }: AlertHistoryListProps) {
  if (history.length === 0) {
    return (
      <div className="text-center py-12 bg-white dark:bg-neutral-800 rounded-lg border border-neutral-200 dark:border-neutral-700">
        <Clock className="h-12 w-12 text-neutral-300 dark:text-neutral-600 mx-auto mb-4" />
        <h3 className="text-lg font-medium text-neutral-900 dark:text-neutral-50 mb-2">
          No history yet
        </h3>
        <p className="text-neutral-500">
          Alert triggers will appear here
        </p>
      </div>
    );
  }

  return (
    <div className="bg-white dark:bg-neutral-800 rounded-lg border border-neutral-200 dark:border-neutral-700 overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead>
            <tr className="border-b border-neutral-200 dark:border-neutral-700 bg-neutral-50 dark:bg-neutral-700/50">
              <th className="px-4 py-3 text-left text-xs font-medium text-neutral-500 uppercase tracking-wider">
                Time
              </th>
              <th className="px-4 py-3 text-left text-xs font-medium text-neutral-500 uppercase tracking-wider">
                Alert ID
              </th>
              <th className="px-4 py-3 text-right text-xs font-medium text-neutral-500 uppercase tracking-wider">
                Triggered Value
              </th>
              <th className="px-4 py-3 text-right text-xs font-medium text-neutral-500 uppercase tracking-wider">
                Threshold
              </th>
              <th className="px-4 py-3 text-center text-xs font-medium text-neutral-500 uppercase tracking-wider">
                Direction
              </th>
              <th className="px-4 py-3 text-center text-xs font-medium text-neutral-500 uppercase tracking-wider">
                Notification
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-neutral-200 dark:divide-neutral-700">
            {history.map((item) => {
              const triggeredValue = toNumber(item.triggered_value);
              const thresholdValue = toNumber(item.threshold_value);
              const isAbove = triggeredValue > thresholdValue;

              return (
                <tr
                  key={item.id}
                  className="hover:bg-neutral-50 dark:hover:bg-neutral-700/30 transition-colors"
                >
                  <td className="px-4 py-3 text-sm text-neutral-900 dark:text-neutral-50">
                    {formatDateTime(item.triggered_at)}
                  </td>
                  <td className="px-4 py-3 text-sm text-neutral-500">
                    #{item.alert_id}
                  </td>
                  <td className="px-4 py-3 text-sm text-right font-mono text-neutral-900 dark:text-neutral-50">
                    {formatValue(item.triggered_value)}
                  </td>
                  <td className="px-4 py-3 text-sm text-right font-mono text-neutral-500">
                    {formatValue(item.threshold_value)}
                  </td>
                  <td className="px-4 py-3 text-center">
                    {isAbove ? (
                      <span className="inline-flex items-center gap-1 text-emerald-600 dark:text-emerald-400">
                        <TrendingUp className="h-4 w-4" />
                        <span className="text-xs">Above</span>
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 text-red-600 dark:text-red-400">
                        <TrendingDown className="h-4 w-4" />
                        <span className="text-xs">Below</span>
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-center">
                    {item.notification_sent ? (
                      <span className="inline-flex items-center gap-1 text-emerald-600 dark:text-emerald-400">
                        <CheckCircle2 className="h-4 w-4" />
                        <span className="text-xs">{item.notification_channel || 'Sent'}</span>
                      </span>
                    ) : (
                      <span
                        className="inline-flex items-center gap-1 text-red-600 dark:text-red-400"
                        title={item.notification_error || 'Failed to send'}
                      >
                        <XCircle className="h-4 w-4" />
                        <span className="text-xs">Failed</span>
                      </span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
