'use client';

import { useState } from 'react';
import { Loader2 } from 'lucide-react';
import { useCreateTrade } from '@/lib/hooks/useTrade';
import { AccountSelect } from '@/components/trade/AccountSelect';
import { EquitySearchInput } from '@/components/equity/EquitySearchInput';
import { LessonCaptureModal } from '@/components/trade/LessonCaptureModal';
import { Modal } from '@/components/ui/Modal';
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
  {
    value: 'dividend',
    label: 'Dividend',
    description:
      'Cash paid on shares you hold — quantity is the shares it paid on, price is the per-share amount. Share count is unchanged.',
  },
  {
    value: 'split',
    label: 'Split',
    description:
      'Stock split — quantity is the ratio (4 for a 4:1, 0.25 for a 1:4 reverse). A split belongs to the security, so it adjusts every account holding it.',
  },
];

// Types whose submit button reads as a reduction. Dividend and split are
// neither: dividend is cash in, split is a re-denomination.
const RED_TYPES: TradeType[] = ['sell', 'short'];
const GREEN_TYPES: TradeType[] = ['buy', 'cover', 'dividend'];

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
  const [accountId, setAccountId] = useState<number | null>(null);

  const [searchQuery, setSearchQuery] = useState(prefillSymbol || '');
  // Set when the logged trade closed the position - swaps the form for the
  // (optional, skippable) lesson-capture step
  const [capture, setCapture] = useState<{ symbol: string; tradeId: number } | null>(
    null
  );

  const createTrade = useCreateTrade();

  const handleSearchChange = (query: string) => {
    setSearchQuery(query);
    setEquitySymbol(query.toUpperCase());
  };

  const handleSelectEquity = (equity: EquitySearchResult) => {
    setEquitySymbol(equity.symbol);
    setSearchQuery(equity.symbol);
  };

  // A split's price is the sentinel 0 (its quantity is the ratio) and it
  // carries no account — the API rejects anything else. Both are enforced here
  // so the form can't build a body the backend will 422.
  const isSplit = tradeType === 'split';
  const isDividend = tradeType === 'dividend';

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!equitySymbol || !quantity || (!isSplit && !price)) return;

    const data: TradeCreate = {
      symbol: equitySymbol.toUpperCase(),
      trade_type: tradeType,
      quantity: parseFloat(quantity),
      price: isSplit ? 0 : parseFloat(price),
      fees: isSplit ? 0 : parseFloat(fees) || 0,
      executed_at: new Date(executedAt).toISOString(),
      notes: notes || undefined,
      account_id: isSplit ? null : accountId,
    };

    try {
      const trade = await createTrade.mutateAsync(data);
      if (trade.position_closed) {
        setCapture({ symbol: trade.equity.symbol, tradeId: trade.id });
      } else {
        handleClose();
      }
    } catch (error) {
      console.error('Failed to create trade:', error);
    }
  };

  const handleClose = () => {
    setCapture(null);
    setTradeType('buy');
    setEquitySymbol(prefillSymbol || '');
    setSearchQuery(prefillSymbol || '');
    setQuantity('');
    setPrice('');
    setFees('0');
    setExecutedAt(new Date().toISOString().slice(0, 16));
    setNotes('');
    setAccountId(null);
    onClose();
  };

  // Calculate total value (meaningless for a split — quantity is a ratio, not
  // a share count, and price is the sentinel 0).
  const totalValue =
    !isSplit && quantity && price ? parseFloat(quantity) * parseFloat(price) : 0;
  const totalWithFees = totalValue + (parseFloat(fees) || 0);

  if (!isOpen) return null;

  if (capture) {
    return (
      <LessonCaptureModal
        symbol={capture.symbol}
        tradeId={capture.tradeId}
        onClose={handleClose}
      />
    );
  }

  return (
    <Modal onClose={handleClose} title="Log Trade" maxWidth="lg">
      <form onSubmit={handleSubmit} className="p-4 space-y-4">
          {/* Trade Type */}
          <div>
            <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-2">
              Trade Type
            </label>
            <div className="grid grid-cols-3 gap-2">
              {TRADE_TYPES.map((type) => (
                <button
                  key={type.value}
                  type="button"
                  onClick={() => setTradeType(type.value)}
                  className={`py-2 px-3 rounded-lg text-sm font-medium transition-colors ${
                    tradeType === type.value
                      ? GREEN_TYPES.includes(type.value)
                        ? 'bg-emerald-600 text-white'
                        : RED_TYPES.includes(type.value)
                          ? 'bg-red-600 text-white'
                          : 'bg-amber-600 text-white'
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
          <div>
            <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
              Symbol
            </label>
            <EquitySearchInput
              value={searchQuery}
              onChange={handleSearchChange}
              onSelect={handleSelectEquity}
              required
            />
          </div>

          {/* Account (only shown once accounts exist). Never on a split: one
              split row adjusts every account holding the symbol. */}
          {!isSplit && <AccountSelect value={accountId} onChange={setAccountId} />}

          {/* Quantity and Price */}
          <div className={isSplit ? '' : 'grid grid-cols-2 gap-4'}>
            <div>
              <label
                htmlFor="trade-quantity"
                className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1"
              >
                {isSplit ? 'Split Ratio' : isDividend ? 'Shares Held' : 'Quantity'}
              </label>
              <input
                id="trade-quantity"
                type="number"
                step="any"
                min="0"
                value={quantity}
                onChange={(e) => setQuantity(e.target.value)}
                placeholder={isSplit ? '4' : '100'}
                className="w-full px-3 py-2 border border-neutral-300 dark:border-neutral-600 rounded-lg bg-white dark:bg-neutral-700 text-neutral-900 dark:text-neutral-50 focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                required
              />
            </div>
            {!isSplit && (
              <div>
                <label
                  htmlFor="trade-price"
                  className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1"
                >
                  {isDividend ? 'Dividend per Share' : 'Price per Share'}
                </label>
                <input
                  id="trade-price"
                  type="number"
                  step="0.0001"
                  min="0"
                  value={price}
                  onChange={(e) => setPrice(e.target.value)}
                  placeholder={isDividend ? '1.20' : '50.00'}
                  className="w-full px-3 py-2 border border-neutral-300 dark:border-neutral-600 rounded-lg bg-white dark:bg-neutral-700 text-neutral-900 dark:text-neutral-50 focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  required
                />
              </div>
            )}
          </div>

          {/* Fees — a split has none (it is not a transaction) */}
          {!isSplit && (
            <div>
              <label
                htmlFor="trade-fees"
                className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1"
              >
                {isDividend ? 'Withholding/Fees' : 'Fees/Commission'}
              </label>
              <input
                id="trade-fees"
                type="number"
                step="0.01"
                min="0"
                value={fees}
                onChange={(e) => setFees(e.target.value)}
                placeholder="0.00"
                className="w-full px-3 py-2 border border-neutral-300 dark:border-neutral-600 rounded-lg bg-white dark:bg-neutral-700 text-neutral-900 dark:text-neutral-50 focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              />
            </div>
          )}

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
                GREEN_TYPES.includes(tradeType)
                  ? 'bg-emerald-600 hover:bg-emerald-700'
                  : RED_TYPES.includes(tradeType)
                    ? 'bg-red-600 hover:bg-red-700'
                    : 'bg-amber-600 hover:bg-amber-700'
              }`}
            >
              {createTrade.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
              Log {tradeType.charAt(0).toUpperCase() + tradeType.slice(1)}
            </button>
          </div>
      </form>
    </Modal>
  );
}
