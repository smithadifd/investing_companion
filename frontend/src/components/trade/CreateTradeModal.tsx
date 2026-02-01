'use client';

import { useState } from 'react';
import { X, Search, Loader2 } from 'lucide-react';
import { useCreateTrade } from '@/lib/hooks/useTrade';
import { api } from '@/lib/api/client';
import type { TradeType, TradeCreate, EquitySearchResult } from '@/lib/api/types';

interface CreateTradeModalProps {
  isOpen: boolean;
  onClose: () => void;
  prefillSymbol?: string;
}

const TRADE_TYPES: { value: TradeType; label: string; description: string }[] = [
  { value: 'buy', label: 'Buy', description: 'Purchase shares (long position)' },
  { value: 'sell', label: 'Sell', description: 'Sell shares you own' },
  { value: 'short', label: 'Short', description: 'Borrow and sell shares' },
  { value: 'cover', label: 'Cover', description: 'Buy back shorted shares' },
];

export function CreateTradeModal({
  isOpen,
  onClose,
  prefillSymbol,
}: CreateTradeModalProps) {
  const [tradeType, setTradeType] = useState<TradeType>('buy');
  const [equitySymbol, setEquitySymbol] = useState(prefillSymbol || '');
  const [quantity, setQuantity] = useState('');
  const [price, setPrice] = useState('');
  const [fees, setFees] = useState('0');
  const [executedAt, setExecutedAt] = useState(
    new Date().toISOString().slice(0, 16)
  );
  const [notes, setNotes] = useState('');

  // Search state
  const [searchQuery, setSearchQuery] = useState(prefillSymbol || '');
  const [searchResults, setSearchResults] = useState<EquitySearchResult[]>([]);
  const [isSearching, setIsSearching] = useState(false);
  const [showResults, setShowResults] = useState(false);

  const createTrade = useCreateTrade();

  const handleSearch = async (query: string) => {
    setSearchQuery(query);
    setEquitySymbol(query.toUpperCase());

    if (query.length < 1) {
      setSearchResults([]);
      setShowResults(false);
      return;
    }

    setIsSearching(true);
    try {
      const results = await api.searchEquities(query, 10);
      setSearchResults(results);
      setShowResults(true);
    } catch (error) {
      console.error('Search failed:', error);
    } finally {
      setIsSearching(false);
    }
  };

  const handleSelectEquity = (equity: EquitySearchResult) => {
    setEquitySymbol(equity.symbol);
    setSearchQuery(equity.symbol);
    setShowResults(false);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!equitySymbol || !quantity || !price) return;

    const data: TradeCreate = {
      symbol: equitySymbol.toUpperCase(),
      trade_type: tradeType,
      quantity: parseFloat(quantity),
      price: parseFloat(price),
      fees: parseFloat(fees) || 0,
      executed_at: new Date(executedAt).toISOString(),
      notes: notes || undefined,
    };

    try {
      await createTrade.mutateAsync(data);
      handleClose();
    } catch (error) {
      console.error('Failed to create trade:', error);
    }
  };

  const handleClose = () => {
    setTradeType('buy');
    setEquitySymbol(prefillSymbol || '');
    setSearchQuery(prefillSymbol || '');
    setQuantity('');
    setPrice('');
    setFees('0');
    setExecutedAt(new Date().toISOString().slice(0, 16));
    setNotes('');
    setSearchResults([]);
    setShowResults(false);
    onClose();
  };

  // Calculate total value
  const totalValue =
    quantity && price ? parseFloat(quantity) * parseFloat(price) : 0;
  const totalWithFees = totalValue + (parseFloat(fees) || 0);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white dark:bg-neutral-800 rounded-xl w-full max-w-lg shadow-xl max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between p-4 border-b border-neutral-200 dark:border-neutral-700 sticky top-0 bg-white dark:bg-neutral-800">
          <h2 className="text-xl font-semibold text-neutral-900 dark:text-neutral-50">
            Log Trade
          </h2>
          <button
            onClick={handleClose}
            className="p-1 text-neutral-500 hover:text-neutral-900 dark:text-neutral-400 dark:hover:text-neutral-50 rounded-lg transition-colors"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-4 space-y-4">
          {/* Trade Type */}
          <div>
            <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-2">
              Trade Type
            </label>
            <div className="grid grid-cols-4 gap-2">
              {TRADE_TYPES.map((type) => (
                <button
                  key={type.value}
                  type="button"
                  onClick={() => setTradeType(type.value)}
                  className={`py-2 px-3 rounded-lg text-sm font-medium transition-colors ${
                    tradeType === type.value
                      ? type.value === 'buy' || type.value === 'cover'
                        ? 'bg-emerald-600 text-white'
                        : 'bg-red-600 text-white'
                      : 'bg-neutral-100 dark:bg-neutral-700 text-neutral-700 dark:text-neutral-300 hover:bg-neutral-200 dark:hover:bg-neutral-600'
                  }`}
                >
                  {type.label}
                </button>
              ))}
            </div>
            <p className="text-xs text-neutral-500 mt-1">
              {TRADE_TYPES.find((t) => t.value === tradeType)?.description}
            </p>
          </div>

          {/* Symbol Search */}
          <div className="relative">
            <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
              Symbol
            </label>
            <div className="relative">
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => handleSearch(e.target.value)}
                onFocus={() => searchResults.length > 0 && setShowResults(true)}
                placeholder="Search symbol or name..."
                className="w-full px-3 py-2 pl-10 border border-neutral-300 dark:border-neutral-600 rounded-lg bg-white dark:bg-neutral-700 text-neutral-900 dark:text-neutral-50 focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                required
              />
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-neutral-400" />
              {isSearching && (
                <Loader2 className="absolute right-3 top-1/2 -translate-y-1/2 h-4 w-4 text-neutral-400 animate-spin" />
              )}
            </div>

            {/* Search Results Dropdown */}
            {showResults && searchResults.length > 0 && (
              <div className="absolute z-10 w-full mt-1 bg-white dark:bg-neutral-700 border border-neutral-200 dark:border-neutral-600 rounded-lg shadow-lg max-h-48 overflow-y-auto">
                {searchResults.map((result) => (
                  <button
                    key={result.symbol}
                    type="button"
                    onClick={() => handleSelectEquity(result)}
                    className="w-full px-3 py-2 text-left hover:bg-neutral-100 dark:hover:bg-neutral-600 transition-colors"
                  >
                    <span className="font-medium text-neutral-900 dark:text-neutral-50">
                      {result.symbol}
                    </span>
                    <span className="text-sm text-neutral-500 ml-2 truncate">
                      {result.name}
                    </span>
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Quantity and Price */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
                Quantity
              </label>
              <input
                type="number"
                step="any"
                min="0"
                value={quantity}
                onChange={(e) => setQuantity(e.target.value)}
                placeholder="100"
                className="w-full px-3 py-2 border border-neutral-300 dark:border-neutral-600 rounded-lg bg-white dark:bg-neutral-700 text-neutral-900 dark:text-neutral-50 focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                required
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
                Price per Share
              </label>
              <input
                type="number"
                step="0.0001"
                min="0"
                value={price}
                onChange={(e) => setPrice(e.target.value)}
                placeholder="50.00"
                className="w-full px-3 py-2 border border-neutral-300 dark:border-neutral-600 rounded-lg bg-white dark:bg-neutral-700 text-neutral-900 dark:text-neutral-50 focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                required
              />
            </div>
          </div>

          {/* Fees */}
          <div>
            <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
              Fees/Commission
            </label>
            <input
              type="number"
              step="0.01"
              min="0"
              value={fees}
              onChange={(e) => setFees(e.target.value)}
              placeholder="0.00"
              className="w-full px-3 py-2 border border-neutral-300 dark:border-neutral-600 rounded-lg bg-white dark:bg-neutral-700 text-neutral-900 dark:text-neutral-50 focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            />
          </div>

          {/* Date/Time */}
          <div>
            <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
              Executed At
            </label>
            <input
              type="datetime-local"
              value={executedAt}
              onChange={(e) => setExecutedAt(e.target.value)}
              className="w-full px-3 py-2 border border-neutral-300 dark:border-neutral-600 rounded-lg bg-white dark:bg-neutral-700 text-neutral-900 dark:text-neutral-50 focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              required
            />
          </div>

          {/* Notes */}
          <div>
            <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
              Notes (optional)
            </label>
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Add trade notes, thesis, or rationale..."
              rows={2}
              className="w-full px-3 py-2 border border-neutral-300 dark:border-neutral-600 rounded-lg bg-white dark:bg-neutral-700 text-neutral-900 dark:text-neutral-50 focus:ring-2 focus:ring-blue-500 focus:border-transparent resize-none"
            />
          </div>

          {/* Total Summary */}
          {totalValue > 0 && (
            <div className="p-3 bg-neutral-50 dark:bg-neutral-700/50 rounded-lg">
              <div className="flex justify-between text-sm">
                <span className="text-neutral-500">Trade Value:</span>
                <span className="font-medium text-neutral-900 dark:text-neutral-50">
                  ${totalValue.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                </span>
              </div>
              {parseFloat(fees) > 0 && (
                <>
                  <div className="flex justify-between text-sm">
                    <span className="text-neutral-500">Fees:</span>
                    <span className="text-neutral-900 dark:text-neutral-50">
                      ${parseFloat(fees).toFixed(2)}
                    </span>
                  </div>
                  <div className="flex justify-between text-sm font-semibold border-t border-neutral-200 dark:border-neutral-600 pt-1 mt-1">
                    <span className="text-neutral-700 dark:text-neutral-300">Total:</span>
                    <span className="text-neutral-900 dark:text-neutral-50">
                      ${totalWithFees.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                    </span>
                  </div>
                </>
              )}
            </div>
          )}

          {/* Submit */}
          <div className="flex justify-end gap-3 pt-2">
            <button
              type="button"
              onClick={handleClose}
              className="px-4 py-2 text-neutral-600 dark:text-neutral-400 hover:bg-neutral-100 dark:hover:bg-neutral-700 rounded-lg transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={createTrade.isPending}
              className={`flex items-center gap-2 px-4 py-2 text-white rounded-lg transition-colors disabled:opacity-50 ${
                tradeType === 'buy' || tradeType === 'cover'
                  ? 'bg-emerald-600 hover:bg-emerald-700'
                  : 'bg-red-600 hover:bg-red-700'
              }`}
            >
              {createTrade.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
              Log {tradeType.charAt(0).toUpperCase() + tradeType.slice(1)}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
