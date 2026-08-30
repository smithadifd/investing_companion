'use client';

import { useId, useState } from 'react';
import { AlertTriangle, Loader2, Plus, Trash2, Download } from 'lucide-react';
import { useAccounts } from '@/lib/hooks/useAccount';
import {
  useBackfillCash,
  useCashTransactions,
  useCreateCashTransaction,
  useDeleteCashTransaction,
  useNav,
} from '@/lib/hooks/useCash';
import type { CashBackfillResult, CashTransactionKind } from '@/lib/api/types';

function toNumber(value: number | string | null | undefined): number {
  if (value === null || value === undefined) return 0;
  return typeof value === 'string' ? parseFloat(value) : value;
}

function formatCurrency(value: number | string | null | undefined): string {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(toNumber(value));
}

function formatDate(value: string): string {
  return new Date(value).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });
}

/**
 * NAV / total-return panel.
 *
 * The headline is the ABSOLUTE DOLLAR total return (the ratified first cut),
 * with the percentage as a subordinate line — it divides by net contributions
 * and is not time-weighted, so it must never read as the primary number.
 *
 * `is_estimated` is rendered as a visible banner listing every gap. A NAV with
 * a missing input is not a NAV with a smaller number; it is a NAV that is
 * short by an unknown amount, and the UI has to say so.
 */
export function NavPanel() {
  const { data: accounts } = useAccounts();
  // null = the whole ledger (every account plus the unassigned trade bucket).
  const [accountId, setAccountId] = useState<number | null>(null);
  const [backfillResult, setBackfillResult] =
    useState<CashBackfillResult | null>(null);

  const selectId = useId();
  const { data: nav, isLoading } = useNav(accountId);
  const { data: cashRows } = useCashTransactions({ account_id: accountId });
  const backfill = useBackfillCash();

  const handleBackfill = async () => {
    if (accountId == null) return;
    try {
      setBackfillResult(await backfill.mutateAsync(accountId));
    } catch {
      setBackfillResult(null);
    }
  };

  if (isLoading) {
    return (
      <div className="animate-pulse space-y-4">
        <div className="h-28 bg-neutral-200 dark:bg-neutral-700 rounded-lg" />
        <div className="h-48 bg-neutral-200 dark:bg-neutral-700 rounded-lg" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Scope picker */}
      <div className="flex flex-wrap items-end gap-3">
        <div>
          <label
            htmlFor={selectId}
            className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1"
          >
            Account
          </label>
          <select
            id={selectId}
            value={accountId ?? ''}
            onChange={(e) => {
              setAccountId(e.target.value ? parseInt(e.target.value, 10) : null);
              setBackfillResult(null);
            }}
            className="px-3 py-2 border border-neutral-300 dark:border-neutral-600 rounded-lg bg-white dark:bg-neutral-700 text-neutral-900 dark:text-neutral-50"
          >
            <option value="">All accounts</option>
            {(accounts ?? []).map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
        </div>
        {accountId != null && (
          <button
            type="button"
            onClick={handleBackfill}
            disabled={backfill.isPending}
            className="flex items-center gap-2 px-4 py-2 border border-neutral-300 dark:border-neutral-600 rounded-lg text-sm text-neutral-700 dark:text-neutral-300 hover:bg-neutral-100 dark:hover:bg-neutral-700 disabled:opacity-50"
          >
            {backfill.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Download className="h-4 w-4" />
            )}
            Backfill from broker
          </button>
        )}
      </div>

      {/* Headline: absolute dollars */}
      {nav && (
        <div className="p-6 bg-white dark:bg-neutral-800 rounded-lg border border-neutral-200 dark:border-neutral-700">
          <p className="text-sm text-neutral-500">Total return</p>
          <p
            className={`text-4xl font-semibold ${
              toNumber(nav.total_return_amount) >= 0
                ? 'text-emerald-600 dark:text-emerald-400'
                : 'text-red-600 dark:text-red-400'
            }`}
          >
            {formatCurrency(nav.total_return_amount)}
          </p>
          <p className="text-sm text-neutral-500 mt-1">
            {nav.total_return_percent !== null ? (
              <>
                {toNumber(nav.total_return_percent).toFixed(2)}% of{' '}
                {formatCurrency(nav.net_contributions)} contributed — a simple
                return, not time-weighted
              </>
            ) : (
              <>No contributions recorded, so there is no percentage to show</>
            )}
          </p>
          <p className="text-sm text-neutral-500 mt-3">
            NAV <span className="font-medium">{formatCurrency(nav.nav)}</span> ={' '}
            {formatCurrency(nav.cash_balance)} cash +{' '}
            {formatCurrency(nav.positions_market_value)} positions
          </p>
        </div>
      )}

      {/* Honesty banner */}
      {nav?.is_estimated && (
        <div
          role="status"
          className="p-4 rounded-lg border border-amber-300 bg-amber-50 dark:border-amber-800 dark:bg-amber-900/20"
        >
          <p className="flex items-center gap-2 font-medium text-amber-800 dark:text-amber-300">
            <AlertTriangle className="h-4 w-4" />
            Estimated — some inputs are missing
          </p>
          <ul className="mt-2 ml-6 list-disc text-sm text-amber-800 dark:text-amber-300">
            {nav.estimate_reasons.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        </div>
      )}

      {/* Breakdown */}
      {nav && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          {[
            { label: 'Realized P&L', value: nav.realized_pnl },
            { label: 'Unrealized P&L', value: nav.unrealized_pnl },
            { label: 'Dividends received', value: nav.dividends_received },
            { label: 'Fees paid', value: nav.fees_paid },
          ].map((cell) => (
            <div
              key={cell.label}
              className="p-4 bg-white dark:bg-neutral-800 rounded-lg border border-neutral-200 dark:border-neutral-700"
            >
              <p className="text-xs text-neutral-500">{cell.label}</p>
              <p className="text-lg font-medium text-neutral-900 dark:text-neutral-50">
                {formatCurrency(cell.value)}
              </p>
            </div>
          ))}
        </div>
      )}

      {backfillResult && (
        <div className="p-4 rounded-lg border border-neutral-200 dark:border-neutral-700 bg-white dark:bg-neutral-800 text-sm">
          <p className="font-medium text-neutral-900 dark:text-neutral-50">
            Adopted {backfillResult.created.length} cash movement
            {backfillResult.created.length === 1 ? '' : 's'};{' '}
            {backfillResult.already_present} already recorded.
          </p>
          {backfillResult.history_gap_note && (
            <p className="mt-2 text-amber-700 dark:text-amber-400">
              {backfillResult.history_gap_note}
            </p>
          )}
          {backfillResult.skipped.length > 0 && (
            <details className="mt-2">
              <summary className="cursor-pointer text-neutral-600 dark:text-neutral-400">
                {backfillResult.skipped.length} broker row
                {backfillResult.skipped.length === 1 ? '' : 's'} not adopted
              </summary>
              <ul className="mt-1 ml-4 list-disc text-neutral-600 dark:text-neutral-400">
                {backfillResult.skipped.map((row) => (
                  <li key={row.external_transaction_id}>
                    {row.broker_type} on {formatDate(row.occurred_at)} —{' '}
                    {row.reason}
                  </li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}

      <CashLedgerTable accountId={accountId} rows={cashRows ?? []} />
    </div>
  );
}

function CashLedgerTable({
  accountId,
  rows,
}: {
  accountId: number | null;
  rows: NonNullable<ReturnType<typeof useCashTransactions>['data']>;
}) {
  const { data: accounts } = useAccounts();
  const [showForm, setShowForm] = useState(false);
  const createCash = useCreateCashTransaction();
  const deleteCash = useDeleteCashTransaction();

  const [kind, setKind] = useState<CashTransactionKind>('deposit');
  const [amount, setAmount] = useState('');
  const [occurredAt, setOccurredAt] = useState(
    new Date().toISOString().slice(0, 16),
  );
  // Cash always belongs to an account: `cash_transactions.account_id` is NOT
  // NULL, so there is no "unassigned" option here on purpose.
  const [formAccountId, setFormAccountId] = useState<number | null>(accountId);

  const targetAccount = formAccountId ?? accountId ?? accounts?.[0]?.id ?? null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (targetAccount == null || !amount) return;
    await createCash.mutateAsync({
      account_id: targetAccount,
      kind,
      amount: parseFloat(amount),
      occurred_at: new Date(occurredAt).toISOString(),
    });
    setAmount('');
    setShowForm(false);
  };

  return (
    <div className="bg-white dark:bg-neutral-800 rounded-lg border border-neutral-200 dark:border-neutral-700">
      <div className="flex items-center justify-between p-4 border-b border-neutral-200 dark:border-neutral-700">
        <h3 className="font-medium text-neutral-900 dark:text-neutral-50">
          Cash ledger
        </h3>
        <button
          type="button"
          onClick={() => setShowForm((v) => !v)}
          className="flex items-center gap-1 px-3 py-1.5 text-sm rounded-lg bg-blue-600 text-white hover:bg-blue-700"
        >
          <Plus className="h-4 w-4" />
          Record cash
        </button>
      </div>

      {showForm && (
        <form
          onSubmit={handleSubmit}
          className="p-4 border-b border-neutral-200 dark:border-neutral-700 grid grid-cols-1 sm:grid-cols-4 gap-3"
        >
          <div>
            <label className="block text-xs text-neutral-500 mb-1" htmlFor="cash-kind">
              Kind
            </label>
            <select
              id="cash-kind"
              value={kind}
              onChange={(e) => setKind(e.target.value as CashTransactionKind)}
              className="w-full px-3 py-2 border border-neutral-300 dark:border-neutral-600 rounded-lg bg-white dark:bg-neutral-700 text-neutral-900 dark:text-neutral-50"
            >
              <option value="deposit">Deposit</option>
              <option value="withdrawal">Withdrawal</option>
            </select>
          </div>
          <div>
            <label className="block text-xs text-neutral-500 mb-1" htmlFor="cash-amount">
              Amount
            </label>
            <input
              id="cash-amount"
              type="number"
              step="0.01"
              min="0"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              placeholder="1000.00"
              className="w-full px-3 py-2 border border-neutral-300 dark:border-neutral-600 rounded-lg bg-white dark:bg-neutral-700 text-neutral-900 dark:text-neutral-50"
              required
            />
          </div>
          <div>
            <label className="block text-xs text-neutral-500 mb-1" htmlFor="cash-account">
              Account
            </label>
            <select
              id="cash-account"
              value={targetAccount ?? ''}
              onChange={(e) => setFormAccountId(parseInt(e.target.value, 10))}
              className="w-full px-3 py-2 border border-neutral-300 dark:border-neutral-600 rounded-lg bg-white dark:bg-neutral-700 text-neutral-900 dark:text-neutral-50"
              required
            >
              {(accounts ?? []).map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-xs text-neutral-500 mb-1" htmlFor="cash-date">
              Occurred at
            </label>
            <input
              id="cash-date"
              type="datetime-local"
              value={occurredAt}
              onChange={(e) => setOccurredAt(e.target.value)}
              className="w-full px-3 py-2 border border-neutral-300 dark:border-neutral-600 rounded-lg bg-white dark:bg-neutral-700 text-neutral-900 dark:text-neutral-50"
              required
            />
          </div>
          <div className="sm:col-span-4 flex justify-end">
            <button
              type="submit"
              disabled={createCash.isPending || targetAccount == null}
              className="flex items-center gap-2 px-4 py-2 rounded-lg bg-emerald-600 text-white hover:bg-emerald-700 disabled:opacity-50"
            >
              {createCash.isPending && (
                <Loader2 className="h-4 w-4 animate-spin" />
              )}
              Save
            </button>
          </div>
        </form>
      )}

      {rows.length === 0 ? (
        <p className="p-6 text-sm text-neutral-500">
          No cash recorded yet. Until the ledger reaches back to your first
          trade, total return is reported as an estimate.
        </p>
      ) : (
        <ul className="divide-y divide-neutral-200 dark:divide-neutral-700">
          {rows.map((row) => (
            <li key={row.id} className="flex items-center gap-4 p-3 text-sm">
              <span className="w-24 uppercase text-xs font-medium text-neutral-500">
                {row.kind}
              </span>
              <span
                className={
                  toNumber(row.signed_amount) >= 0
                    ? 'text-emerald-600 dark:text-emerald-400'
                    : 'text-red-600 dark:text-red-400'
                }
              >
                {formatCurrency(row.signed_amount)}
              </span>
              <span className="text-neutral-500">
                {formatDate(row.occurred_at)}
              </span>
              <span className="text-neutral-500">
                {row.account?.name ?? ''}
              </span>
              {row.source !== 'manual' && (
                <span className="px-2 py-0.5 rounded text-xs bg-neutral-100 dark:bg-neutral-700 text-neutral-600 dark:text-neutral-300">
                  {row.source}
                </span>
              )}
              <button
                type="button"
                aria-label={`Delete ${row.kind} of ${formatCurrency(row.amount)}`}
                onClick={() => deleteCash.mutate(row.id)}
                className="ml-auto text-neutral-400 hover:text-red-600"
              >
                <Trash2 className="h-4 w-4" />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
