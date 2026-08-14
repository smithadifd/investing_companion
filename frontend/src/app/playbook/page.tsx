'use client';

import { useState } from 'react';
import {
  Archive,
  Bell,
  BellOff,
  CheckCircle2,
  Crosshair,
  EyeOff,
  Pencil,
  Plus,
  RotateCcw,
  Target,
  Trash2,
  Zap,
} from 'lucide-react';
import {
  useTriggers,
  useDeleteTrigger,
  useRearmTrigger,
} from '@/lib/hooks/useTrigger';
import type { Trigger, TriggerSignal } from '@/lib/api/types';
import { ConfirmModal } from '@/components/ui/ConfirmModal';
import { TriggerModal } from '@/components/trigger/TriggerModal';
import { ExecuteTriggerModal } from '@/components/trigger/ExecuteTriggerModal';

// Helper to convert string/number to number
function toNumber(value: number | string | null | undefined): number {
  if (value === null || value === undefined) return 0;
  return typeof value === 'string' ? parseFloat(value) : value;
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

// Tier accent colors (left border + chip)
const TIER_STYLES: Record<string, { border: string; chip: string }> = {
  yellow: {
    border: 'border-l-yellow-400',
    chip: 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400',
  },
  orange: {
    border: 'border-l-orange-400',
    chip: 'bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-400',
  },
  red: {
    border: 'border-l-red-500',
    chip: 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400',
  },
};

const SIGNAL_CONFIG: Record<
  TriggerSignal,
  { label: string; className: string; icon: React.ElementType; title?: string }
> = {
  hit: {
    label: 'Hit',
    className:
      'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400 font-semibold',
    icon: Zap,
  },
  approaching: {
    label: 'Approaching',
    className: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400',
    icon: Crosshair,
  },
  armed: {
    label: 'Armed',
    className:
      'bg-neutral-100 text-neutral-600 dark:bg-neutral-700 dark:text-neutral-300',
    icon: Target,
  },
  unwatched: {
    label: 'Unwatched',
    className:
      'bg-transparent text-neutral-400 dark:text-neutral-500 border border-dashed border-neutral-300 dark:border-neutral-600',
    icon: EyeOff,
    title: 'No alerts are linked to this trigger',
  },
  // Shares the dashed outline with Unwatched (both mean "no live coverage")
  // but in orange, because this one is a ladder that was built and then went
  // dark — that is a problem to fix, not a trigger never wired up.
  disarmed: {
    label: 'Disarmed',
    className:
      'bg-transparent text-orange-600 dark:text-orange-400 border border-dashed border-orange-400 dark:border-orange-500/60',
    icon: BellOff,
    title: 'Every alert linked to this trigger is deactivated — nothing is watching it',
  },
};

function SignalChip({ signal }: { signal: TriggerSignal | null }) {
  if (!signal) return null;
  const config = SIGNAL_CONFIG[signal];
  const Icon = config.icon;
  return (
    <span
      title={config.title}
      className={`flex items-center gap-1 text-xs px-2 py-0.5 rounded-full ${config.className}`}
    >
      <Icon className="h-3 w-3" />
      {config.label}
    </span>
  );
}

function LinkedAlertRow({ alert }: { alert: Trigger['alerts'][number] }) {
  const distance =
    alert.distance_percent !== null && alert.distance_percent !== undefined
      ? `${toNumber(alert.distance_percent).toFixed(1)}% away`
      : null;

  return (
    <li className="flex items-center gap-2 text-xs text-neutral-600 dark:text-neutral-400">
      {alert.is_active ? (
        <Bell className="h-3 w-3 shrink-0 text-emerald-500" />
      ) : (
        <BellOff className="h-3 w-3 shrink-0 text-neutral-400" />
      )}
      <span className="truncate">{alert.name}</span>
      {distance && (
        <span className="shrink-0 font-medium text-neutral-900 dark:text-neutral-50">
          {distance}
        </span>
      )}
      {alert.last_triggered_at && (
        <span className="shrink-0 text-neutral-400">
          triggered {formatTimeAgo(alert.last_triggered_at)}
        </span>
      )}
    </li>
  );
}

function TriggerCard({
  trigger,
  onExecute,
  onRearm,
  onEdit,
  onDelete,
}: {
  trigger: Trigger;
  onExecute: () => void;
  onRearm: () => void;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const isExecuted = trigger.status === 'executed';
  const isRetired = trigger.status === 'retired';
  const tierStyle = trigger.tier ? TIER_STYLES[trigger.tier] : undefined;

  return (
    <div
      className={`bg-white dark:bg-neutral-800 rounded-lg border border-neutral-200 dark:border-neutral-700 border-l-4 ${
        tierStyle ? tierStyle.border : 'border-l-neutral-300 dark:border-l-neutral-600'
      } ${isExecuted ? 'opacity-60' : ''} ${isRetired ? 'opacity-40' : ''}`}
    >
      <div className="p-4">
        <div className="flex justify-between items-start mb-3">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <h3 className="font-semibold text-neutral-900 dark:text-neutral-50 truncate">
                {trigger.name}
              </h3>
              {trigger.tier && tierStyle && (
                <span
                  className={`text-xs px-2 py-0.5 rounded-full capitalize ${tierStyle.chip}`}
                >
                  {trigger.tier}
                </span>
              )}
              {isRetired ? (
                <span className="flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-neutral-100 text-neutral-500 dark:bg-neutral-700 dark:text-neutral-400">
                  <Archive className="h-3 w-3" />
                  Retired
                </span>
              ) : isExecuted ? (
                <span className="flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400">
                  <CheckCircle2 className="h-3 w-3" />
                  Executed
                </span>
              ) : (
                <SignalChip signal={trigger.signal} />
              )}
            </div>
          </div>
          <div className="flex items-center gap-1 ml-2">
            {trigger.status === 'active' && (
              <button
                onClick={onExecute}
                className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                  trigger.signal === 'hit'
                    ? 'bg-red-600 text-white hover:bg-red-700'
                    : 'text-neutral-500 hover:text-emerald-600 hover:bg-emerald-100 dark:hover:bg-emerald-900/30'
                }`}
                title="Mark this trigger as executed"
              >
                <CheckCircle2 className="h-4 w-4" />
                Execute
              </button>
            )}
            {(isExecuted || isRetired) && (
              <button
                onClick={onRearm}
                className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium text-neutral-500 hover:text-blue-600 hover:bg-blue-100 dark:hover:bg-blue-900/30 transition-colors"
                title="Re-arm this trigger"
              >
                <RotateCcw className="h-4 w-4" />
                Re-arm
              </button>
            )}
            <button
              onClick={onEdit}
              className="p-1.5 rounded-lg text-neutral-400 hover:text-blue-500 hover:bg-blue-100 dark:hover:bg-blue-900/30 transition-colors"
              title="Edit trigger"
            >
              <Pencil className="h-4 w-4" />
            </button>
            <button
              onClick={onDelete}
              className="p-1.5 rounded-lg text-neutral-400 hover:text-red-500 hover:bg-red-100 dark:hover:bg-red-900/30 transition-colors"
              title="Delete trigger"
            >
              <Trash2 className="h-4 w-4" />
            </button>
          </div>
        </div>

        {/* IF / THEN */}
        <div className="space-y-1.5 mb-3">
          <div className="flex gap-2 text-sm">
            <span className="shrink-0 w-10 text-xs font-semibold uppercase tracking-wide text-neutral-400 mt-0.5">
              If
            </span>
            <span className="text-neutral-600 dark:text-neutral-400">{trigger.rule}</span>
          </div>
          <div className="flex gap-2 text-sm">
            <span className="shrink-0 w-10 text-xs font-semibold uppercase tracking-wide text-neutral-400 mt-0.5">
              Then
            </span>
            <span className="text-neutral-900 dark:text-neutral-50 font-medium">
              {trigger.action}
            </span>
          </div>
        </div>

        {/* Execution note + date */}
        {isExecuted && trigger.executed_at && (
          <div className="mb-3 p-3 rounded-lg bg-emerald-50 dark:bg-emerald-900/20 border border-emerald-200 dark:border-emerald-800">
            <p className="text-xs font-medium text-emerald-700 dark:text-emerald-400 mb-1">
              Executed {formatTimeAgo(trigger.executed_at)} (
              {new Date(trigger.executed_at).toLocaleDateString()})
            </p>
            {trigger.execution_note ? (
              <p className="text-sm text-neutral-700 dark:text-neutral-300 whitespace-pre-wrap">
                {trigger.execution_note}
              </p>
            ) : (
              <p className="text-sm text-neutral-400 italic">No note recorded</p>
            )}
          </div>
        )}

        {/* Linked alerts */}
        {trigger.alerts.length > 0 ? (
          <ul className="space-y-1 border-t border-neutral-100 dark:border-neutral-700 pt-2">
            {trigger.alerts.map((alert) => (
              <LinkedAlertRow key={alert.id} alert={alert} />
            ))}
          </ul>
        ) : (
          !isExecuted &&
          !isRetired && (
            <p className="text-xs text-neutral-400 border-t border-neutral-100 dark:border-neutral-700 pt-2">
              No linked alerts — this trigger has no live signal
            </p>
          )
        )}
      </div>
    </div>
  );
}

export default function PlaybookPage() {
  const [showRetired, setShowRetired] = useState(false);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [editingTrigger, setEditingTrigger] = useState<Trigger | null>(null);
  const [executingTrigger, setExecutingTrigger] = useState<Trigger | null>(null);
  const [deleteTriggerId, setDeleteTriggerId] = useState<number | null>(null);

  const { data: triggers, isLoading } = useTriggers(showRetired);
  const deleteTrigger = useDeleteTrigger();
  const rearmTrigger = useRearmTrigger();

  // Backend returns triggers ordered by display_order, id
  const visibleTriggers = (triggers || []).filter(
    (t) => showRetired || t.status !== 'retired'
  );

  const hitCount = visibleTriggers.filter(
    (t) => t.status === 'active' && t.signal === 'hit'
  ).length;
  const approachingCount = visibleTriggers.filter(
    (t) => t.status === 'active' && t.signal === 'approaching'
  ).length;

  if (isLoading) {
    return (
      <div className="min-h-[calc(100vh-4rem)] bg-neutral-50 dark:bg-neutral-900">
        <div className="max-w-4xl mx-auto px-4 sm:px-6 py-8">
          <div className="animate-pulse space-y-6">
            <div className="h-8 w-32 bg-neutral-200 dark:bg-neutral-700 rounded"></div>
            <div className="space-y-4">
              {[...Array(4)].map((_, i) => (
                <div key={i} className="h-36 bg-neutral-200 dark:bg-neutral-700 rounded-lg"></div>
              ))}
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-[calc(100vh-4rem)] bg-neutral-50 dark:bg-neutral-900">
      <div className="max-w-4xl mx-auto px-4 sm:px-6 py-8">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 mb-6">
          <div>
            <h1 className="text-2xl font-bold text-neutral-900 dark:text-neutral-50">
              Playbook
            </h1>
            <p className="text-sm text-neutral-500">
              Standing orders decided in advance — execute calmly when conditions hit
            </p>
            {(hitCount > 0 || approachingCount > 0) && (
              <p className="text-sm mt-1">
                {hitCount > 0 && (
                  <span className="font-semibold text-red-600 dark:text-red-400">
                    {hitCount} hit
                  </span>
                )}
                {hitCount > 0 && approachingCount > 0 && (
                  <span className="text-neutral-400"> · </span>
                )}
                {approachingCount > 0 && (
                  <span className="font-medium text-amber-600 dark:text-amber-400">
                    {approachingCount} approaching
                  </span>
                )}
              </p>
            )}
          </div>
          <button
            onClick={() => setShowCreateModal(true)}
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
          >
            <Plus className="h-4 w-4" />
            New Trigger
          </button>
        </div>

        {/* Retired toggle */}
        <div className="flex justify-end mb-4">
          <label className="flex items-center gap-2 text-sm text-neutral-600 dark:text-neutral-400 cursor-pointer">
            <input
              type="checkbox"
              checked={showRetired}
              onChange={(e) => setShowRetired(e.target.checked)}
              className="h-4 w-4 rounded border-neutral-300 text-blue-600 focus:ring-blue-500"
            />
            Show retired
          </label>
        </div>

        {/* Trigger list */}
        {visibleTriggers.length > 0 ? (
          <div className="space-y-4">
            {visibleTriggers.map((trigger) => (
              <TriggerCard
                key={trigger.id}
                trigger={trigger}
                onExecute={() => setExecutingTrigger(trigger)}
                onRearm={() => rearmTrigger.mutate(trigger.id)}
                onEdit={() => setEditingTrigger(trigger)}
                onDelete={() => setDeleteTriggerId(trigger.id)}
              />
            ))}
          </div>
        ) : (
          <div className="text-center py-12 bg-white dark:bg-neutral-800 rounded-lg border border-neutral-200 dark:border-neutral-700">
            <Target className="h-12 w-12 text-neutral-300 dark:text-neutral-600 mx-auto mb-4" />
            <h3 className="text-lg font-medium text-neutral-900 dark:text-neutral-50 mb-2">
              No triggers yet
            </h3>
            <p className="text-neutral-500 mb-4">
              Write down your if-this-then-that standing orders before the market tests you
            </p>
            <button
              onClick={() => setShowCreateModal(true)}
              className="inline-flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
            >
              <Plus className="h-4 w-4" />
              Create Trigger
            </button>
          </div>
        )}
      </div>

      {/* Create Modal */}
      <TriggerModal
        isOpen={showCreateModal}
        onClose={() => setShowCreateModal(false)}
      />

      {/* Edit Modal */}
      {editingTrigger && (
        <TriggerModal
          key={editingTrigger.id}
          isOpen
          trigger={editingTrigger}
          onClose={() => setEditingTrigger(null)}
        />
      )}

      {/* Execute Modal */}
      {executingTrigger && (
        <ExecuteTriggerModal
          trigger={executingTrigger}
          onClose={() => setExecutingTrigger(null)}
        />
      )}

      {/* Delete Confirmation */}
      {deleteTriggerId !== null && (
        <ConfirmModal
          title="Delete Trigger"
          message="Are you sure you want to delete this trigger? Its execution history goes with it. This action cannot be undone."
          confirmLabel="Delete"
          onConfirm={() => {
            if (deleteTriggerId) {
              deleteTrigger.mutate(deleteTriggerId);
            }
            setDeleteTriggerId(null);
          }}
          onCancel={() => setDeleteTriggerId(null)}
          variant="danger"
        />
      )}
    </div>
  );
}
