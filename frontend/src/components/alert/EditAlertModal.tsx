'use client';

import { useState } from 'react';
import { X, Loader2 } from 'lucide-react';
import { useUpdateAlert } from '@/lib/hooks/useAlert';
import type { Alert, AlertConditionType, AlertUpdate } from '@/lib/api/types';

interface EditAlertModalProps {
  alert: Alert;
  onClose: () => void;
}

const CONDITION_OPTIONS: { value: AlertConditionType; label: string; description: string }[] = [
  { value: 'above', label: 'Above', description: 'Triggers when value exceeds threshold' },
  { value: 'below', label: 'Below', description: 'Triggers when value falls below threshold' },
  { value: 'crosses_above', label: 'Crosses Above', description: 'Triggers when value crosses above threshold' },
  { value: 'crosses_below', label: 'Crosses Below', description: 'Triggers when value crosses below threshold' },
  { value: 'percent_up', label: 'Percent Up', description: 'Triggers on % increase over period' },
  { value: 'percent_down', label: 'Percent Down', description: 'Triggers on % decrease over period' },
];

const PERIOD_OPTIONS = [
  { value: '1d', label: '1 Day' },
  { value: '1w', label: '1 Week' },
  { value: '1m', label: '1 Month' },
];

export function EditAlertModal({ alert, onClose }: EditAlertModalProps) {
  const [name, setName] = useState(alert.name);
  const [notes, setNotes] = useState(alert.notes || '');
  const [conditionType, setConditionType] = useState<AlertConditionType>(alert.condition_type);
  const [thresholdValue, setThresholdValue] = useState(
    typeof alert.threshold_value === 'string'
      ? alert.threshold_value
      : alert.threshold_value.toString()
  );
  const [comparisonPeriod, setComparisonPeriod] = useState(alert.comparison_period || '1d');
  const [cooldownMinutes, setCooldownMinutes] = useState(alert.cooldown_minutes.toString());
  const [isActive, setIsActive] = useState(alert.is_active);

  const updateAlert = useUpdateAlert();

  const isPercentCondition = conditionType === 'percent_up' || conditionType === 'percent_down';

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!name || !thresholdValue) return;

    const data: AlertUpdate = {
      name,
      notes: notes || undefined,
      condition_type: conditionType,
      threshold_value: parseFloat(thresholdValue),
      comparison_period: isPercentCondition ? comparisonPeriod : undefined,
      cooldown_minutes: parseInt(cooldownMinutes) || 60,
      is_active: isActive,
    };

    try {
      await updateAlert.mutateAsync({ id: alert.id, data });
      onClose();
    } catch (error) {
      console.error('Failed to update alert:', error);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white dark:bg-neutral-800 rounded-xl w-full max-w-lg shadow-xl max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between p-4 border-b border-neutral-200 dark:border-neutral-700 sticky top-0 bg-white dark:bg-neutral-800">
          <h2 className="text-xl font-semibold text-neutral-900 dark:text-neutral-50">
            Edit Alert
          </h2>
          <button
            onClick={onClose}
            className="p-1 text-neutral-500 hover:text-neutral-900 dark:text-neutral-400 dark:hover:text-neutral-50 rounded-lg transition-colors"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-4 space-y-4">
          {/* Target (read-only) */}
          {alert.target && (
            <div>
              <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
                Target
              </label>
              <div className="px-3 py-2 bg-neutral-50 dark:bg-neutral-700/50 border border-neutral-200 dark:border-neutral-600 rounded-lg text-neutral-700 dark:text-neutral-300">
                <span className="font-medium">{alert.target.symbol}</span>
                <span className="text-neutral-500 ml-2">- {alert.target.name}</span>
                <span className="text-xs text-neutral-400 ml-2">
                  ({alert.target.type === 'ratio' ? 'Ratio' : 'Equity'})
                </span>
              </div>
              <p className="text-xs text-neutral-500 mt-1">
                Target cannot be changed. Create a new alert for a different target.
              </p>
            </div>
          )}

          {/* Alert Name */}
          <div>
            <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
              Alert Name
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g., AAPL above $200"
              className="w-full px-3 py-2 border border-neutral-300 dark:border-neutral-600 rounded-lg bg-white dark:bg-neutral-700 text-neutral-900 dark:text-neutral-50 focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              required
            />
          </div>

          {/* Condition Type */}
          <div>
            <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
              Condition
            </label>
            <select
              value={conditionType}
              onChange={(e) => setConditionType(e.target.value as AlertConditionType)}
              className="w-full px-3 py-2 border border-neutral-300 dark:border-neutral-600 rounded-lg bg-white dark:bg-neutral-700 text-neutral-900 dark:text-neutral-50 focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            >
              {CONDITION_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
            <p className="text-xs text-neutral-500 mt-1">
              {CONDITION_OPTIONS.find((o) => o.value === conditionType)?.description}
            </p>
          </div>

          {/* Threshold */}
          <div>
            <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
              Threshold {isPercentCondition ? '(%)' : '(Value)'}
            </label>
            <input
              type="number"
              step="any"
              value={thresholdValue}
              onChange={(e) => setThresholdValue(e.target.value)}
              placeholder={isPercentCondition ? 'e.g., 5' : 'e.g., 200.00'}
              className="w-full px-3 py-2 border border-neutral-300 dark:border-neutral-600 rounded-lg bg-white dark:bg-neutral-700 text-neutral-900 dark:text-neutral-50 focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              required
            />
          </div>

          {/* Comparison Period (for percent conditions) */}
          {isPercentCondition && (
            <div>
              <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
                Comparison Period
              </label>
              <select
                value={comparisonPeriod}
                onChange={(e) => setComparisonPeriod(e.target.value)}
                className="w-full px-3 py-2 border border-neutral-300 dark:border-neutral-600 rounded-lg bg-white dark:bg-neutral-700 text-neutral-900 dark:text-neutral-50 focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              >
                {PERIOD_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </div>
          )}

          {/* Cooldown */}
          <div>
            <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
              Cooldown (minutes)
            </label>
            <input
              type="number"
              min="1"
              max="10080"
              value={cooldownMinutes}
              onChange={(e) => setCooldownMinutes(e.target.value)}
              className="w-full px-3 py-2 border border-neutral-300 dark:border-neutral-600 rounded-lg bg-white dark:bg-neutral-700 text-neutral-900 dark:text-neutral-50 focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            />
            <p className="text-xs text-neutral-500 mt-1">
              Minimum time between repeated notifications
            </p>
          </div>

          {/* Notes */}
          <div>
            <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
              Notes (optional)
            </label>
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Add context or instructions..."
              rows={2}
              className="w-full px-3 py-2 border border-neutral-300 dark:border-neutral-600 rounded-lg bg-white dark:bg-neutral-700 text-neutral-900 dark:text-neutral-50 focus:ring-2 focus:ring-blue-500 focus:border-transparent resize-none"
            />
          </div>

          {/* Active Toggle */}
          <div className="flex items-center gap-2">
            <input
              type="checkbox"
              id="isActive"
              checked={isActive}
              onChange={(e) => setIsActive(e.target.checked)}
              className="h-4 w-4 rounded border-neutral-300 text-blue-600 focus:ring-blue-500"
            />
            <label
              htmlFor="isActive"
              className="text-sm text-neutral-700 dark:text-neutral-300"
            >
              Alert is active
            </label>
          </div>

          {/* Submit */}
          <div className="flex justify-end gap-3 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-neutral-600 dark:text-neutral-400 hover:bg-neutral-100 dark:hover:bg-neutral-700 rounded-lg transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={updateAlert.isPending}
              className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors disabled:opacity-50"
            >
              {updateAlert.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
              Save Changes
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
