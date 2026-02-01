'use client';

import { useState, useMemo } from 'react';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import {
  ArrowLeft,
  Loader2,
  Plus,
  Settings,
  Download,
} from 'lucide-react';
import {
  useWatchlist,
  useRemoveWatchlistItem,
  useExportWatchlist,
} from '@/lib/hooks/useWatchlist';
import { WatchlistItemRow } from '@/components/watchlist/WatchlistItemRow';
import { AddEquityModal } from '@/components/watchlist/AddEquityModal';
import { EditWatchlistModal } from '@/components/watchlist/EditWatchlistModal';
import { EditItemModal } from '@/components/watchlist/EditItemModal';
import { ConfirmModal } from '@/components/ui/ConfirmModal';
import { SortableHeader, type SortConfig } from '@/components/ui/SortableHeader';
import type { WatchlistItem } from '@/lib/api/types';

type SortKey = 'symbol' | 'price' | 'change' | 'target';

function parseNumber(value: number | string | null | undefined): number {
  if (value === null || value === undefined) return 0;
  return typeof value === 'string' ? parseFloat(value) : value;
}

export default function WatchlistDetailPage() {
  const params = useParams();
  const id = parseInt(params.id as string, 10);

  const [showAddModal, setShowAddModal] = useState(false);
  const [showEditModal, setShowEditModal] = useState(false);
  const [editingItem, setEditingItem] = useState<WatchlistItem | null>(null);
  const [removingItem, setRemovingItem] = useState<WatchlistItem | null>(null);
  const [sortConfig, setSortConfig] = useState<SortConfig<SortKey>>({
    key: 'change',
    direction: 'desc',
  });

  const { data: watchlist, isLoading, error } = useWatchlist(id);
  const removeMutation = useRemoveWatchlistItem();
  const exportMutation = useExportWatchlist();

  const handleSort = (key: SortKey) => {
    setSortConfig((current) => {
      if (current.key !== key) {
        return { key, direction: 'desc' };
      }
      if (current.direction === 'desc') {
        return { key, direction: 'asc' };
      }
      if (current.direction === 'asc') {
        return { key, direction: null };
      }
      return { key, direction: 'desc' };
    });
  };

  const sortedItems = useMemo(() => {
    if (!watchlist?.items) return [];

    const items = [...watchlist.items];

    if (!sortConfig.direction) {
      // Default: sort by absolute change (biggest movers first)
      return items.sort((a, b) => {
        const aChange = Math.abs(parseNumber(a.quote?.change_percent));
        const bChange = Math.abs(parseNumber(b.quote?.change_percent));
        return bChange - aChange;
      });
    }

    return items.sort((a, b) => {
      let aVal: number | string = 0;
      let bVal: number | string = 0;

      switch (sortConfig.key) {
        case 'symbol':
          aVal = a.equity.symbol;
          bVal = b.equity.symbol;
          break;
        case 'price':
          aVal = parseNumber(a.quote?.price);
          bVal = parseNumber(b.quote?.price);
          break;
        case 'change':
          aVal = parseNumber(a.quote?.change_percent);
          bVal = parseNumber(b.quote?.change_percent);
          break;
        case 'target':
          aVal = parseNumber(a.target_price);
          bVal = parseNumber(b.target_price);
          break;
      }

      if (typeof aVal === 'string' && typeof bVal === 'string') {
        const comparison = aVal.localeCompare(bVal);
        return sortConfig.direction === 'asc' ? comparison : -comparison;
      }

      const numA = typeof aVal === 'number' ? aVal : 0;
      const numB = typeof bVal === 'number' ? bVal : 0;
      return sortConfig.direction === 'asc' ? numA - numB : numB - numA;
    });
  }, [watchlist?.items, sortConfig]);

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
      <div className="flex items-center justify-center min-h-[calc(100vh-4rem)] bg-neutral-50 dark:bg-neutral-900">
        <div className="flex flex-col items-center gap-4">
          <Loader2 className="h-8 w-8 animate-spin text-blue-500" />
          <span className="text-neutral-500 dark:text-neutral-400">Loading watchlist...</span>
        </div>
      </div>
    );
  }

  if (error || !watchlist) {
    return (
      <div className="flex items-center justify-center min-h-[calc(100vh-4rem)] bg-neutral-50 dark:bg-neutral-900">
        <div className="text-center">
          <h1 className="text-2xl font-bold text-neutral-900 dark:text-neutral-50">
            Watchlist Not Found
          </h1>
          <p className="text-neutral-500 dark:text-neutral-400 mt-2">
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
    <div className="min-h-[calc(100vh-4rem)] bg-neutral-50 dark:bg-neutral-900">
      <div className="max-w-6xl mx-auto px-4 sm:px-6 py-6 sm:py-8">
        {/* Back link */}
        <Link
          href="/watchlists"
          className="inline-flex items-center gap-2 text-sm text-neutral-500 dark:text-neutral-400 hover:text-neutral-900 dark:hover:text-neutral-50 mb-6 transition-colors"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to Watchlists
        </Link>

        {/* Header */}
        <div className="bg-white dark:bg-neutral-800 border border-neutral-200 dark:border-neutral-700 rounded-xl p-6 mb-6">
          <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
            <div className="flex-1">
              <div className="flex items-center gap-2">
                <h1 className="text-2xl font-bold text-neutral-900 dark:text-neutral-50">
                  {watchlist.name}
                </h1>
                {watchlist.is_default && (
                  <span className="px-2 py-0.5 text-xs font-medium bg-blue-500/10 text-blue-600 dark:text-blue-400 rounded-full">
                    Default
                  </span>
                )}
              </div>
              {watchlist.description && (
                <p className="text-neutral-500 dark:text-neutral-400 mt-2">
                  {watchlist.description}
                </p>
              )}
              <p className="text-sm text-neutral-500 dark:text-neutral-400 mt-2">
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
                className="p-2 text-neutral-500 dark:text-neutral-400 hover:text-neutral-900 dark:hover:text-neutral-50 hover:bg-neutral-100 dark:hover:bg-neutral-700 rounded-lg transition-colors"
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
                className="p-2 text-neutral-500 dark:text-neutral-400 hover:text-neutral-900 dark:hover:text-neutral-50 hover:bg-neutral-100 dark:hover:bg-neutral-700 rounded-lg transition-colors"
                title="Edit watchlist"
              >
                <Settings className="h-5 w-5" />
              </button>
            </div>
          </div>
        </div>

        {/* Items */}
        {watchlist.items.length === 0 ? (
          <div className="bg-white dark:bg-neutral-800 border border-neutral-200 dark:border-neutral-700 rounded-xl p-12 text-center">
            <p className="text-neutral-500 dark:text-neutral-400 mb-4">
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
          <div className="bg-white dark:bg-neutral-800 border border-neutral-200 dark:border-neutral-700 rounded-xl overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="border-b border-neutral-200 dark:border-neutral-700 bg-neutral-50 dark:bg-neutral-800/50">
                    <th className="text-left p-4">
                      <SortableHeader
                        label="Symbol"
                        sortKey="symbol"
                        currentSort={sortConfig}
                        onSort={handleSort}
                        align="left"
                      />
                    </th>
                    <th className="text-right p-4">
                      <SortableHeader
                        label="Price"
                        sortKey="price"
                        currentSort={sortConfig}
                        onSort={handleSort}
                        align="right"
                        className="w-full"
                      />
                    </th>
                    <th className="text-right p-4">
                      <SortableHeader
                        label="Change"
                        sortKey="change"
                        currentSort={sortConfig}
                        onSort={handleSort}
                        align="right"
                        className="w-full"
                      />
                    </th>
                    <th className="text-right p-4 hidden sm:table-cell">
                      <SortableHeader
                        label="Target"
                        sortKey="target"
                        currentSort={sortConfig}
                        onSort={handleSort}
                        align="right"
                        className="w-full"
                      />
                    </th>
                    <th className="text-left p-4 font-medium text-neutral-500 dark:text-neutral-400 text-sm hidden md:table-cell">
                      Notes
                    </th>
                    <th className="p-4 w-20"></th>
                  </tr>
                </thead>
                <tbody>
                  {sortedItems.map((item) => (
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
