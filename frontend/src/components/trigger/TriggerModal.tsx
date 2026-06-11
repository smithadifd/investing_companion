'use client';

import { useState } from 'react';
import { Loader2, Search } from 'lucide-react';
import { useCreateTrigger, useUpdateTrigger } from '@/lib/hooks/useTrigger';
import { useAlerts } from '@/lib/hooks/useAlert';
import { Modal } from '@/components/ui/Modal';
import type { Trigger, TriggerCreate, TriggerUpdate } from '@/lib/api/types';

interface TriggerModalProps {
  isOpen: boolean;
  onClose: () => void;
  /** When provided, the modal edits this trigger instead of creating a new one */
  trigger?: Trigger | null;
}

const TIER_OPTIONS: { value: string; label: string }[] = [
  { value: '', label: 'No tier' },
  { value: 'yellow', label: 'Yellow' },
  { value: 'orange', label: 'Orange' },
  { value: 'red', label: 'Red' },
];

export function TriggerModal({ isOpen, onClose, trigger }: TriggerModalProps) {
  const isEdit = !!trigger;

  const [name, setName] = useState(trigger?.name || '');
  const [rule, setRule] = useState(trigger?.rule || '');
  const [action, setAction] = useState(trigger?.action || '');
  const [tier, setTier] = useState(trigger?.tier || '');
  const [displayOrder, setDisplayOrder] = useState(
    trigger ? trigger.display_order.toString() : '0'
  );
  const [selectedAlertIds, setSelectedAlertIds] = useState<number[]>(
    trigger ? trigger.alerts.map((a) => a.id) : []
  );
  const [alertFilter, setAlertFilter] = useState('');

  const { data: alerts } = useAlerts();
  const createTrigger = useCreateTrigger();
  const updateTrigger = useUpdateTrigger();

  const isPending = createTrigger.isPending || updateTrigger.isPending;

  const filteredAlerts = alerts?.filter((a) =>
    a.name.toLowerCase().includes(alertFilter.toLowerCase())
  );

  const toggleAlert = (alertId: number) => {
    setSelectedAlertIds((prev) =>
      prev.includes(alertId)
        ? prev.filter((id) => id !== alertId)
        : [...prev, alertId]
    );
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!name || !rule || !action) return;

    try {
      if (isEdit && trigger) {
        const data: TriggerUpdate = {
          name,
          rule,
          action,
          tier: tier || undefined,
          display_order: parseInt(displayOrder) || 0,
          alert_ids: selectedAlertIds,
        };
        await updateTrigger.mutateAsync({ id: trigger.id, data });
      } else {
        const data: TriggerCreate = {
          name,
          rule,
          action,
          tier: tier || undefined,
          display_order: parseInt(displayOrder) || 0,
          alert_ids: selectedAlertIds,
        };
        await createTrigger.mutateAsync(data);
      }
      handleClose();
    } catch (error) {
      console.error('Failed to save trigger:', error);
    }
  };

  const handleClose = () => {
    setName(trigger?.name || '');
    setRule(trigger?.rule || '');
    setAction(trigger?.action || '');
    setTier(trigger?.tier || '');
    setDisplayOrder(trigger ? trigger.display_order.toString() : '0');
    setSelectedAlertIds(trigger ? trigger.alerts.map((a) => a.id) : []);
    setAlertFilter('');
    onClose();
  };

  if (!isOpen) return null;

  return (
    <Modal onClose={handleClose} title={isEdit ? 'Edit Trigger' : 'New Trigger'} maxWidth="lg">
      <form onSubmit={handleSubmit} className="p-4 space-y-4">
        {/* Name */}
        <div>
          <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
            Name
          </label>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            maxLength={100}
            placeholder="e.g., SPY Crisis Tier 2"
            className="w-full px-3 py-2 border border-neutral-300 dark:border-neutral-600 rounded-lg bg-white dark:bg-neutral-700 text-neutral-900 dark:text-neutral-50 focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            required
          />
        </div>

        {/* Rule (IF) */}
        <div>
          <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
            If (condition)
          </label>
          <textarea
            value={rule}
            onChange={(e) => setRule(e.target.value)}
            placeholder="e.g., SPY closes 10% below its 1y high"
            rows={2}
            className="w-full px-3 py-2 border border-neutral-300 dark:border-neutral-600 rounded-lg bg-white dark:bg-neutral-700 text-neutral-900 dark:text-neutral-50 focus:ring-2 focus:ring-blue-500 focus:border-transparent resize-none"
            required
          />
        </div>

        {/* Action (THEN) */}
        <div>
          <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
            Then (pre-committed action)
          </label>
          <textarea
            value={action}
            onChange={(e) => setAction(e.target.value)}
            placeholder="e.g., Deploy first tranche: buy 10 shares SPY, no second-guessing"
            rows={2}
            className="w-full px-3 py-2 border border-neutral-300 dark:border-neutral-600 rounded-lg bg-white dark:bg-neutral-700 text-neutral-900 dark:text-neutral-50 focus:ring-2 focus:ring-blue-500 focus:border-transparent resize-none"
            required
          />
        </div>

        {/* Tier + Display Order */}
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
              Tier
            </label>
            <select
              value={tier}
              onChange={(e) => setTier(e.target.value)}
              className="w-full px-3 py-2 border border-neutral-300 dark:border-neutral-600 rounded-lg bg-white dark:bg-neutral-700 text-neutral-900 dark:text-neutral-50 focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            >
              {TIER_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
            <p className="text-xs text-neutral-500 mt-1">
              Severity color for the playbook
            </p>
          </div>
          <div>
            <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
              Display Order
            </label>
            <input
              type="number"
              value={displayOrder}
              onChange={(e) => setDisplayOrder(e.target.value)}
              className="w-full px-3 py-2 border border-neutral-300 dark:border-neutral-600 rounded-lg bg-white dark:bg-neutral-700 text-neutral-900 dark:text-neutral-50 focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            />
            <p className="text-xs text-neutral-500 mt-1">
              Lower numbers appear first
            </p>
          </div>
        </div>

        {/* Linked Alerts */}
        <div>
          <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
            Linked Alerts
            {selectedAlertIds.length > 0 && (
              <span className="ml-2 text-xs font-normal text-neutral-500">
                ({selectedAlertIds.length} selected)
              </span>
            )}
          </label>
          <p className="text-xs text-neutral-500 mb-2">
            Linked alerts drive the live signal (armed / approaching / hit)
          </p>
          <div className="relative mb-2">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-neutral-400" />
            <input
              type="text"
              value={alertFilter}
              onChange={(e) => setAlertFilter(e.target.value)}
              placeholder="Filter alerts..."
              className="w-full pl-8 pr-3 py-1.5 text-sm border border-neutral-300 dark:border-neutral-600 rounded-lg bg-white dark:bg-neutral-700 text-neutral-900 dark:text-neutral-50 focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            />
          </div>
          <div className="max-h-48 overflow-y-auto border border-neutral-200 dark:border-neutral-700 rounded-lg divide-y divide-neutral-100 dark:divide-neutral-700">
            {filteredAlerts && filteredAlerts.length > 0 ? (
              filteredAlerts.map((alert) => (
                <label
                  key={alert.id}
                  className="flex items-center gap-3 px-3 py-2 cursor-pointer hover:bg-neutral-50 dark:hover:bg-neutral-700/50 transition-colors"
                >
                  <input
                    type="checkbox"
                    checked={selectedAlertIds.includes(alert.id)}
                    onChange={() => toggleAlert(alert.id)}
                    className="h-4 w-4 rounded border-neutral-300 text-blue-600 focus:ring-blue-500"
                  />
                  <span className="flex-1 text-sm text-neutral-900 dark:text-neutral-50 truncate">
                    {alert.name}
                  </span>
                  {!alert.is_active && (
                    <span className="text-xs px-1.5 py-0.5 rounded-full bg-neutral-100 text-neutral-500 dark:bg-neutral-700 dark:text-neutral-400">
                      Paused
                    </span>
                  )}
                </label>
              ))
            ) : (
              <p className="px-3 py-4 text-sm text-neutral-500 text-center">
                {alertFilter ? 'No alerts match your filter' : 'No alerts available'}
              </p>
            )}
          </div>
        </div>

        {/* Submit */}
        <div className="flex justify-end gap-3 pt-2">
          <button
            type="button"
            onClick={handleClose}
            className="px-4 py-2 text-neutral-600 dark:text-neutral-400 hover:bg-neutral-100 dark:hover:bg-neutral-700 rounded-lg transition-colors"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={isPending}
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors disabled:opacity-50"
          >
            {isPending && <Loader2 className="h-4 w-4 animate-spin" />}
            {isEdit ? 'Save Changes' : 'Create Trigger'}
          </button>
        </div>
      </form>
    </Modal>
  );
}
