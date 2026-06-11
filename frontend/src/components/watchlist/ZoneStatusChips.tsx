'use client';

import type { EntryZoneStatus, ZoneStatusValue } from '@/lib/api/types';
import { formatCurrency } from '@/lib/utils/format';

const STATUS_STYLES: Record<ZoneStatusValue, string> = {
  in_zone:
    'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400',
  approaching:
    'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400',
  above:
    'bg-neutral-100 text-neutral-600 dark:bg-neutral-700 dark:text-neutral-400',
  below:
    'bg-neutral-100 text-neutral-500 dark:bg-neutral-700 dark:text-neutral-500',
  unknown:
    'bg-neutral-100 text-neutral-400 dark:bg-neutral-700 dark:text-neutral-500',
};

const STATUS_LABELS: Record<ZoneStatusValue, string> = {
  in_zone: 'in zone',
  approaching: 'near',
  above: 'above',
  below: 'below',
  unknown: '?',
};

function bandLabel(zone: EntryZoneStatus): string {
  if (zone.low !== null && zone.high !== null) {
    return `${formatCurrency(zone.low)}–${formatCurrency(zone.high)}`;
  }
  if (zone.high !== null) {
    return `≤ ${formatCurrency(zone.high)}`;
  }
  if (zone.low !== null) {
    return `≥ ${formatCurrency(zone.low)}`;
  }
  return 'no bounds';
}

export function ZoneStatusChips({ zones }: { zones: EntryZoneStatus[] }) {
  if (!zones.length) return null;

  return (
    <div className="flex flex-wrap gap-1">
      {zones.map((zone) => (
        <span
          key={zone.tier}
          title={`${zone.tier}: ${bandLabel(zone)}`}
          className={`inline-flex items-center gap-1 text-xs px-1.5 py-0.5 rounded-full whitespace-nowrap ${STATUS_STYLES[zone.status]}`}
        >
          <span className="font-medium">{zone.tier}</span>
          <span className="opacity-75">{STATUS_LABELS[zone.status]}</span>
        </span>
      ))}
    </div>
  );
}
