'use client';

import { useState } from 'react';
import {
  Bell,
  BellOff,
  Plus,
  Trash2,
  History,
  Settings,
  TrendingUp,
  TrendingDown,
  PlayCircle,
  CheckCircle2,
  XCircle,
  AlertCircle,
  Pencil,
} from 'lucide-react';
import {
  useAlerts,
  useAlertStats,
  useToggleAlert,
  useDeleteAlert,
  useAllAlertHistory,
  useCheckAlert,
} from '@/lib/hooks/useAlert';
import type { Alert, AlertCheckResult, AlertHistory as AlertHistoryType } from '@/lib/api/types';
import { ConfirmModal } from '@/components/ui/ConfirmModal';
import { CreateAlertModal } from '@/components/alert/CreateAlertModal';
import { EditAlertModal } from '@/components/alert/EditAlertModal';
import { AlertHistoryList } from '@/components/alert/AlertHistoryList';
import { NotificationSettings } from '@/components/alert/NotificationSettings';

// Helper to convert string/number to number
function toNumber(value: number | string | null | undefined): number {
  if (value === null || value === undefined) return 0;
  return typeof value === 'string' ? parseFloat(value) : value;
}

// Format price/ratio value
function formatValue(value: number | string | null, isRatio = false): string {
  const num = toNumber(value);
  if (isRatio) {
    if (num >= 100) return num.toFixed(1);
    if (num >= 10) return num.toFixed(2);
    return num.toFixed(4);
  }
  if (num >= 1000) return `$${num.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  if (num >= 1) return `$${num.toFixed(2)}`;
  return `$${num.toFixed(4)}`;
}

// Format time ago
function formatTimeAgo(dateString: string | null): string {
  if (!dateString) return 'Never';
  const date = new Date(dateString);
  const now = new Date();
  const seconds = Math.floor((now.getTime() - date.getTime()) / 1000);

  if (seconds < 60) return 'Just now';
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  if (seconds < 604800) return `${Math.floor(seconds / 86400)}d ago`;
  return date.toLocaleDateString();
}

// Condition type labels
const CONDITION_LABELS: Record<string, string> = {
  above: 'Above',
  below: 'Below',
  crosses_above: 'Crosses Above',
  crosses_below: 'Crosses Below',
  percent_up: '% Up',
  percent_down: '% Down',
};

// Condition type icons
function ConditionIcon({ type }: { type: string }) {
  if (type.includes('up') || type.includes('above')) {
    return <TrendingUp className="h-4 w-4 text-emerald-500" />;
  }
  return <TrendingDown className="h-4 w-4 text-red-500" />;
}

function AlertCard({
  alert,
  onToggle,
  onDelete,
  onCheck,
  onEdit,
  isChecking,
}: {
  alert: Alert;
  onToggle: () => void;
  onDelete: () => void;
  onCheck: () => void;
  onEdit: () => void;
  isChecking: boolean;
}) {
  const isRatio = alert.target?.type === 'ratio';
  const thresholdDisplay = alert.condition_type.includes('percent')
    ? `${toNumber(alert.threshold_value)}%`
    : formatValue(alert.threshold_value, isRatio);

  // Current price from last check
  const currentPrice = alert.last_checked_value !== null && alert.last_checked_value !== undefined
    ? formatValue(alert.last_checked_value, isRatio)
    : null;

  return (
    <div
      className={`bg-white dark:bg-neutral-800 rounded-lg border transition-all ${
        alert.is_active
          ? 'border-neutral-200 dark:border-neutral-700'
          : 'border-neutral-200 dark:border-neutral-700 opacity-60'
      }`}
    >
      <div className="p-4">
        <div className="flex justify-between items-start mb-3">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <h3 className="font-semibold text-neutral-900 dark:text-neutral-50 truncate">
                {alert.name}
              </h3>
              {alert.is_active ? (
                <span className="flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400">
                  <Bell className="h-3 w-3" />
                  Active
                </span>
              ) : (
                <span className="flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-neutral-100 text-neutral-600 dark:bg-neutral-700 dark:text-neutral-400">
                  <BellOff className="h-3 w-3" />
                  Paused
                </span>
              )}
            </div>
            {alert.target && (
              <p className="text-sm text-neutral-500 mt-0.5">
                {alert.target.symbol} - {alert.target.name}
              </p>
            )}
          </div>
          <div className="flex items-center gap-1 ml-2">
            <button
              onClick={onCheck}
              disabled={isChecking}
              className="p-1.5 rounded-lg text-neutral-400 hover:text-blue-500 hover:bg-blue-100 dark:hover:bg-blue-900/30 transition-colors disabled:opacity-50"
              title="Check alert now"
            >
              <PlayCircle className="h-4 w-4" />
            </button>
            <button
              onClick={onEdit}
              className="p-1.5 rounded-lg text-neutral-400 hover:text-blue-500 hover:bg-blue-100 dark:hover:bg-blue-900/30 transition-colors"
              title="Edit alert"
            >
              <Pencil className="h-4 w-4" />
            </button>
            <button
              onClick={onToggle}
              className={`p-1.5 rounded-lg transition-colors ${
                alert.is_active
                  ? 'text-emerald-500 hover:bg-emerald-100 dark:hover:bg-emerald-900/30'
                  : 'text-neutral-400 hover:bg-neutral-100 dark:hover:bg-neutral-700'
              }`}
              title={alert.is_active ? 'Pause alert' : 'Activate alert'}
            >
              {alert.is_active ? <Bell className="h-4 w-4" /> : <BellOff className="h-4 w-4" />}
            </button>
            <button
              onClick={onDelete}
              className="p-1.5 rounded-lg text-neutral-400 hover:text-red-500 hover:bg-red-100 dark:hover:bg-red-900/30 transition-colors"
              title="Delete alert"
            >
              <Trash2 className="h-4 w-4" />
            </button>
          </div>
        </div>

        {/* Condition and current price */}
        <div className="flex items-center gap-3 mb-3">
          <div className="flex items-center gap-2 flex-wrap flex-1 min-w-0">
            <ConditionIcon type={alert.condition_type} />
            <span className="text-sm text-neutral-600 dark:text-neutral-400">
              {CONDITION_LABELS[alert.condition_type] || alert.condition_type}
            </span>
            <span className="text-sm font-semibold text-neutral-900 dark:text-neutral-50">
              {thresholdDisplay}
            </span>
            {alert.comparison_period && (
              <span className="text-xs text-neutral-500">
                ({alert.comparison_period})
              </span>
            )}
          </div>
          {currentPrice && (
            <div className="text-right shrink-0">
              <p className="text-xs text-neutral-500">Current</p>
              <p className="text-sm font-bold text-neutral-900 dark:text-neutral-50">
                {currentPrice}
              </p>
            </div>
          )}
        </div>

        {/* Stats */}
        <div className="flex items-center justify-between text-xs text-neutral-500">
          <span>
            Cooldown: {alert.cooldown_minutes}m
          </span>
          <span>
            Last triggered: {formatTimeAgo(alert.last_triggered_at)}
          </span>
        </div>

        {/* Notes */}
        {alert.notes && (
          <p className="text-xs text-neutral-500 mt-2 line-clamp-2 border-t border-neutral-100 dark:border-neutral-700 pt-2">
            {alert.notes}
          </p>
        )}
      </div>
    </div>
  );
}

function StatsCard({
  label,
  value,
  icon: Icon,
  color,
}: {
  label: string;
  value: number;
  icon: React.ElementType;
  color: string;
}) {
  return (
    <div className="bg-white dark:bg-neutral-800 rounded-lg border border-neutral-200 dark:border-neutral-700 p-4">
      <div className="flex items-center gap-3">
        <div className={`p-2 rounded-lg ${color}`}>
          <Icon className="h-5 w-5" />
        </div>
        <div>
          <p className="text-2xl font-bold text-neutral-900 dark:text-neutral-50">
            {value}
          </p>
          <p className="text-sm text-neutral-500">{label}</p>
        </div>
      </div>
    </div>
  );
}

type TabType = 'alerts' | 'history' | 'settings';

function CheckResultModal({
  result,
  alert,
  onClose,
  onSendNotification,
}: {
  result: AlertCheckResult;
  alert: Alert | undefined;
  onClose: () => void;
  onSendNotification: () => void;
}) {
  const [notificationSent, setNotificationSent] = useState(false);
  const [sendingNotification, setSendingNotification] = useState(false);
  const isRatio = alert?.target?.type === 'ratio';

  const handleSendNotification = async () => {
    setSendingNotification(true);
    try {
      await onSendNotification();
      setNotificationSent(true);
    } finally {
      setSendingNotification(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white dark:bg-neutral-800 rounded-xl w-full max-w-md shadow-xl">
        <div className="p-4 border-b border-neutral-200 dark:border-neutral-700">
          <h2 className="text-lg font-semibold text-neutral-900 dark:text-neutral-50">
            Alert Check Result
          </h2>
        </div>
        <div className="p-4 space-y-4">
          <div className={`p-4 rounded-lg ${
            result.is_triggered
              ? 'bg-emerald-50 dark:bg-emerald-900/20 border border-emerald-200 dark:border-emerald-800'
              : 'bg-neutral-50 dark:bg-neutral-700/50 border border-neutral-200 dark:border-neutral-600'
          }`}>
            <div className="flex items-center gap-2 mb-2">
              {result.is_triggered ? (
                <>
                  <CheckCircle2 className="h-5 w-5 text-emerald-600 dark:text-emerald-400" />
                  <span className="font-semibold text-emerald-700 dark:text-emerald-300">
                    Condition Met
                  </span>
                </>
              ) : (
                <>
                  <XCircle className="h-5 w-5 text-neutral-500" />
                  <span className="font-semibold text-neutral-700 dark:text-neutral-300">
                    Condition Not Met
                  </span>
                </>
              )}
            </div>
            <p className="text-sm text-neutral-600 dark:text-neutral-400">
              {result.condition_met}
            </p>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="bg-neutral-50 dark:bg-neutral-700/50 rounded-lg p-3">
              <p className="text-xs text-neutral-500 mb-1">Current Value</p>
              <p className="text-lg font-bold text-neutral-900 dark:text-neutral-50">
                {isRatio
                  ? toNumber(result.current_value).toFixed(4)
                  : `$${toNumber(result.current_value).toFixed(2)}`
                }
              </p>
            </div>
            <div className="bg-neutral-50 dark:bg-neutral-700/50 rounded-lg p-3">
              <p className="text-xs text-neutral-500 mb-1">Threshold</p>
              <p className="text-lg font-bold text-neutral-900 dark:text-neutral-50">
                {isRatio
                  ? toNumber(result.threshold_value).toFixed(4)
                  : `$${toNumber(result.threshold_value).toFixed(2)}`
                }
              </p>
            </div>
          </div>

          {result.is_triggered && (
            <div className={`text-sm ${
              result.should_notify
                ? 'text-emerald-600 dark:text-emerald-400'
                : 'text-amber-600 dark:text-amber-400'
            }`}>
              {result.should_notify
                ? 'Would send notification (not in cooldown)'
                : 'Would NOT notify (in cooldown period)'
              }
            </div>
          )}

          {/* Send Test Notification button when condition is met */}
          {result.is_triggered && !notificationSent && (
            <button
              onClick={handleSendNotification}
              disabled={sendingNotification}
              className="w-full flex items-center justify-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors disabled:opacity-50"
            >
              {sendingNotification ? (
                <>
                  <Bell className="h-4 w-4 animate-pulse" />
                  Sending...
                </>
              ) : (
                <>
                  <Bell className="h-4 w-4" />
                  Send Test Notification
                </>
              )}
            </button>
          )}

          {notificationSent && (
            <div className="flex items-center gap-2 text-sm text-emerald-600 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-900/20 p-3 rounded-lg">
              <CheckCircle2 className="h-4 w-4" />
              Notification sent to Discord!
            </div>
          )}
        </div>
        <div className="p-4 border-t border-neutral-200 dark:border-neutral-700 flex justify-end">
          <button
            onClick={onClose}
            className="px-4 py-2 bg-neutral-100 dark:bg-neutral-700 text-neutral-700 dark:text-neutral-300 rounded-lg hover:bg-neutral-200 dark:hover:bg-neutral-600 transition-colors"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
}

export default function AlertsPage() {
  const [activeTab, setActiveTab] = useState<TabType>('alerts');
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [editingAlert, setEditingAlert] = useState<Alert | null>(null);
  const [deleteAlertId, setDeleteAlertId] = useState<number | null>(null);
  const [checkingAlertId, setCheckingAlertId] = useState<number | null>(null);
  const [checkResult, setCheckResult] = useState<{ result: AlertCheckResult; alertId: number } | null>(null);

  const { data: alerts, isLoading: alertsLoading } = useAlerts();
  const { data: stats } = useAlertStats();
  const { data: history } = useAllAlertHistory();
  const toggleAlert = useToggleAlert();
  const deleteAlert = useDeleteAlert();
  const checkAlert = useCheckAlert();

  const handleCheck = async (alertId: number) => {
    setCheckingAlertId(alertId);
    try {
      const result = await checkAlert.mutateAsync({ alertId, notify: false });
      setCheckResult({ result, alertId });
    } finally {
      setCheckingAlertId(null);
    }
  };

  const handleSendTestNotification = async (alertId: number) => {
    await checkAlert.mutateAsync({ alertId, notify: true });
  };

  const activeAlerts = alerts?.filter((a) => a.is_active) || [];
  const pausedAlerts = alerts?.filter((a) => !a.is_active) || [];

  if (alertsLoading) {
    return (
      <div className="min-h-[calc(100vh-4rem)] bg-neutral-50 dark:bg-neutral-900">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 py-8">
          <div className="animate-pulse space-y-6">
            <div className="h-8 w-32 bg-neutral-200 dark:bg-neutral-700 rounded"></div>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
              {[...Array(4)].map((_, i) => (
                <div key={i} className="h-24 bg-neutral-200 dark:bg-neutral-700 rounded-lg"></div>
              ))}
            </div>
            <div className="space-y-4">
              {[...Array(3)].map((_, i) => (
                <div key={i} className="h-32 bg-neutral-200 dark:bg-neutral-700 rounded-lg"></div>
              ))}
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-[calc(100vh-4rem)] bg-neutral-50 dark:bg-neutral-900">
      <div className="max-w-6xl mx-auto px-4 sm:px-6 py-8">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 mb-6">
          <div>
            <h1 className="text-2xl font-bold text-neutral-900 dark:text-neutral-50">
              Alerts
            </h1>
            <p className="text-sm text-neutral-500">
              Monitor prices and ratios with real-time notifications
            </p>
          </div>
          <button
            onClick={() => setShowCreateModal(true)}
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
          >
            <Plus className="h-4 w-4" />
            New Alert
          </button>
        </div>

        {/* Stats */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
          <StatsCard
            label="Total Alerts"
            value={stats?.total_alerts || 0}
            icon={Bell}
            color="bg-blue-100 text-blue-600 dark:bg-blue-900/30 dark:text-blue-400"
          />
          <StatsCard
            label="Active"
            value={stats?.active_alerts || 0}
            icon={CheckCircle2}
            color="bg-emerald-100 text-emerald-600 dark:bg-emerald-900/30 dark:text-emerald-400"
          />
          <StatsCard
            label="Triggered Today"
            value={stats?.triggered_today || 0}
            icon={AlertCircle}
            color="bg-amber-100 text-amber-600 dark:bg-amber-900/30 dark:text-amber-400"
          />
          <StatsCard
            label="Triggered This Week"
            value={stats?.triggered_this_week || 0}
            icon={History}
            color="bg-purple-100 text-purple-600 dark:bg-purple-900/30 dark:text-purple-400"
          />
        </div>

        {/* Tabs */}
        <div className="flex gap-1 mb-6 bg-neutral-100 dark:bg-neutral-800 p-1 rounded-lg w-fit">
          <button
            onClick={() => setActiveTab('alerts')}
            className={`flex items-center gap-2 px-4 py-2 rounded-md text-sm font-medium transition-colors ${
              activeTab === 'alerts'
                ? 'bg-white dark:bg-neutral-700 text-neutral-900 dark:text-neutral-50 shadow-sm'
                : 'text-neutral-600 dark:text-neutral-400 hover:text-neutral-900 dark:hover:text-neutral-50'
            }`}
          >
            <Bell className="h-4 w-4" />
            Alerts
          </button>
          <button
            onClick={() => setActiveTab('history')}
            className={`flex items-center gap-2 px-4 py-2 rounded-md text-sm font-medium transition-colors ${
              activeTab === 'history'
                ? 'bg-white dark:bg-neutral-700 text-neutral-900 dark:text-neutral-50 shadow-sm'
                : 'text-neutral-600 dark:text-neutral-400 hover:text-neutral-900 dark:hover:text-neutral-50'
            }`}
          >
            <History className="h-4 w-4" />
            History
          </button>
          <button
            onClick={() => setActiveTab('settings')}
            className={`flex items-center gap-2 px-4 py-2 rounded-md text-sm font-medium transition-colors ${
              activeTab === 'settings'
                ? 'bg-white dark:bg-neutral-700 text-neutral-900 dark:text-neutral-50 shadow-sm'
                : 'text-neutral-600 dark:text-neutral-400 hover:text-neutral-900 dark:hover:text-neutral-50'
            }`}
          >
            <Settings className="h-4 w-4" />
            Settings
          </button>
        </div>

        {/* Tab Content */}
        {activeTab === 'alerts' && (
          <div className="space-y-6">
            {/* Active Alerts */}
            {activeAlerts.length > 0 && (
              <div>
                <h2 className="text-sm font-medium text-neutral-500 mb-3 flex items-center gap-2">
                  <Bell className="h-4 w-4 text-emerald-500" />
                  Active Alerts ({activeAlerts.length})
                </h2>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {activeAlerts.map((alert) => (
                    <AlertCard
                      key={alert.id}
                      alert={alert}
                      onToggle={() => toggleAlert.mutate(alert.id)}
                      onDelete={() => setDeleteAlertId(alert.id)}
                      onCheck={() => handleCheck(alert.id)}
                      onEdit={() => setEditingAlert(alert)}
                      isChecking={checkingAlertId === alert.id}
                    />
                  ))}
                </div>
              </div>
            )}

            {/* Paused Alerts */}
            {pausedAlerts.length > 0 && (
              <div>
                <h2 className="text-sm font-medium text-neutral-500 mb-3 flex items-center gap-2">
                  <BellOff className="h-4 w-4" />
                  Paused Alerts ({pausedAlerts.length})
                </h2>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {pausedAlerts.map((alert) => (
                    <AlertCard
                      key={alert.id}
                      alert={alert}
                      onToggle={() => toggleAlert.mutate(alert.id)}
                      onDelete={() => setDeleteAlertId(alert.id)}
                      onCheck={() => handleCheck(alert.id)}
                      onEdit={() => setEditingAlert(alert)}
                      isChecking={checkingAlertId === alert.id}
                    />
                  ))}
                </div>
              </div>
            )}

            {/* Empty State */}
            {(!alerts || alerts.length === 0) && (
              <div className="text-center py-12 bg-white dark:bg-neutral-800 rounded-lg border border-neutral-200 dark:border-neutral-700">
                <Bell className="h-12 w-12 text-neutral-300 dark:text-neutral-600 mx-auto mb-4" />
                <h3 className="text-lg font-medium text-neutral-900 dark:text-neutral-50 mb-2">
                  No alerts yet
                </h3>
                <p className="text-neutral-500 mb-4">
                  Create your first alert to get notified when prices move
                </p>
                <button
                  onClick={() => setShowCreateModal(true)}
                  className="inline-flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
                >
                  <Plus className="h-4 w-4" />
                  Create Alert
                </button>
              </div>
            )}
          </div>
        )}

        {activeTab === 'history' && (
          <AlertHistoryList history={history || []} />
        )}

        {activeTab === 'settings' && (
          <NotificationSettings />
        )}
      </div>

      {/* Create Modal */}
      <CreateAlertModal
        isOpen={showCreateModal}
        onClose={() => setShowCreateModal(false)}
      />

      {/* Edit Modal */}
      {editingAlert && (
        <EditAlertModal
          alert={editingAlert}
          onClose={() => setEditingAlert(null)}
        />
      )}

      {/* Delete Confirmation */}
      {deleteAlertId !== null && (
        <ConfirmModal
          title="Delete Alert"
          message="Are you sure you want to delete this alert? This action cannot be undone."
          confirmLabel="Delete"
          onConfirm={() => {
            if (deleteAlertId) {
              deleteAlert.mutate(deleteAlertId);
            }
            setDeleteAlertId(null);
          }}
          onCancel={() => setDeleteAlertId(null)}
          variant="danger"
        />
      )}

      {/* Check Result Modal */}
      {checkResult && (
        <CheckResultModal
          result={checkResult.result}
          alert={alerts?.find((a) => a.id === checkResult.alertId)}
          onClose={() => setCheckResult(null)}
          onSendNotification={() => handleSendTestNotification(checkResult.alertId)}
        />
      )}
    </div>
  );
}
