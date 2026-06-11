'use client';

import { Plus, X } from 'lucide-react';

export interface ZoneDraft {
  tier: string;
  low: string;
  high: string;
}

const MAX_ZONES = 8;

const inputClass =
  'px-2 py-1.5 bg-neutral-100 dark:bg-neutral-700 border border-neutral-200 dark:border-neutral-600 rounded-lg text-sm text-neutral-900 dark:text-neutral-50 placeholder:text-neutral-500 dark:placeholder:text-neutral-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent';

/**
 * Editor for tiered entry zones: rows of (tier name, low, high).
 * Each zone needs at least one bound; leave low empty for "sub-X" tiers.
 */
export function EntryZoneEditor({
  zones,
  onChange,
}: {
  zones: ZoneDraft[];
  onChange: (zones: ZoneDraft[]) => void;
}) {
  const update = (index: number, patch: Partial<ZoneDraft>) => {
    onChange(zones.map((z, i) => (i === index ? { ...z, ...patch } : z)));
  };

  return (
    <div className="space-y-2">
      {zones.map((zone, index) => (
        <div key={index} className="flex items-center gap-2">
          <input
            type="text"
            value={zone.tier}
            onChange={(e) => update(index, { tier: e.target.value })}
            placeholder={`Tier ${index + 1} (e.g., Half starter)`}
            aria-label={`Zone ${index + 1} tier name`}
            maxLength={40}
            className={`flex-1 min-w-0 ${inputClass}`}
          />
          <input
            type="number"
            value={zone.low}
            onChange={(e) => update(index, { low: e.target.value })}
            placeholder="Low"
            aria-label={`Zone ${index + 1} low bound`}
            min="0"
            step="0.01"
            className={`w-24 ${inputClass}`}
          />
          <span className="text-neutral-400">–</span>
          <input
            type="number"
            value={zone.high}
            onChange={(e) => update(index, { high: e.target.value })}
            placeholder="High"
            aria-label={`Zone ${index + 1} high bound`}
            min="0"
            step="0.01"
            className={`w-24 ${inputClass}`}
          />
          <button
            type="button"
            onClick={() => onChange(zones.filter((_, i) => i !== index))}
            title="Remove zone"
            className="p-1.5 text-neutral-400 hover:text-red-500 hover:bg-red-500/10 rounded transition-colors"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      ))}

      {zones.length < MAX_ZONES && (
        <button
          type="button"
          onClick={() => onChange([...zones, { tier: '', low: '', high: '' }])}
          className="flex items-center gap-1.5 text-sm text-blue-500 hover:text-blue-600 transition-colors"
        >
          <Plus className="h-4 w-4" />
          Add zone
        </button>
      )}
    </div>
  );
}

/** Validate drafts; returns an error message or null. Empty rows are ignored. */
export function validateZoneDrafts(zones: ZoneDraft[]): string | null {
  const active = zones.filter((z) => z.tier.trim() || z.low || z.high);
  const names = new Set<string>();
  for (const zone of active) {
    if (!zone.tier.trim()) {
      return 'Each zone needs a tier name';
    }
    if (!zone.low && !zone.high) {
      return `Zone "${zone.tier}" needs at least one bound`;
    }
    const low = zone.low ? parseFloat(zone.low) : null;
    const high = zone.high ? parseFloat(zone.high) : null;
    if (low !== null && high !== null && low >= high) {
      return `Zone "${zone.tier}": low must be less than high`;
    }
    const key = zone.tier.trim().toLowerCase();
    if (names.has(key)) {
      return `Duplicate tier name "${zone.tier.trim()}"`;
    }
    names.add(key);
  }
  return null;
}

/** Convert valid drafts to the API shape, dropping empty rows. */
export function zoneDraftsToApi(zones: ZoneDraft[]) {
  return zones
    .filter((z) => z.tier.trim() || z.low || z.high)
    .map((z) => ({
      tier: z.tier.trim(),
      low: z.low ? parseFloat(z.low) : null,
      high: z.high ? parseFloat(z.high) : null,
    }));
}
