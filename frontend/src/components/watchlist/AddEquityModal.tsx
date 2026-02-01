'use client';

import { useState } from 'react';
import { X, Loader2, Search } from 'lucide-react';
import { useEquitySearch } from '@/lib/hooks/useEquity';
import { useAddWatchlistItem } from '@/lib/hooks/useWatchlist';

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

  const { data: searchResults, isLoading: searching } = useEquitySearch(
    query,
    query.length >= 1
  );
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

  const handleSelect = (symbol: string) => {
    setSelectedSymbol(symbol);
    setQuery(symbol);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div
        className="absolute inset-0 bg-black/50 backdrop-blur-sm"
        onClick={onClose}
      />
      <div className="relative bg-white dark:bg-neutral-800 border border-neutral-200 dark:border-neutral-700 rounded-xl shadow-xl w-full max-w-lg max-h-[90vh] overflow-hidden flex flex-col">
        <div className="flex items-center justify-between p-4 border-b border-neutral-200 dark:border-neutral-700">
          <h2 className="text-lg font-semibold text-neutral-900 dark:text-neutral-50">Add Equity</h2>
          <button
            onClick={onClose}
            className="p-1 text-neutral-500 hover:text-neutral-900 dark:text-neutral-400 dark:hover:text-neutral-50 rounded-lg transition-colors"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="p-4 space-y-4 overflow-y-auto flex-1">
          {/* Search */}
          <div>
            <label className="block text-sm font-medium text-neutral-900 dark:text-neutral-50 mb-1">
              Search Symbol
            </label>
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-neutral-500 dark:text-neutral-400" />
              <input
                type="text"
                value={query}
                onChange={(e) => {
                  setQuery(e.target.value);
                  setSelectedSymbol(null);
                }}
                placeholder="Search by symbol or name..."
                className="w-full pl-10 pr-4 py-2 bg-neutral-100 dark:bg-neutral-700 border border-neutral-200 dark:border-neutral-600 rounded-lg text-neutral-900 dark:text-neutral-50 placeholder:text-neutral-500 dark:placeholder:text-neutral-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                autoFocus
              />
            </div>

            {/* Search results */}
            {query && !selectedSymbol && (
              <div className="mt-2 bg-neutral-100 dark:bg-neutral-700 border border-neutral-200 dark:border-neutral-600 rounded-lg max-h-40 overflow-y-auto">
                {searching ? (
                  <div className="flex items-center justify-center p-4">
                    <Loader2 className="h-4 w-4 animate-spin text-blue-500" />
                  </div>
                ) : searchResults && searchResults.length > 0 ? (
                  searchResults.map((result) => (
                    <button
                      key={result.symbol}
                      onClick={() => handleSelect(result.symbol)}
                      className="w-full px-4 py-2 text-left hover:bg-blue-500/10 transition-colors"
                    >
                      <span className="font-semibold text-neutral-900 dark:text-neutral-50">
                        {result.symbol}
                      </span>
                      <span className="text-neutral-500 dark:text-neutral-400 ml-2 text-sm">
                        {result.name}
                      </span>
                    </button>
                  ))
                ) : query.length >= 1 ? (
                  <div className="p-4 text-center text-neutral-500 dark:text-neutral-400 text-sm">
                    No results found
                  </div>
                ) : null}
              </div>
            )}
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
      </div>
    </div>
  );
}
