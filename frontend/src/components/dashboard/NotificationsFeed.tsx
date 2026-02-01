'use client';

import Link from 'next/link';
import { useAlerts, useAllAlertHistory } from '@/lib/hooks/useAlert';
import type { Alert, AlertHistory } from '@/lib/api/types';

interface NotificationItem {
  id: number;
  alertId: number;
  alertName: string;
  symbol: string;
  triggeredAt: Date;
  triggeredValue: number;
  thresholdValue: number;
  conditionType: string;
  notificationSent: boolean;
}

function parseNumber(value: number | string): number {
  return typeof value === 'string' ? parseFloat(value) : value;
}

function formatTimeAgo(date: Date): string {
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);

  if (diffMins < 1) return 'Just now';
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays < 7) return `${diffDays}d ago`;
  return date.toLocaleDateString();
}

function getConditionLabel(conditionType: string): string {
  switch (conditionType) {
    case 'above':
      return 'went above';
    case 'below':
      return 'went below';
    case 'crosses_above':
      return 'crossed above';
    case 'crosses_below':
      return 'crossed below';
    case 'percent_up':
      return 'rose by';
    case 'percent_down':
      return 'fell by';
    default:
      return 'triggered at';
  }
}

function NotificationCard({ notification }: { notification: NotificationItem }) {
  const isPercentCondition =
    notification.conditionType === 'percent_up' ||
    notification.conditionType === 'percent_down';

  return (
    <Link href={`/equity/${notification.symbol}`}>
      <div className="flex items-start gap-3 p-3 rounded-lg border border-neutral-200 dark:border-neutral-700 bg-white dark:bg-neutral-800 hover:border-neutral-300 dark:hover:border-neutral-600 transition-all hover:shadow-sm">
        <div
          className={`flex-shrink-0 w-2 h-2 mt-2 rounded-full ${
            notification.notificationSent
              ? 'bg-emerald-500'
              : 'bg-amber-500'
          }`}
        />
        <div className="flex-1 min-w-0">
          <p className="text-sm text-neutral-900 dark:text-neutral-50">
            <span className="font-semibold">{notification.symbol}</span>{' '}
            {getConditionLabel(notification.conditionType)}{' '}
            <span className="font-medium">
              {isPercentCondition
                ? `${notification.thresholdValue.toFixed(1)}%`
                : `$${notification.thresholdValue.toFixed(2)}`}
            </span>
          </p>
          <p className="text-xs text-neutral-500 dark:text-neutral-400 mt-0.5">
            Current: ${notification.triggeredValue.toFixed(2)} &middot;{' '}
            {formatTimeAgo(notification.triggeredAt)}
          </p>
        </div>
      </div>
    </Link>
  );
}

export function NotificationsFeed() {
  const { data: alerts } = useAlerts();
  const { data: history, isLoading, error } = useAllAlertHistory(20, 0);

  if (isLoading) {
    return (
      <div className="bg-white dark:bg-neutral-800 rounded-xl border border-neutral-200 dark:border-neutral-700 p-5">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-semibold text-neutral-900 dark:text-neutral-50">
            Recent Alerts
          </h2>
        </div>
        <div className="space-y-3">
          {[1, 2, 3, 4, 5].map((i) => (
            <div
              key={i}
              className="h-14 bg-neutral-100 dark:bg-neutral-700 rounded-lg animate-pulse"
            />
          ))}
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-white dark:bg-neutral-800 rounded-xl border border-neutral-200 dark:border-neutral-700 p-5">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-semibold text-neutral-900 dark:text-neutral-50">
            Recent Alerts
          </h2>
        </div>
        <p className="text-neutral-500 dark:text-neutral-400 text-sm text-center py-4">
          Could not load alerts
        </p>
      </div>
    );
  }

  // Build a map of alert id to alert info
  const alertMap = new Map<number, Alert>();
  alerts?.forEach((alert) => alertMap.set(alert.id, alert));

  // Convert history to notification items
  const notifications: NotificationItem[] = (history || [])
    .map((h: AlertHistory): NotificationItem | null => {
      const alert = alertMap.get(h.alert_id);
      if (!alert) return null;

      return {
        id: h.id,
        alertId: h.alert_id,
        alertName: alert.name,
        symbol: alert.target?.symbol || 'Unknown',
        triggeredAt: new Date(h.triggered_at),
        triggeredValue: parseNumber(h.triggered_value),
        thresholdValue: parseNumber(h.threshold_value),
        conditionType: alert.condition_type,
        notificationSent: h.notification_sent,
      };
    })
    .filter((n): n is NotificationItem => n !== null)
    .slice(0, 8);

  if (notifications.length === 0) {
    return (
      <div className="bg-white dark:bg-neutral-800 rounded-xl border border-neutral-200 dark:border-neutral-700 p-5">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-semibold text-neutral-900 dark:text-neutral-50">
            Recent Alerts
          </h2>
          <Link
            href="/alerts"
            className="text-sm text-blue-600 dark:text-blue-400 hover:underline"
          >
            Manage
          </Link>
        </div>
        <div className="text-center py-8">
          <p className="text-neutral-500 dark:text-neutral-400 mb-3">
            No alerts triggered yet
          </p>
          <Link
            href="/alerts"
            className="text-blue-600 dark:text-blue-400 hover:underline text-sm"
          >
            Create an alert
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-white dark:bg-neutral-800 rounded-xl border border-neutral-200 dark:border-neutral-700 p-5">
      <div className="flex items-center justify-between mb-4">
        <h2 className="font-semibold text-neutral-900 dark:text-neutral-50">
          Recent Alerts
        </h2>
        <Link
          href="/alerts"
          className="text-sm text-blue-600 dark:text-blue-400 hover:underline"
        >
          View All
        </Link>
      </div>
      <div className="space-y-2 max-h-[400px] overflow-y-auto">
        {notifications.map((notification) => (
          <NotificationCard key={notification.id} notification={notification} />
        ))}
      </div>
    </div>
  );
}
