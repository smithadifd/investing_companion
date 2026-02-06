'use client';

import { useState } from 'react';
import { Loader2 } from 'lucide-react';
import { useAddWatchlistItem } from '@/lib/hooks/useWatchlist';
import { EquitySearchInput } from '@/components/equity/EquitySearchInput';
import { Modal } from '@/components/ui/Modal';
import type { EquitySearchResult } from '@/lib/api/types';

interface AddEquityModalProps {
  watchlistId: number;
  onClose: () => void;
}

export function AddEquityModal({ watchlistId, onClose }: AddEquityModalProps) {
  const [query, setQuery] = useState('');
  const [notes, setNotes] = useState('');
  const [targetPrice, setTargetPrice] = useState('');
  const [thesis, setThesis] = useState('');
  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null);

  const addMutation = useAddWatchlistItem();

  const handleAdd = async () => {
    if (!selectedSymbol) return;

    try {
      await addMutation.mutateAsync({
        watchlistId,
        data: {
          symbol: selectedSymbol,
          notes: notes || undefined,
          target_price: targetPrice ? parseFloat(targetPrice) : undefined,
          thesis: thesis || undefined,
        },
      });
      onClose();
    } catch (error) {
      console.error('Failed to add equity:', error);
    }
  };

  const handleSelect = (result: EquitySearchResult) => {
    setSelectedSymbol(result.symbol);
    setQuery(result.symbol);
  };

  return (
    <Modal onClose={onClose} title="Add Equity" maxWidth="lg">
      <div className="p-4 space-y-4 overflow-y-auto flex-1">
        {/* Search */}
        <div>
          <label className="block text-sm font-medium text-neutral-900 dark:text-neutral-50 mb-1">
            Search Symbol
          </label>
          <EquitySearchInput
            value={query}
            onChange={(value) => {
              setQuery(value);
              setSelectedSymbol(null);
            }}
            onSelect={handleSelect}
            placeholder="Search by symbol or name..."
            autoFocus
          />
        </div>

        {/* Optional fields (shown after selection) */}
        {selectedSymbol && (
          <>
            <div>
              <label className="block text-sm font-medium text-neutral-900 dark:text-neutral-50 mb-1">
                Target Price (optional)
              </label>
              <input
                type="number"
                value={targetPrice}
                onChange={(e) => setTargetPrice(e.target.value)}
                placeholder="e.g., 150.00"
                min="0"
                step="0.01"
                className="w-full px-3 py-2 bg-neutral-100 dark:bg-neutral-700 border border-neutral-200 dark:border-neutral-600 rounded-lg text-neutral-900 dark:text-neutral-50 placeholder:text-neutral-500 dark:placeholder:text-neutral-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-neutral-900 dark:text-neutral-50 mb-1">
                Notes (optional)
              </label>
              <input
                type="text"
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                placeholder="Quick note about this position..."
                className="w-full px-3 py-2 bg-neutral-100 dark:bg-neutral-700 border border-neutral-200 dark:border-neutral-600 rounded-lg text-neutral-900 dark:text-neutral-50 placeholder:text-neutral-500 dark:placeholder:text-neutral-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-neutral-900 dark:text-neutral-50 mb-1">
                Thesis (optional)
              </label>
              <textarea
                value={thesis}
                onChange={(e) => setThesis(e.target.value)}
                placeholder="Why are you tracking this equity?"
                rows={3}
                className="w-full px-3 py-2 bg-neutral-100 dark:bg-neutral-700 border border-neutral-200 dark:border-neutral-600 rounded-lg text-neutral-900 dark:text-neutral-50 placeholder:text-neutral-500 dark:placeholder:text-neutral-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent resize-none"
              />
            </div>
          </>
        )}
      </div>

      <div className="flex justify-end gap-3 p-4 border-t border-neutral-200 dark:border-neutral-700">
        <button
          type="button"
          onClick={onClose}
          className="px-4 py-2 text-neutral-500 hover:text-neutral-900 dark:text-neutral-400 dark:hover:text-neutral-50 transition-colors"
        >
          Cancel
        </button>
        <button
          onClick={handleAdd}
          disabled={!selectedSymbol || addMutation.isPending}
          className="flex items-center gap-2 px-4 py-2 bg-blue-500 hover:bg-blue-600 disabled:bg-blue-500/50 text-white rounded-lg font-medium transition-colors"
        >
          {addMutation.isPending && (
            <Loader2 className="h-4 w-4 animate-spin" />
          )}
          {addMutation.isPending ? 'Adding...' : 'Add to Watchlist'}
        </button>
      </div>
    </Modal>
  );
}
