'use client';

import { useState } from 'react';
import { X, Loader2 } from 'lucide-react';
import { useUpdateWatchlistItem } from '@/lib/hooks/useWatchlist';
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

  const updateMutation = useUpdateWatchlistItem();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    try {
      await updateMutation.mutateAsync({
        watchlistId,
        itemId: item.id,
        data: {
          notes: notes.trim() || undefined,
          target_price: targetPrice ? parseFloat(targetPrice) : undefined,
          thesis: thesis.trim() || undefined,
        },
      });
      onClose();
    } catch (error) {
      console.error('Failed to update item:', error);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div
        className="absolute inset-0 bg-black/50 backdrop-blur-sm"
        onClick={onClose}
      />
      <div className="relative bg-white dark:bg-neutral-800 border border-neutral-200 dark:border-neutral-700 rounded-xl shadow-xl w-full max-w-lg">
        <div className="flex items-center justify-between p-4 border-b border-neutral-200 dark:border-neutral-700">
          <div>
            <h2 className="text-lg font-semibold text-neutral-900 dark:text-neutral-50">
              Edit {item.equity.symbol}
            </h2>
            <p className="text-sm text-neutral-500 dark:text-neutral-400">{item.equity.name}</p>
          </div>
          <button
            onClick={onClose}
            className="p-1 text-neutral-500 hover:text-neutral-900 dark:text-neutral-400 dark:hover:text-neutral-50 rounded-lg transition-colors"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

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
              disabled={updateMutation.isPending}
              className="flex items-center gap-2 px-4 py-2 bg-blue-500 hover:bg-blue-600 disabled:bg-blue-500/50 text-white rounded-lg font-medium transition-colors"
            >
              {updateMutation.isPending && (
                <Loader2 className="h-4 w-4 animate-spin" />
              )}
              {updateMutation.isPending ? 'Saving...' : 'Save Changes'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
