'use client';

import { useState, useEffect } from 'react';
import { Star, Plus, Trash2, TrendingUp, TrendingDown } from 'lucide-react';
import {
  useRatios,
  useRatioQuotes,
  useToggleRatioFavorite,
  useDeleteRatio,
  useCreateRatio,
  useInitializeRatios,
} from '@/lib/hooks/useRatio';
import type { Ratio, RatioQuote, RatioCreate } from '@/lib/api/types';
import { RatioChart } from '@/components/ratio/RatioChart';
import { ConfirmModal } from '@/components/ui/ConfirmModal';

// Helper to convert string/number to number
function toNumber(value: number | string | null | undefined): number {
  if (value === null || value === undefined) return 0;
  return typeof value === 'string' ? parseFloat(value) : value;
}

// Format ratio value
function formatRatioValue(value: number | string | null): string {
  const num = toNumber(value);
  if (num >= 100) return num.toFixed(1);
  if (num >= 10) return num.toFixed(2);
  return num.toFixed(4);
}

// Format percent
function formatPercent(value: number | string | null): string {
  if (value === null) return '-';
  const num = toNumber(value);
  const sign = num >= 0 ? '+' : '';
  return `${sign}${num.toFixed(2)}%`;
}

// Category colors
const CATEGORY_COLORS: Record<string, string> = {
  commodity: 'bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-400',
  equity: 'bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-400',
  macro: 'bg-purple-100 text-purple-800 dark:bg-purple-900/30 dark:text-purple-400',
  crypto: 'bg-orange-100 text-orange-800 dark:bg-orange-900/30 dark:text-orange-400',
  custom: 'bg-neutral-100 text-neutral-800 dark:bg-neutral-700 dark:text-neutral-300',
};

function RatioCard({
  ratio,
  quote,
  onToggleFavorite,
  onDelete,
  onSelect,
  isSelected,
}: {
  ratio: Ratio;
  quote?: RatioQuote;
  onToggleFavorite: () => void;
  onDelete: () => void;
  onSelect: () => void;
  isSelected: boolean;
}) {
  const change = toNumber(quote?.change_percent_1d);

  return (
    <div
      className={`bg-white dark:bg-neutral-800 rounded-lg p-4 border transition-all cursor-pointer ${
        isSelected
          ? 'border-blue-500 ring-2 ring-blue-500/20'
          : 'border-neutral-200 dark:border-neutral-700 hover:border-neutral-300 dark:hover:border-neutral-600'
      }`}
      onClick={onSelect}
    >
      <div className="flex justify-between items-start mb-2">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <h3 className="font-semibold text-neutral-900 dark:text-neutral-50 truncate">
              {ratio.name}
            </h3>
            <span className={`text-xs px-2 py-0.5 rounded-full ${CATEGORY_COLORS[ratio.category] || CATEGORY_COLORS.custom}`}>
              {ratio.category}
            </span>
          </div>
          <p className="text-xs text-neutral-500 mt-0.5">
            {ratio.numerator_symbol} / {ratio.denominator_symbol}
          </p>
        </div>
        <div className="flex items-center gap-1 ml-2">
          <button
            onClick={(e) => {
              e.stopPropagation();
              onToggleFavorite();
            }}
            className={`p-1.5 rounded-lg transition-colors ${
              ratio.is_favorite
                ? 'text-amber-500 hover:bg-amber-100 dark:hover:bg-amber-900/30'
                : 'text-neutral-400 hover:bg-neutral-100 dark:hover:bg-neutral-700'
            }`}
          >
            <Star className={`h-4 w-4 ${ratio.is_favorite ? 'fill-current' : ''}`} />
          </button>
          {!ratio.is_system && (
            <button
              onClick={(e) => {
                e.stopPropagation();
                onDelete();
              }}
              className="p-1.5 rounded-lg text-neutral-400 hover:text-red-500 hover:bg-red-100 dark:hover:bg-red-900/30 transition-colors"
            >
              <Trash2 className="h-4 w-4" />
            </button>
          )}
        </div>
      </div>

      {quote ? (
        <div className="flex items-baseline justify-between">
          <span className="text-2xl font-bold text-neutral-900 dark:text-neutral-50">
            {formatRatioValue(quote.current_value)}
          </span>
          <div className={`flex items-center gap-1 ${
            change >= 0
              ? 'text-emerald-600 dark:text-emerald-400'
              : 'text-red-600 dark:text-red-400'
          }`}>
            {change >= 0 ? (
              <TrendingUp className="h-4 w-4" />
            ) : (
              <TrendingDown className="h-4 w-4" />
            )}
            <span className="text-sm font-medium">
              {formatPercent(quote.change_percent_1d)}
            </span>
          </div>
        </div>
      ) : (
        <div className="animate-pulse h-8 bg-neutral-200 dark:bg-neutral-700 rounded"></div>
      )}

      {ratio.description && (
        <p className="text-xs text-neutral-500 mt-2 line-clamp-2">
          {ratio.description}
        </p>
      )}
    </div>
  );
}

function CreateRatioModal({
  isOpen,
  onClose,
  onCreate,
}: {
  isOpen: boolean;
  onClose: () => void;
  onCreate: (data: RatioCreate) => void;
}) {
  const [name, setName] = useState('');
  const [numerator, setNumerator] = useState('');
  const [denominator, setDenominator] = useState('');
  const [description, setDescription] = useState('');
  const [category, setCategory] = useState('custom');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!name || !numerator || !denominator) return;

    onCreate({
      name,
      numerator_symbol: numerator.toUpperCase(),
      denominator_symbol: denominator.toUpperCase(),
      description: description || undefined,
      category,
    });

    setName('');
    setNumerator('');
    setDenominator('');
    setDescription('');
    setCategory('custom');
    onClose();
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-white dark:bg-neutral-800 rounded-xl p-6 w-full max-w-md mx-4 shadow-xl">
        <h2 className="text-xl font-semibold text-neutral-900 dark:text-neutral-50 mb-4">
          Create Custom Ratio
        </h2>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
              Name
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g., Gold/Silver"
              className="w-full px-3 py-2 border border-neutral-300 dark:border-neutral-600 rounded-lg bg-white dark:bg-neutral-700 text-neutral-900 dark:text-neutral-50 focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              required
            />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
                Numerator Symbol
              </label>
              <input
                type="text"
                value={numerator}
                onChange={(e) => setNumerator(e.target.value)}
                placeholder="e.g., GC=F"
                className="w-full px-3 py-2 border border-neutral-300 dark:border-neutral-600 rounded-lg bg-white dark:bg-neutral-700 text-neutral-900 dark:text-neutral-50 focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                required
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
                Denominator Symbol
              </label>
              <input
                type="text"
                value={denominator}
                onChange={(e) => setDenominator(e.target.value)}
                placeholder="e.g., SI=F"
                className="w-full px-3 py-2 border border-neutral-300 dark:border-neutral-600 rounded-lg bg-white dark:bg-neutral-700 text-neutral-900 dark:text-neutral-50 focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                required
              />
            </div>
          </div>
          <div>
            <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
              Category
            </label>
            <select
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              className="w-full px-3 py-2 border border-neutral-300 dark:border-neutral-600 rounded-lg bg-white dark:bg-neutral-700 text-neutral-900 dark:text-neutral-50 focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            >
              <option value="commodity">Commodity</option>
              <option value="equity">Equity</option>
              <option value="macro">Macro</option>
              <option value="crypto">Crypto</option>
              <option value="custom">Custom</option>
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
              Description (optional)
            </label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="What does this ratio indicate?"
              rows={2}
              className="w-full px-3 py-2 border border-neutral-300 dark:border-neutral-600 rounded-lg bg-white dark:bg-neutral-700 text-neutral-900 dark:text-neutral-50 focus:ring-2 focus:ring-blue-500 focus:border-transparent resize-none"
            />
          </div>
          <div className="flex justify-end gap-3 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-neutral-600 dark:text-neutral-400 hover:bg-neutral-100 dark:hover:bg-neutral-700 rounded-lg transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
            >
              Create
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

export default function RatiosPage() {
  const [selectedRatioId, setSelectedRatioId] = useState<number | null>(null);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [deleteRatioId, setDeleteRatioId] = useState<number | null>(null);
  const [categoryFilter, setCategoryFilter] = useState<string | undefined>();

  const { data: ratios, isLoading: ratiosLoading } = useRatios(false, categoryFilter);
  const { data: quotes } = useRatioQuotes();
  const toggleFavorite = useToggleRatioFavorite();
  const deleteRatio = useDeleteRatio();
  const createRatio = useCreateRatio();
  const initializeRatios = useInitializeRatios();

  // Initialize system ratios on first load if no ratios exist
  useEffect(() => {
    if (ratios && ratios.length === 0) {
      initializeRatios.mutate();
    }
  }, [ratios]);

  // Auto-select first ratio
  useEffect(() => {
    if (ratios && ratios.length > 0 && !selectedRatioId) {
      setSelectedRatioId(ratios[0].id);
    }
  }, [ratios, selectedRatioId]);

  const quoteMap = new Map(quotes?.map((q) => [q.id, q]));
  const selectedRatio = ratios?.find((r) => r.id === selectedRatioId);

  // Group ratios: favorites first, then by category
  const favoriteRatios = ratios?.filter((r) => r.is_favorite) || [];
  const otherRatios = ratios?.filter((r) => !r.is_favorite) || [];

  const categories = ['all', 'commodity', 'equity', 'macro', 'crypto', 'custom'];

  if (ratiosLoading) {
    return (
      <div className="min-h-[calc(100vh-4rem)] bg-neutral-50 dark:bg-neutral-900">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 py-8">
          <div className="animate-pulse space-y-6">
            <div className="h-8 w-32 bg-neutral-200 dark:bg-neutral-700 rounded"></div>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              {[...Array(6)].map((_, i) => (
                <div key={i} className="h-32 bg-neutral-200 dark:bg-neutral-700 rounded-lg"></div>
              ))}
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-[calc(100vh-4rem)] bg-neutral-50 dark:bg-neutral-900">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 py-8">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 mb-6">
          <div>
            <h1 className="text-2xl font-bold text-neutral-900 dark:text-neutral-50">
              Ratios
            </h1>
            <p className="text-sm text-neutral-500">
              Track and compare asset ratios
            </p>
          </div>
          <button
            onClick={() => setShowCreateModal(true)}
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
          >
            <Plus className="h-4 w-4" />
            New Ratio
          </button>
        </div>

        {/* Category Filter */}
        <div className="flex gap-2 mb-6 overflow-x-auto pb-2">
          {categories.map((cat) => (
            <button
              key={cat}
              onClick={() => setCategoryFilter(cat === 'all' ? undefined : cat)}
              className={`px-3 py-1.5 rounded-full text-sm font-medium transition-colors whitespace-nowrap ${
                (cat === 'all' && !categoryFilter) || categoryFilter === cat
                  ? 'bg-blue-600 text-white'
                  : 'bg-neutral-200 dark:bg-neutral-700 text-neutral-700 dark:text-neutral-300 hover:bg-neutral-300 dark:hover:bg-neutral-600'
              }`}
            >
              {cat.charAt(0).toUpperCase() + cat.slice(1)}
            </button>
          ))}
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Ratio List */}
          <div className="lg:col-span-1 space-y-4">
            {favoriteRatios.length > 0 && (
              <div>
                <h2 className="text-sm font-medium text-neutral-500 mb-2 flex items-center gap-1">
                  <Star className="h-4 w-4 text-amber-500 fill-amber-500" />
                  Favorites
                </h2>
                <div className="space-y-3">
                  {favoriteRatios.map((ratio) => (
                    <RatioCard
                      key={ratio.id}
                      ratio={ratio}
                      quote={quoteMap.get(ratio.id)}
                      onToggleFavorite={() =>
                        toggleFavorite.mutate({ id: ratio.id, isFavorite: false })
                      }
                      onDelete={() => setDeleteRatioId(ratio.id)}
                      onSelect={() => setSelectedRatioId(ratio.id)}
                      isSelected={selectedRatioId === ratio.id}
                    />
                  ))}
                </div>
              </div>
            )}

            {otherRatios.length > 0 && (
              <div>
                {favoriteRatios.length > 0 && (
                  <h2 className="text-sm font-medium text-neutral-500 mb-2">
                    All Ratios
                  </h2>
                )}
                <div className="space-y-3">
                  {otherRatios.map((ratio) => (
                    <RatioCard
                      key={ratio.id}
                      ratio={ratio}
                      quote={quoteMap.get(ratio.id)}
                      onToggleFavorite={() =>
                        toggleFavorite.mutate({ id: ratio.id, isFavorite: true })
                      }
                      onDelete={() => setDeleteRatioId(ratio.id)}
                      onSelect={() => setSelectedRatioId(ratio.id)}
                      isSelected={selectedRatioId === ratio.id}
                    />
                  ))}
                </div>
              </div>
            )}

            {(!ratios || ratios.length === 0) && (
              <div className="text-center py-8">
                <p className="text-neutral-500 mb-4">No ratios found</p>
                <button
                  onClick={() => initializeRatios.mutate()}
                  className="text-blue-600 hover:text-blue-700 text-sm font-medium"
                >
                  Initialize system ratios
                </button>
              </div>
            )}
          </div>

          {/* Chart */}
          <div className="lg:col-span-2">
            {selectedRatio ? (
              <RatioChart ratio={selectedRatio} />
            ) : (
              <div className="bg-white dark:bg-neutral-800 rounded-lg border border-neutral-200 dark:border-neutral-700 p-8 text-center">
                <p className="text-neutral-500">Select a ratio to view its chart</p>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Create Modal */}
      <CreateRatioModal
        isOpen={showCreateModal}
        onClose={() => setShowCreateModal(false)}
        onCreate={(data) => createRatio.mutate(data)}
      />

      {/* Delete Confirmation */}
      {deleteRatioId !== null && (
        <ConfirmModal
          title="Delete Ratio"
          message="Are you sure you want to delete this ratio? This action cannot be undone."
          confirmLabel="Delete"
          onConfirm={() => {
            if (deleteRatioId) {
              deleteRatio.mutate(deleteRatioId);
              if (selectedRatioId === deleteRatioId) {
                setSelectedRatioId(null);
              }
            }
            setDeleteRatioId(null);
          }}
          onCancel={() => setDeleteRatioId(null)}
          variant="danger"
        />
      )}
    </div>
  );
}
