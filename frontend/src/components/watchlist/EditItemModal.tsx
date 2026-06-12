'use client';

import { useState } from 'react';
import { Loader2, Calendar, Bell, Layers } from 'lucide-react';
import { useUpdateWatchlistItem } from '@/lib/hooks/useWatchlist';
import { useAlerts, useCreateAlert, useDeleteAlert } from '@/lib/hooks/useAlert';
import { Modal } from '@/components/ui/Modal';
import {
  EntryZoneEditor,
  validateZoneDrafts,
  zoneDraftsToApi,
  type ZoneDraft,
} from './EntryZoneEditor';
import type { WatchlistItem } from '@/lib/api/types';

interface EditItemModalProps {
  watchlistId: number;
  item: WatchlistItem;
  onClose: () => void;
}

export function EditItemModal({
  watchlistId,
  item,
  onClose,
}: EditItemModalProps) {
  const [notes, setNotes] = useState(item.notes || '');
  const [targetPrice, setTargetPrice] = useState(
    item.target_price ? String(item.target_price) : ''
  );
  const [thesis, setThesis] = useState(item.thesis || '');
  const [catalystTags, setCatalystTags] = useState(
    (item.catalyst_tags ?? []).join(', ')
  );
  const [trackCalendar, setTrackCalendar] = useState(item.track_calendar ?? false);
  const [zones, setZones] = useState<ZoneDraft[]>(
    (item.entry_zones ?? []).map((z) => ({
      tier: z.tier,
      low: z.low !== null && z.low !== undefined ? String(z.low) : '',
      high: z.high !== null && z.high !== undefined ? String(z.high) : '',
    }))
  );
  const [zoneError, setZoneError] = useState<string | null>(null);

  // The zone-hit alert for this item, if one exists. The toggle and save
  // wait for this query so a slow load can't misreport (and delete) an
  // existing alert.
  const { data: equityAlerts, isLoading: alertsLoading } = useAlerts(
    false,
    item.equity_id
  );
  const existingZoneAlert = equityAlerts?.find(
    (a) => a.condition_type === 'entry_zone' && a.watchlist_item_id === item.id
  );
  const [zoneAlertEnabled, setZoneAlertEnabled] = useState<boolean | null>(null);
  const zoneAlertOn = zoneAlertEnabled ?? Boolean(existingZoneAlert);

  const updateMutation = useUpdateWatchlistItem();
  const createAlertMutation = useCreateAlert();
  const deleteAlertMutation = useDeleteAlert();

  const isPending =
    alertsLoading ||
    updateMutation.isPending ||
    createAlertMutation.isPending ||
    deleteAlertMutation.isPending;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    const validationError = validateZoneDrafts(zones);
    setZoneError(validationError);
    if (validationError) return;

    const apiZones = zoneDraftsToApi(zones);
    const apiCatalysts = catalystTags
      .split(',')
      .map((t) => t.trim())
      .filter(Boolean);

    try {
      await updateMutation.mutateAsync({
        watchlistId,
        itemId: item.id,
        data: {
          notes: notes.trim() || undefined,
          target_price: targetPrice ? parseFloat(targetPrice) : undefined,
          thesis: thesis.trim() || undefined,
          track_calendar: trackCalendar,
          // null clears the zones; a list replaces them
          entry_zones: apiZones.length ? apiZones : null,
          // [] clears catalyst tags; backend lowercases + dedupes
          catalyst_tags: apiCatalysts,
        },
      });

      if (zoneAlertOn && !existingZoneAlert && apiZones.length) {
        await createAlertMutation.mutateAsync({
          name: `${item.equity.symbol} entry zones`,
          condition_type: 'entry_zone',
          watchlist_item_id: item.id,
        });
      } else if (!zoneAlertOn && existingZoneAlert) {
        await deleteAlertMutation.mutateAsync(existingZoneAlert.id);
      }

      onClose();
    } catch (error) {
      console.error('Failed to update item:', error);
    }
  };

  return (
    <Modal onClose={onClose} title={`Edit ${item.equity.symbol}`} maxWidth="lg">
      <form onSubmit={handleSubmit} className="p-4 space-y-4">
        <div>
          <label
            htmlFor="targetPrice"
            className="block text-sm font-medium text-neutral-900 dark:text-neutral-50 mb-1"
          >
            Target Price
          </label>
          <input
            type="number"
            id="targetPrice"
            value={targetPrice}
            onChange={(e) => setTargetPrice(e.target.value)}
            placeholder="e.g., 150.00"
            min="0"
            step="0.01"
            className="w-full px-3 py-2 bg-neutral-100 dark:bg-neutral-700 border border-neutral-200 dark:border-neutral-600 rounded-lg text-neutral-900 dark:text-neutral-50 placeholder:text-neutral-500 dark:placeholder:text-neutral-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
          />
        </div>

        <div>
          <label
            htmlFor="notes"
            className="block text-sm font-medium text-neutral-900 dark:text-neutral-50 mb-1"
          >
            Notes
          </label>
          <input
            type="text"
            id="notes"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="Quick note about this position..."
            className="w-full px-3 py-2 bg-neutral-100 dark:bg-neutral-700 border border-neutral-200 dark:border-neutral-600 rounded-lg text-neutral-900 dark:text-neutral-50 placeholder:text-neutral-500 dark:placeholder:text-neutral-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
          />
        </div>

        <div>
          <label
            htmlFor="thesis"
            className="block text-sm font-medium text-neutral-900 dark:text-neutral-50 mb-1"
          >
            Investment Thesis
          </label>
          <textarea
            id="thesis"
            value={thesis}
            onChange={(e) => setThesis(e.target.value)}
            placeholder="Why are you tracking this equity? What's your thesis?"
            rows={4}
            className="w-full px-3 py-2 bg-neutral-100 dark:bg-neutral-700 border border-neutral-200 dark:border-neutral-600 rounded-lg text-neutral-900 dark:text-neutral-50 placeholder:text-neutral-500 dark:placeholder:text-neutral-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent resize-none"
          />
        </div>

        {/* Catalyst tags */}
        <div>
          <label
            htmlFor="catalystTags"
            className="block text-sm font-medium text-neutral-900 dark:text-neutral-50 mb-1"
          >
            Catalyst Tags
          </label>
          <input
            type="text"
            id="catalystTags"
            value={catalystTags}
            onChange={(e) => setCatalystTags(e.target.value)}
            placeholder="uranium restart, carry unwind"
            className="w-full px-3 py-2 bg-neutral-100 dark:bg-neutral-700 border border-neutral-200 dark:border-neutral-600 rounded-lg text-neutral-900 dark:text-neutral-50 placeholder:text-neutral-500 dark:placeholder:text-neutral-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
          />
          <p className="text-xs text-neutral-500 dark:text-neutral-400 mt-1">
            Comma-separated single-catalyst clusters. Groups exposure across
            holdings that share a catalyst.
          </p>
        </div>

        {/* Tiered entry zones */}
        <div className="p-3 bg-neutral-50 dark:bg-neutral-700/50 rounded-lg space-y-3">
          <div className="flex items-center gap-3">
            <Layers className="h-5 w-5 text-amber-500" />
            <div>
              <p className="text-sm font-medium text-neutral-900 dark:text-neutral-50">
                Entry Zones
              </p>
              <p className="text-xs text-neutral-500 dark:text-neutral-400">
                Tiered buy zones (e.g., $50–52 half starter, sub-46 aggressive).
                Leave low empty for &quot;sub-X&quot; tiers.
              </p>
            </div>
          </div>

          <EntryZoneEditor zones={zones} onChange={setZones} />

          {zoneError && (
            <p className="text-sm text-red-500" role="alert">
              {zoneError}
            </p>
          )}

          <div className="flex items-center justify-between pt-1">
            <div className="flex items-center gap-2">
              <Bell className="h-4 w-4 text-blue-500" />
              <p className="text-sm text-neutral-900 dark:text-neutral-50">
                Alert when price enters a zone
              </p>
            </div>
            <button
              type="button"
              role="switch"
              aria-checked={zoneAlertOn}
              aria-label="Alert when price enters a zone"
              disabled={alertsLoading}
              onClick={() => setZoneAlertEnabled(!zoneAlertOn)}
              className={`relative w-11 h-6 rounded-full transition-colors disabled:opacity-50 ${
                zoneAlertOn ? 'bg-blue-500' : 'bg-neutral-300 dark:bg-neutral-600'
              }`}
            >
              <span
                className={`absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full shadow transition-transform ${
                  zoneAlertOn ? 'translate-x-5' : 'translate-x-0'
                }`}
              />
            </button>
          </div>
        </div>

        {/* Calendar tracking toggle */}
        <div className="flex items-center justify-between p-3 bg-neutral-50 dark:bg-neutral-700/50 rounded-lg">
          <div className="flex items-center gap-3">
            <Calendar className="h-5 w-5 text-blue-500" />
            <div>
              <p className="text-sm font-medium text-neutral-900 dark:text-neutral-50">
                Track on Calendar
              </p>
              <p className="text-xs text-neutral-500 dark:text-neutral-400">
                Show earnings and dividend dates for this equity
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={() => setTrackCalendar(!trackCalendar)}
            className={`relative w-11 h-6 rounded-full transition-colors ${
              trackCalendar ? 'bg-blue-500' : 'bg-neutral-300 dark:bg-neutral-600'
            }`}
          >
            <span
              className={`absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full shadow transition-transform ${
                trackCalendar ? 'translate-x-5' : 'translate-x-0'
              }`}
            />
          </button>
        </div>

        <div className="flex justify-end gap-3 pt-2">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 text-neutral-500 hover:text-neutral-900 dark:text-neutral-400 dark:hover:text-neutral-50 transition-colors"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={isPending}
            className="flex items-center gap-2 px-4 py-2 bg-blue-500 hover:bg-blue-600 disabled:bg-blue-500/50 text-white rounded-lg font-medium transition-colors"
          >
            {isPending && <Loader2 className="h-4 w-4 animate-spin" />}
            {isPending ? 'Saving...' : 'Save Changes'}
          </button>
        </div>
      </form>
    </Modal>
  );
}
