'use client';

import { useState, useCallback } from 'react';
import { Loader2 } from 'lucide-react';
import { useCreateAlert } from '@/lib/hooks/useAlert';
import { useRatios } from '@/lib/hooks/useRatio';
import { EquitySearchInput } from '@/components/equity/EquitySearchInput';
import { Modal } from '@/components/ui/Modal';
import type { AlertConditionType, AlertCreate, EquitySearchResult, Ratio } from '@/lib/api/types';

interface CreateAlertModalProps {
  isOpen: boolean;
  onClose: () => void;
  prefillSymbol?: string;
  prefillRatioId?: number;
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

// Short labels for auto-generated alert names
const CONDITION_NAME_LABELS: Record<AlertConditionType, string> = {
  above: 'Above',
  below: 'Below',
  crosses_above: 'Crosses Above',
  crosses_below: 'Crosses Below',
  percent_up: '% Up',
  percent_down: '% Down',
};

/**
 * Generate a descriptive alert name from the current form state.
 * Examples: "CCJ Below $118", "GLD/SLV Crosses Above 80", "AAPL % Up 5%"
 */
function generateAlertName(
  symbol: string,
  conditionType: AlertConditionType,
  thresholdValue: string,
): string {
  if (!symbol) return '';
  const label = CONDITION_NAME_LABELS[conditionType];
  const isPercent = conditionType === 'percent_up' || conditionType === 'percent_down';

  if (!thresholdValue) return `${symbol} ${label}`;

  const formattedThreshold = isPercent
    ? `${thresholdValue}%`
    : `$${thresholdValue}`;

  return `${symbol} ${label} ${formattedThreshold}`;
}

export function CreateAlertModal({
  isOpen,
  onClose,
  prefillSymbol,
  prefillRatioId,
}: CreateAlertModalProps) {
  const [targetType, setTargetType] = useState<'equity' | 'ratio'>(
    prefillRatioId ? 'ratio' : 'equity'
  );
  const [name, setName] = useState('');
  const [nameManuallyEdited, setNameManuallyEdited] = useState(false);
  const [notes, setNotes] = useState('');
  const [equitySymbol, setEquitySymbol] = useState(prefillSymbol || '');
  const [ratioId, setRatioId] = useState<number | undefined>(prefillRatioId);
  const [ratioSymbol, setRatioSymbol] = useState('');
  const [conditionType, setConditionType] = useState<AlertConditionType>('above');
  const [thresholdValue, setThresholdValue] = useState('');
  const [comparisonPeriod, setComparisonPeriod] = useState('1d');
  const [cooldownMinutes, setCooldownMinutes] = useState('60');
  const [isActive, setIsActive] = useState(true);

  const [searchQuery, setSearchQuery] = useState('');

  const { data: ratios } = useRatios();
  const createAlert = useCreateAlert();

  const isPercentCondition = conditionType === 'percent_up' || conditionType === 'percent_down';

  // Auto-update name when symbol, condition, or threshold changes
  const updateAutoName = useCallback(
    (symbol: string, condition: AlertConditionType, threshold: string) => {
      if (!nameManuallyEdited) {
        setName(generateAlertName(symbol, condition, threshold));
      }
    },
    [nameManuallyEdited]
  );

  // Get the current display symbol for auto-naming
  const currentSymbol = targetType === 'equity' ? equitySymbol.toUpperCase() : ratioSymbol;

  const handleSearchChange = (query: string) => {
    setSearchQuery(query);
    setEquitySymbol(query);
  };

  const handleSelectEquity = (equity: EquitySearchResult) => {
    setEquitySymbol(equity.symbol);
    setSearchQuery(equity.symbol);
    updateAutoName(equity.symbol, conditionType, thresholdValue);
  };

  const handleSelectRatio = (ratio: Ratio) => {
    setRatioId(ratio.id);
    const symbol = `${ratio.numerator_symbol}/${ratio.denominator_symbol}`;
    setRatioSymbol(symbol);
    updateAutoName(symbol, conditionType, thresholdValue);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!name || !thresholdValue) return;
    if (targetType === 'equity' && !equitySymbol) return;
    if (targetType === 'ratio' && !ratioId) return;

    const data: AlertCreate = {
      name,
      notes: notes || undefined,
      equity_symbol: targetType === 'equity' ? equitySymbol.toUpperCase() : undefined,
      ratio_id: targetType === 'ratio' ? ratioId : undefined,
      condition_type: conditionType,
      threshold_value: parseFloat(thresholdValue),
      comparison_period: isPercentCondition ? comparisonPeriod : undefined,
      cooldown_minutes: parseInt(cooldownMinutes) || 60,
      is_active: isActive,
    };

    try {
      await createAlert.mutateAsync(data);
      handleClose();
    } catch (error) {
      console.error('Failed to create alert:', error);
    }
  };

  const handleClose = () => {
    setName('');
    setNameManuallyEdited(false);
    setNotes('');
    setEquitySymbol(prefillSymbol || '');
    setRatioId(prefillRatioId);
    setRatioSymbol('');
    setConditionType('above');
    setThresholdValue('');
    setComparisonPeriod('1d');
    setCooldownMinutes('60');
    setIsActive(true);
    setSearchQuery('');
    onClose();
  };

  if (!isOpen) return null;

  return (
    <Modal onClose={handleClose} title="Create Alert" maxWidth="lg">
      <form onSubmit={handleSubmit} className="p-4 space-y-4">
          {/* Target Type */}
          <div>
            <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-2">
              Alert Target
            </label>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => setTargetType('equity')}
                className={`flex-1 py-2 px-4 rounded-lg text-sm font-medium transition-colors ${
                  targetType === 'equity'
                    ? 'bg-blue-600 text-white'
                    : 'bg-neutral-100 dark:bg-neutral-700 text-neutral-700 dark:text-neutral-300 hover:bg-neutral-200 dark:hover:bg-neutral-600'
                }`}
              >
                Equity
              </button>
              <button
                type="button"
                onClick={() => setTargetType('ratio')}
                className={`flex-1 py-2 px-4 rounded-lg text-sm font-medium transition-colors ${
                  targetType === 'ratio'
                    ? 'bg-blue-600 text-white'
                    : 'bg-neutral-100 dark:bg-neutral-700 text-neutral-700 dark:text-neutral-300 hover:bg-neutral-200 dark:hover:bg-neutral-600'
                }`}
              >
                Ratio
              </button>
            </div>
          </div>

          {/* Equity Search or Ratio Select */}
          {targetType === 'equity' ? (
            <div>
              <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
                Symbol
              </label>
              <EquitySearchInput
                value={searchQuery}
                onChange={handleSearchChange}
                onSelect={handleSelectEquity}
                required
              />
            </div>
          ) : (
            <div>
              <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
                Ratio
              </label>
              <select
                value={ratioId || ''}
                onChange={(e) => {
                  const id = parseInt(e.target.value);
                  const ratio = ratios?.find((r) => r.id === id);
                  if (ratio) handleSelectRatio(ratio);
                  else setRatioId(id);
                }}
                className="w-full px-3 py-2 border border-neutral-300 dark:border-neutral-600 rounded-lg bg-white dark:bg-neutral-700 text-neutral-900 dark:text-neutral-50 focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                required
              >
                <option value="">Select a ratio...</option>
                {ratios?.map((ratio) => (
                  <option key={ratio.id} value={ratio.id}>
                    {ratio.name} ({ratio.numerator_symbol}/{ratio.denominator_symbol})
                  </option>
                ))}
              </select>
            </div>
          )}

          {/* Condition Type */}
          <div>
            <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
              Condition
            </label>
            <select
              value={conditionType}
              onChange={(e) => {
                const newCondition = e.target.value as AlertConditionType;
                setConditionType(newCondition);
                updateAutoName(currentSymbol, newCondition, thresholdValue);
              }}
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
              onChange={(e) => {
                setThresholdValue(e.target.value);
                updateAutoName(currentSymbol, conditionType, e.target.value);
              }}
              placeholder={isPercentCondition ? 'e.g., 5' : 'e.g., 200.00'}
              className="w-full px-3 py-2 border border-neutral-300 dark:border-neutral-600 rounded-lg bg-white dark:bg-neutral-700 text-neutral-900 dark:text-neutral-50 focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              required
            />
          </div>

          {/* Alert Name */}
          <div>
            <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
              Alert Name
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => {
                setName(e.target.value);
                setNameManuallyEdited(true);
              }}
              placeholder="Auto-generated from symbol & condition"
              className="w-full px-3 py-2 border border-neutral-300 dark:border-neutral-600 rounded-lg bg-white dark:bg-neutral-700 text-neutral-900 dark:text-neutral-50 focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              required
            />
            {!nameManuallyEdited && name && (
              <p className="text-xs text-neutral-400 mt-1">
                Auto-generated — edit to customize
              </p>
            )}
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
              Activate alert immediately
            </label>
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
              disabled={createAlert.isPending}
              className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors disabled:opacity-50"
            >
              {createAlert.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
              Create Alert
            </button>
          </div>
      </form>
    </Modal>
  );
}
