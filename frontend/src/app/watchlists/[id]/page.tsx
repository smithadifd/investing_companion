'use client';

import { useState } from 'react';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import {
  ArrowLeft,
  Loader2,
  Plus,
  Settings,
  Download,
  Upload,
} from 'lucide-react';
import {
  useWatchlist,
  useUpdateWatchlist,
  useRemoveWatchlistItem,
  useExportWatchlist,
} from '@/lib/hooks/useWatchlist';
import { WatchlistItemRow } from '@/components/watchlist/WatchlistItemRow';
import { AddEquityModal } from '@/components/watchlist/AddEquityModal';
import { EditWatchlistModal } from '@/components/watchlist/EditWatchlistModal';
import { EditItemModal } from '@/components/watchlist/EditItemModal';
import { ConfirmModal } from '@/components/ui/ConfirmModal';
import type { WatchlistItem } from '@/lib/api/types';

export default function WatchlistDetailPage() {
  const params = useParams();
  const id = parseInt(params.id as string, 10);

  const [showAddModal, setShowAddModal] = useState(false);
  const [showEditModal, setShowEditModal] = useState(false);
  const [editingItem, setEditingItem] = useState<WatchlistItem | null>(null);
  const [removingItem, setRemovingItem] = useState<WatchlistItem | null>(null);

  const { data: watchlist, isLoading, error } = useWatchlist(id);
  const updateMutation = useUpdateWatchlist();
  const removeMutation = useRemoveWatchlistItem();
  const exportMutation = useExportWatchlist();

  const handleRemoveItem = async () => {
    if (!removingItem) return;
    await removeMutation.mutateAsync({ watchlistId: id, itemId: removingItem.id });
    setRemovingItem(null);
  };

  const handleExport = async () => {
    try {
      const data = await exportMutation.mutateAsync(id);
      const blob = new Blob([JSON.stringify(data, null, 2)], {
        type: 'application/json',
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${watchlist?.name || 'watchlist'}.json`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (error) {
      console.error('Export failed:', error);
    }
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-[calc(100vh-4rem)] bg-background">
        <div className="flex flex-col items-center gap-4">
          <Loader2 className="h-8 w-8 animate-spin text-blue-500" />
          <span className="text-muted-foreground">Loading watchlist...</span>
        </div>
      </div>
    );
  }

  if (error || !watchlist) {
    return (
      <div className="flex items-center justify-center min-h-[calc(100vh-4rem)] bg-background">
        <div className="text-center">
          <h1 className="text-2xl font-bold text-foreground">
            Watchlist Not Found
          </h1>
          <p className="text-muted-foreground mt-2">
            This watchlist does not exist or was deleted.
          </p>
          <Link
            href="/watchlists"
            className="inline-flex items-center gap-2 mt-4 text-blue-500 hover:text-blue-400"
          >
            <ArrowLeft className="h-4 w-4" />
            Back to Watchlists
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-[calc(100vh-4rem)] bg-background">
      <div className="max-w-6xl mx-auto px-4 sm:px-6 py-8">
        {/* Back link */}
        <Link
          href="/watchlists"
          className="inline-flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground mb-6 transition-colors"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to Watchlists
        </Link>

        {/* Header */}
        <div className="bg-card border border-border rounded-xl shadow-sm p-6 mb-6">
          <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
            <div className="flex-1">
              <div className="flex items-center gap-2">
                <h1 className="text-2xl font-bold text-foreground">
                  {watchlist.name}
                </h1>
                {watchlist.is_default && (
                  <span className="px-2 py-0.5 text-xs font-medium bg-blue-500/10 text-blue-500 rounded-full">
                    Default
                  </span>
                )}
              </div>
              {watchlist.description && (
                <p className="text-muted-foreground mt-2">
                  {watchlist.description}
                </p>
              )}
              <p className="text-sm text-muted-foreground mt-2">
                {watchlist.items.length}{' '}
                {watchlist.items.length === 1 ? 'equity' : 'equities'}
              </p>
            </div>

            <div className="flex items-center gap-2">
              <button
                onClick={() => setShowAddModal(true)}
                className="flex items-center gap-2 px-4 py-2 bg-blue-500 hover:bg-blue-600 text-white rounded-lg font-medium transition-colors"
              >
                <Plus className="h-4 w-4" />
                <span className="hidden sm:inline">Add Equity</span>
              </button>
              <button
                onClick={handleExport}
                disabled={exportMutation.isPending}
                className="p-2 text-muted-foreground hover:text-foreground hover:bg-muted rounded-lg transition-colors"
                title="Export watchlist"
              >
                {exportMutation.isPending ? (
                  <Loader2 className="h-5 w-5 animate-spin" />
                ) : (
                  <Download className="h-5 w-5" />
                )}
              </button>
              <button
                onClick={() => setShowEditModal(true)}
                className="p-2 text-muted-foreground hover:text-foreground hover:bg-muted rounded-lg transition-colors"
                title="Edit watchlist"
              >
                <Settings className="h-5 w-5" />
              </button>
            </div>
          </div>
        </div>

        {/* Items */}
        {watchlist.items.length === 0 ? (
          <div className="bg-card border border-border rounded-xl shadow-sm p-12 text-center">
            <p className="text-muted-foreground mb-4">
              This watchlist is empty. Add equities to start tracking.
            </p>
            <button
              onClick={() => setShowAddModal(true)}
              className="inline-flex items-center gap-2 px-4 py-2 bg-blue-500 hover:bg-blue-600 text-white rounded-lg font-medium transition-colors"
            >
              <Plus className="h-4 w-4" />
              Add Equity
            </button>
          </div>
        ) : (
          <div className="bg-card border border-border rounded-xl shadow-sm overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="border-b border-border bg-muted/50">
                    <th className="text-left p-4 font-medium text-muted-foreground">
                      Symbol
                    </th>
                    <th className="text-right p-4 font-medium text-muted-foreground">
                      Price
                    </th>
                    <th className="text-right p-4 font-medium text-muted-foreground">
                      Change
                    </th>
                    <th className="text-right p-4 font-medium text-muted-foreground hidden sm:table-cell">
                      Target
                    </th>
                    <th className="text-left p-4 font-medium text-muted-foreground hidden md:table-cell">
                      Notes
                    </th>
                    <th className="p-4 w-20"></th>
                  </tr>
                </thead>
                <tbody>
                  {watchlist.items.map((item) => (
                    <WatchlistItemRow
                      key={item.id}
                      item={item}
                      onEdit={() => setEditingItem(item)}
                      onRemove={() => setRemovingItem(item)}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>

      {/* Modals */}
      {showAddModal && (
        <AddEquityModal
          watchlistId={id}
          onClose={() => setShowAddModal(false)}
        />
      )}

      {showEditModal && (
        <EditWatchlistModal
          watchlist={watchlist}
          onClose={() => setShowEditModal(false)}
        />
      )}

      {editingItem && (
        <EditItemModal
          watchlistId={id}
          item={editingItem}
          onClose={() => setEditingItem(null)}
        />
      )}

      {removingItem && (
        <ConfirmModal
          title="Remove Equity"
          message={`Are you sure you want to remove ${removingItem.equity.symbol} from this watchlist?`}
          confirmLabel="Remove"
          variant="danger"
          isLoading={removeMutation.isPending}
          onConfirm={handleRemoveItem}
          onCancel={() => setRemovingItem(null)}
        />
      )}
    </div>
  );
}
