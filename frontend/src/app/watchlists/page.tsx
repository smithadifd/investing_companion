'use client';

import { useState } from 'react';
import Link from 'next/link';
import { Loader2, Plus, List, Trash2, Upload } from 'lucide-react';
import { useWatchlists, useCreateWatchlist, useDeleteWatchlist } from '@/lib/hooks/useWatchlist';
import { CreateWatchlistModal } from '@/components/watchlist/CreateWatchlistModal';
import { ImportWatchlistModal } from '@/components/watchlist/ImportWatchlistModal';
import { ConfirmModal } from '@/components/ui/ConfirmModal';
import { formatDate } from '@/lib/utils/format';
import type { WatchlistSummary } from '@/lib/api/types';

export default function WatchlistsPage() {
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [showImportModal, setShowImportModal] = useState(false);
  const [deletingWatchlist, setDeletingWatchlist] = useState<WatchlistSummary | null>(null);
  const { data: watchlists, isLoading, error, refetch } = useWatchlists();
  const createMutation = useCreateWatchlist();
  const deleteMutation = useDeleteWatchlist();

  const handleCreate = async (name: string, description: string) => {
    await createMutation.mutateAsync({ name, description });
    setShowCreateModal(false);
  };

  const handleDeleteClick = (watchlist: WatchlistSummary, e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDeletingWatchlist(watchlist);
  };

  const handleDeleteConfirm = async () => {
    if (!deletingWatchlist) return;
    await deleteMutation.mutateAsync(deletingWatchlist.id);
    setDeletingWatchlist(null);
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-[calc(100vh-4rem)] bg-neutral-50 dark:bg-neutral-900">
        <div className="flex flex-col items-center gap-4">
          <Loader2 className="h-8 w-8 animate-spin text-blue-500" />
          <span className="text-neutral-500 dark:text-neutral-400">Loading watchlists...</span>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center min-h-[calc(100vh-4rem)] bg-neutral-50 dark:bg-neutral-900">
        <div className="text-center">
          <h1 className="text-2xl font-bold text-neutral-900 dark:text-neutral-50">Error Loading Watchlists</h1>
          <p className="text-neutral-500 dark:text-neutral-400 mt-2">
            Could not load your watchlists. Please try again later.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-[calc(100vh-4rem)] bg-neutral-50 dark:bg-neutral-900">
      <div className="max-w-4xl mx-auto px-4 sm:px-6 py-6 sm:py-8">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl sm:text-3xl font-bold text-neutral-900 dark:text-neutral-50">
              Watchlists
            </h1>
            <p className="text-neutral-500 dark:text-neutral-400 mt-1 text-sm">
              Track equities with notes and price targets
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setShowImportModal(true)}
              className="flex items-center gap-2 px-4 py-2 border border-neutral-200 dark:border-neutral-700 hover:bg-neutral-100 dark:hover:bg-neutral-800 text-neutral-900 dark:text-neutral-50 rounded-lg font-medium transition-colors"
            >
              <Upload className="h-4 w-4" />
              <span className="hidden sm:inline">Import</span>
            </button>
            <button
              onClick={() => setShowCreateModal(true)}
              className="flex items-center gap-2 px-4 py-2 bg-blue-500 hover:bg-blue-600 text-white rounded-lg font-medium transition-colors"
            >
              <Plus className="h-4 w-4" />
              <span className="hidden sm:inline">New Watchlist</span>
            </button>
          </div>
        </div>

        {!watchlists || watchlists.length === 0 ? (
          <div className="bg-white dark:bg-neutral-800 border border-neutral-200 dark:border-neutral-700 rounded-xl p-12 text-center">
            <List className="h-12 w-12 text-neutral-400 mx-auto mb-4" />
            <h2 className="text-xl font-semibold text-neutral-900 dark:text-neutral-50 mb-2">
              No Watchlists Yet
            </h2>
            <p className="text-neutral-500 dark:text-neutral-400 mb-6">
              Create your first watchlist to start tracking equities.
            </p>
            <button
              onClick={() => setShowCreateModal(true)}
              className="inline-flex items-center gap-2 px-4 py-2 bg-blue-500 hover:bg-blue-600 text-white rounded-lg font-medium transition-colors"
            >
              <Plus className="h-4 w-4" />
              Create Watchlist
            </button>
          </div>
        ) : (
          <div className="grid gap-4">
            {watchlists.map((watchlist) => (
              <Link
                key={watchlist.id}
                href={`/watchlists/${watchlist.id}`}
                className="block bg-white dark:bg-neutral-800 border border-neutral-200 dark:border-neutral-700 rounded-xl p-5 hover:shadow-md hover:border-blue-500/30 transition-all group"
              >
                <div className="flex items-start justify-between">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <h2 className="text-lg font-semibold text-neutral-900 dark:text-neutral-50 truncate">
                        {watchlist.name}
                      </h2>
                      {watchlist.is_default && (
                        <span className="px-2 py-0.5 text-xs font-medium bg-blue-500/10 text-blue-600 dark:text-blue-400 rounded-full">
                          Default
                        </span>
                      )}
                    </div>
                    {watchlist.description && (
                      <p className="text-neutral-500 dark:text-neutral-400 text-sm mt-1 line-clamp-2">
                        {watchlist.description}
                      </p>
                    )}
                    <div className="flex items-center gap-4 mt-3 text-sm text-neutral-500 dark:text-neutral-400">
                      <span>{watchlist.item_count} {watchlist.item_count === 1 ? 'item' : 'items'}</span>
                      <span>Updated {formatDate(watchlist.updated_at)}</span>
                    </div>
                  </div>
                  <button
                    onClick={(e) => handleDeleteClick(watchlist, e)}
                    className="p-2 text-neutral-400 hover:text-red-500 hover:bg-red-500/10 rounded-lg opacity-0 group-hover:opacity-100 transition-all"
                    title="Delete watchlist"
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
              </Link>
            ))}
          </div>
        )}
      </div>

      {showCreateModal && (
        <CreateWatchlistModal
          onClose={() => setShowCreateModal(false)}
          onCreate={handleCreate}
          isCreating={createMutation.isPending}
        />
      )}

      {showImportModal && (
        <ImportWatchlistModal
          onClose={() => setShowImportModal(false)}
          onSuccess={() => refetch()}
        />
      )}

      {deletingWatchlist && (
        <ConfirmModal
          title="Delete Watchlist"
          message={`Are you sure you want to delete "${deletingWatchlist.name}"? This will remove all items in the watchlist and cannot be undone.`}
          confirmLabel="Delete"
          variant="danger"
          isLoading={deleteMutation.isPending}
          onConfirm={handleDeleteConfirm}
          onCancel={() => setDeletingWatchlist(null)}
        />
      )}
    </div>
  );
}
