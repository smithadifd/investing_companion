'use client';

import { useState } from 'react';
import { Plus, Check, Loader2, ChevronDown } from 'lucide-react';
import { useWatchlists, useAddWatchlistItem } from '@/lib/hooks/useWatchlist';

interface AddToWatchlistButtonProps {
  symbol: string;
}

export function AddToWatchlistButton({ symbol }: AddToWatchlistButtonProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [addedTo, setAddedTo] = useState<number | null>(null);

  const { data: watchlists, isLoading } = useWatchlists();
  const addMutation = useAddWatchlistItem();

  const handleAdd = async (watchlistId: number) => {
    try {
      await addMutation.mutateAsync({
        watchlistId,
        data: { symbol },
      });
      setAddedTo(watchlistId);
      setTimeout(() => {
        setAddedTo(null);
        setIsOpen(false);
      }, 1500);
    } catch (error) {
      console.error('Failed to add to watchlist:', error);
    }
  };

  return (
    <div className="relative">
      <button
        onClick={() => setIsOpen(!isOpen)}
        disabled={isLoading || addMutation.isPending}
        className="flex items-center gap-2 px-4 py-2 bg-blue-500 hover:bg-blue-600 disabled:bg-blue-500/50 text-white rounded-lg font-medium transition-colors"
      >
        {addMutation.isPending ? (
          <Loader2 className="h-4 w-4 animate-spin" />
        ) : (
          <Plus className="h-4 w-4" />
        )}
        <span className="hidden sm:inline">Add to Watchlist</span>
        <ChevronDown className="h-4 w-4" />
      </button>

      {isOpen && (
        <>
          <div
            className="fixed inset-0 z-10"
            onClick={() => setIsOpen(false)}
          />
          <div className="absolute right-0 mt-2 w-56 bg-card border border-border rounded-lg shadow-xl z-20 overflow-hidden">
            {isLoading ? (
              <div className="flex items-center justify-center p-4">
                <Loader2 className="h-4 w-4 animate-spin text-blue-500" />
              </div>
            ) : !watchlists || watchlists.length === 0 ? (
              <div className="p-4 text-center text-sm text-muted-foreground">
                No watchlists yet.
                <br />
                Create one from the Watchlists page.
              </div>
            ) : (
              <div className="py-1">
                {watchlists.map((watchlist) => (
                  <button
                    key={watchlist.id}
                    onClick={() => handleAdd(watchlist.id)}
                    disabled={addMutation.isPending}
                    className="w-full px-4 py-2 text-left text-foreground hover:bg-muted transition-colors flex items-center justify-between gap-2"
                  >
                    <span className="truncate">{watchlist.name}</span>
                    {addedTo === watchlist.id && (
                      <Check className="h-4 w-4 text-emerald-500 flex-shrink-0" />
                    )}
                  </button>
                ))}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
