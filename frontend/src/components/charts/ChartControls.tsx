'use client';

import { CandlestickChart, LineChart } from 'lucide-react';

export type ChartType = 'candlestick' | 'line';
export type ChartInterval = '1m' | '5m' | '15m' | '30m' | '1h' | '1d';

interface ChartControlsProps {
  chartType: ChartType;
  interval: ChartInterval;
  showSMA: boolean;
  showEMA: boolean;
  showBollingerBands: boolean;
  showRSI: boolean;
  showMACD: boolean;
  onChartTypeChange: (type: ChartType) => void;
  onIntervalChange: (interval: ChartInterval) => void;
  onToggleSMA: () => void;
  onToggleEMA: () => void;
  onToggleBollingerBands: () => void;
  onToggleRSI: () => void;
  onToggleMACD: () => void;
}

interface ToggleButtonProps {
  label: string;
  active: boolean;
  color: string;
  onClick: () => void;
  disabled?: boolean;
}

function ToggleButton({ label, active, color, onClick, disabled = false }: ToggleButtonProps) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-all ${
        disabled
          ? 'bg-neutral-100 dark:bg-neutral-700 text-neutral-400 dark:text-neutral-500 cursor-not-allowed opacity-50'
          : active
          ? `${color} text-white shadow-sm`
          : 'bg-neutral-100 dark:bg-neutral-700 text-neutral-600 dark:text-neutral-300 hover:bg-neutral-200 dark:hover:bg-neutral-600'
      }`}
      title={disabled ? 'Only available with 1D interval' : undefined}
    >
      {label}
    </button>
  );
}

const INTERVALS: { value: ChartInterval; label: string }[] = [
  { value: '1m', label: '1m' },
  { value: '5m', label: '5m' },
  { value: '15m', label: '15m' },
  { value: '30m', label: '30m' },
  { value: '1h', label: '1h' },
  { value: '1d', label: '1D' },
];

export function ChartControls({
  chartType,
  interval,
  showSMA,
  showEMA,
  showBollingerBands,
  showRSI,
  showMACD,
  onChartTypeChange,
  onIntervalChange,
  onToggleSMA,
  onToggleEMA,
  onToggleBollingerBands,
  onToggleRSI,
  onToggleMACD,
}: ChartControlsProps) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      {/* Chart Type Toggle */}
      <div className="flex items-center gap-1 bg-neutral-100 dark:bg-neutral-700 rounded-lg p-1">
        <button
          onClick={() => onChartTypeChange('candlestick')}
          className={`p-1.5 rounded-md transition-all ${
            chartType === 'candlestick'
              ? 'bg-white dark:bg-neutral-600 shadow-sm text-neutral-900 dark:text-neutral-50'
              : 'text-neutral-500 dark:text-neutral-400 hover:text-neutral-700 dark:hover:text-neutral-200'
          }`}
          title="Candlestick chart"
        >
          <CandlestickChart className="h-4 w-4" />
        </button>
        <button
          onClick={() => onChartTypeChange('line')}
          className={`p-1.5 rounded-md transition-all ${
            chartType === 'line'
              ? 'bg-white dark:bg-neutral-600 shadow-sm text-neutral-900 dark:text-neutral-50'
              : 'text-neutral-500 dark:text-neutral-400 hover:text-neutral-700 dark:hover:text-neutral-200'
          }`}
          title="Line chart"
        >
          <LineChart className="h-4 w-4" />
        </button>
      </div>

      {/* Interval Selector */}
      <div className="flex items-center gap-1 bg-neutral-100 dark:bg-neutral-700 rounded-lg p-1">
        {INTERVALS.map((int) => (
          <button
            key={int.value}
            onClick={() => onIntervalChange(int.value)}
            className={`px-2 py-1 text-xs font-medium rounded-md transition-all ${
              interval === int.value
                ? 'bg-white dark:bg-neutral-600 shadow-sm text-neutral-900 dark:text-neutral-50'
                : 'text-neutral-500 dark:text-neutral-400 hover:text-neutral-700 dark:hover:text-neutral-200'
            }`}
          >
            {int.label}
          </button>
        ))}
      </div>

      <div className="w-px h-6 bg-neutral-200 dark:bg-neutral-700 mx-1" />

      {/* Overlays - only show for candlestick charts with daily interval */}
      {chartType === 'candlestick' && (
        <>
          <div className="flex items-center gap-1 mr-1">
            <span className="text-xs text-neutral-500 dark:text-neutral-400">Overlays:</span>
          </div>
          <ToggleButton
            label="SMA"
            active={showSMA}
            color="bg-amber-500"
            onClick={onToggleSMA}
            disabled={interval !== '1d'}
          />
          <ToggleButton
            label="EMA"
            active={showEMA}
            color="bg-emerald-500"
            onClick={onToggleEMA}
            disabled={interval !== '1d'}
          />
          <ToggleButton
            label="BB"
            active={showBollingerBands}
            color="bg-indigo-500"
            onClick={onToggleBollingerBands}
            disabled={interval !== '1d'}
          />

          <div className="w-px h-6 bg-neutral-200 dark:bg-neutral-700 mx-1" />
        </>
      )}

      {/* Indicators - only available for daily interval */}
      <div className="flex items-center gap-1 mr-1">
        <span className="text-xs text-neutral-500 dark:text-neutral-400">Indicators:</span>
      </div>
      <ToggleButton
        label="RSI"
        active={showRSI}
        color="bg-amber-500"
        onClick={onToggleRSI}
        disabled={interval !== '1d'}
      />
      <ToggleButton
        label="MACD"
        active={showMACD}
        color="bg-blue-500"
        onClick={onToggleMACD}
        disabled={interval !== '1d'}
      />
    </div>
  );
}
