'use client';

interface ChartControlsProps {
  showSMA: boolean;
  showEMA: boolean;
  showBollingerBands: boolean;
  showRSI: boolean;
  showMACD: boolean;
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
}

function ToggleButton({ label, active, color, onClick }: ToggleButtonProps) {
  return (
    <button
      onClick={onClick}
      className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-all ${
        active
          ? `${color} text-white shadow-sm`
          : 'bg-neutral-100 dark:bg-neutral-700 text-neutral-600 dark:text-neutral-300 hover:bg-neutral-200 dark:hover:bg-neutral-600'
      }`}
    >
      {label}
    </button>
  );
}

export function ChartControls({
  showSMA,
  showEMA,
  showBollingerBands,
  showRSI,
  showMACD,
  onToggleSMA,
  onToggleEMA,
  onToggleBollingerBands,
  onToggleRSI,
  onToggleMACD,
}: ChartControlsProps) {
  return (
    <div className="flex flex-wrap gap-2">
      <div className="flex items-center gap-1 mr-2">
        <span className="text-xs text-neutral-500 dark:text-neutral-400">Overlays:</span>
      </div>
      <ToggleButton
        label="SMA"
        active={showSMA}
        color="bg-amber-500"
        onClick={onToggleSMA}
      />
      <ToggleButton
        label="EMA"
        active={showEMA}
        color="bg-emerald-500"
        onClick={onToggleEMA}
      />
      <ToggleButton
        label="BB"
        active={showBollingerBands}
        color="bg-indigo-500"
        onClick={onToggleBollingerBands}
      />

      <div className="w-px h-6 bg-neutral-200 dark:bg-neutral-700 mx-2" />

      <div className="flex items-center gap-1 mr-2">
        <span className="text-xs text-neutral-500 dark:text-neutral-400">Indicators:</span>
      </div>
      <ToggleButton
        label="RSI"
        active={showRSI}
        color="bg-amber-500"
        onClick={onToggleRSI}
      />
      <ToggleButton
        label="MACD"
        active={showMACD}
        color="bg-blue-500"
        onClick={onToggleMACD}
      />
    </div>
  );
}
