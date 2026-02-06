'use client';

import { useState, useEffect } from 'react';
import { X, Loader2, Zap } from 'lucide-react';
import { useCreateTrade } from '@/lib/hooks/useTrade';
import { Modal } from '@/components/ui/Modal';
import type { TradeType, TradeCreate } from '@/lib/api/types';

interface QuickTradeModalProps {
  symbol: string;
  tradeType: 'buy' | 'sell';
  suggestedPrice?: number;
  onClose: () => void;
}

export function QuickTradeModal({
  symbol,
  tradeType,
  suggestedPrice,
  onClose,
}: QuickTradeModalProps) {
  const [quantity, setQuantity] = useState('');
  const [price, setPrice] = useState(suggestedPrice?.toFixed(2) || '');

  const createTrade = useCreateTrade();

  // Update price if suggestedPrice changes
  useEffect(() => {
    if (suggestedPrice) {
      setPrice(suggestedPrice.toFixed(2));
    }
  }, [suggestedPrice]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!quantity || !price) return;

    const data: TradeCreate = {
      symbol: symbol.toUpperCase(),
      trade_type: tradeType as TradeType,
      quantity: parseFloat(quantity),
      price: parseFloat(price),
      fees: 0,
      executed_at: new Date().toISOString(),
    };

    try {
      await createTrade.mutateAsync(data);
      onClose();
    } catch (error) {
      console.error('Failed to create trade:', error);
    }
  };

  const totalValue = quantity && price ? parseFloat(quantity) * parseFloat(price) : 0;
  const isBuy = tradeType === 'buy';

  const headerContent = (
    <div className={`flex items-center justify-between p-4 border-b border-neutral-200 dark:border-neutral-700 ${
      isBuy ? 'bg-emerald-50 dark:bg-emerald-900/20' : 'bg-red-50 dark:bg-red-900/20'
    } rounded-t-xl`}>
      <div className="flex items-center gap-2">
        <Zap className={`h-5 w-5 ${isBuy ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-600 dark:text-red-400'}`} />
        <h2 className="text-lg font-semibold text-neutral-900 dark:text-neutral-50">
          Quick {isBuy ? 'Buy' : 'Sell'} {symbol}
        </h2>
      </div>
      <button
        onClick={onClose}
        className="p-1 text-neutral-500 hover:text-neutral-900 dark:text-neutral-400 dark:hover:text-neutral-50 rounded-lg transition-colors"
      >
        <X className="h-5 w-5" />
      </button>
    </div>
  );

  return (
    <Modal onClose={onClose} header={headerContent} maxWidth="sm">
        <form onSubmit={handleSubmit} className="p-4 space-y-4">
          {/* Quantity */}
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
              placeholder="Number of shares"
              autoFocus
              className="w-full px-3 py-2 border border-neutral-300 dark:border-neutral-600 rounded-lg bg-white dark:bg-neutral-700 text-neutral-900 dark:text-neutral-50 focus:ring-2 focus:ring-blue-500 focus:border-transparent text-lg"
              required
            />
          </div>

          {/* Price */}
          <div>
            <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
              Price per Share
            </label>
            <input
              type="number"
              step="0.01"
              min="0"
              value={price}
              onChange={(e) => setPrice(e.target.value)}
              placeholder="Price"
              className="w-full px-3 py-2 border border-neutral-300 dark:border-neutral-600 rounded-lg bg-white dark:bg-neutral-700 text-neutral-900 dark:text-neutral-50 focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              required
            />
          </div>

          {/* Total */}
          {totalValue > 0 && (
            <div className="p-3 bg-neutral-50 dark:bg-neutral-700/50 rounded-lg">
              <div className="flex justify-between text-sm">
                <span className="text-neutral-500">Total Value:</span>
                <span className="font-bold text-lg text-neutral-900 dark:text-neutral-50">
                  ${totalValue.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                </span>
              </div>
            </div>
          )}

          {/* Submit */}
          <div className="flex gap-3 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="flex-1 px-4 py-2 text-neutral-600 dark:text-neutral-400 hover:bg-neutral-100 dark:hover:bg-neutral-700 rounded-lg transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={createTrade.isPending || !quantity || !price}
              className={`flex-1 flex items-center justify-center gap-2 px-4 py-2 text-white rounded-lg transition-colors disabled:opacity-50 ${
                isBuy
                  ? 'bg-emerald-600 hover:bg-emerald-700'
                  : 'bg-red-600 hover:bg-red-700'
              }`}
            >
              {createTrade.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
              {isBuy ? 'Buy' : 'Sell'}
            </button>
          </div>
        </form>
    </Modal>
  );
}
