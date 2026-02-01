'use client';

import { useState } from 'react';
import { X, Loader2 } from 'lucide-react';
import { useUpdateTrade } from '@/lib/hooks/useTrade';
import type { Trade, TradeType, TradeUpdate } from '@/lib/api/types';

interface EditTradeModalProps {
  trade: Trade;
  onClose: () => void;
}

const TRADE_TYPES: { value: TradeType; label: string }[] = [
  { value: 'buy', label: 'Buy' },
  { value: 'sell', label: 'Sell' },
  { value: 'short', label: 'Short' },
  { value: 'cover', label: 'Cover' },
];

function toNumber(value: number | string | null | undefined): number {
  if (value === null || value === undefined) return 0;
  return typeof value === 'string' ? parseFloat(value) : value;
}

export function EditTradeModal({ trade, onClose }: EditTradeModalProps) {
  const [tradeType, setTradeType] = useState<TradeType>(trade.trade_type);
  const [quantity, setQuantity] = useState(toNumber(trade.quantity).toString());
  const [price, setPrice] = useState(toNumber(trade.price).toString());
  const [fees, setFees] = useState(toNumber(trade.fees).toString());
  const [executedAt, setExecutedAt] = useState(
    new Date(trade.executed_at).toISOString().slice(0, 16)
  );
  const [notes, setNotes] = useState(trade.notes || '');

  const updateTrade = useUpdateTrade();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    const data: TradeUpdate = {
      trade_type: tradeType,
      quantity: parseFloat(quantity),
      price: parseFloat(price),
      fees: parseFloat(fees) || 0,
      executed_at: new Date(executedAt).toISOString(),
      notes: notes || undefined,
    };

    try {
      await updateTrade.mutateAsync({ id: trade.id, data });
      onClose();
    } catch (error) {
      console.error('Failed to update trade:', error);
    }
  };

  // Calculate total value
  const totalValue =
    quantity && price ? parseFloat(quantity) * parseFloat(price) : 0;
  const totalWithFees = totalValue + (parseFloat(fees) || 0);

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white dark:bg-neutral-800 rounded-xl w-full max-w-lg shadow-xl max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between p-4 border-b border-neutral-200 dark:border-neutral-700 sticky top-0 bg-white dark:bg-neutral-800">
          <h2 className="text-xl font-semibold text-neutral-900 dark:text-neutral-50">
            Edit Trade
          </h2>
          <button
            onClick={onClose}
            className="p-1 text-neutral-500 hover:text-neutral-900 dark:text-neutral-400 dark:hover:text-neutral-50 rounded-lg transition-colors"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-4 space-y-4">
          {/* Symbol (read-only) */}
          <div>
            <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
              Symbol
            </label>
            <div className="px-3 py-2 bg-neutral-100 dark:bg-neutral-700 rounded-lg text-neutral-900 dark:text-neutral-50">
              <span className="font-semibold">{trade.equity.symbol}</span>
              <span className="text-neutral-500 ml-2">{trade.equity.name}</span>
            </div>
          </div>

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
              Notes
            </label>
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Add trade notes..."
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
              onClick={onClose}
              className="px-4 py-2 text-neutral-600 dark:text-neutral-400 hover:bg-neutral-100 dark:hover:bg-neutral-700 rounded-lg transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={updateTrade.isPending}
              className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors disabled:opacity-50"
            >
              {updateTrade.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
              Save Changes
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
