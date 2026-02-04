'use client';

interface PeriodSelectorProps {
  value: string;
  onChange: (period: string) => void;
}

const periods = [
  { value: '1d', label: '1D' },
  { value: '5d', label: '5D' },
  { value: '1mo', label: '1M' },
  { value: '3mo', label: '3M' },
  { value: '6mo', label: '6M' },
  { value: '1y', label: '1Y' },
  { value: '2y', label: '2Y' },
  { value: '5y', label: '5Y' },
];

export function PeriodSelector({ value, onChange }: PeriodSelectorProps) {
  return (
    <div className="flex gap-1 bg-neutral-100 dark:bg-neutral-700 rounded-lg p-1 overflow-x-auto">
      {periods.map((period) => (
        <button
          key={period.value}
          onClick={() => onChange(period.value)}
          className={`px-2 sm:px-3 py-1.5 text-xs sm:text-sm font-medium rounded-md transition-colors whitespace-nowrap ${
            value === period.value
              ? 'bg-white dark:bg-neutral-600 text-neutral-900 dark:text-neutral-50 shadow-sm'
              : 'text-neutral-500 dark:text-neutral-400 hover:text-neutral-900 dark:hover:text-neutral-50'
          }`}
        >
          {period.label}
        </button>
      ))}
    </div>
  );
}
