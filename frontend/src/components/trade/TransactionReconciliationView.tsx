'use client';

import { AlertTriangle, Loader2 } from 'lucide-react';
import { useAccountTransactionReconciliation } from '@/lib/hooks/useReconciliation';
import { ApiError } from '@/lib/api/client';
import type { TransactionMatch } from '@/lib/api/types';

interface TransactionReconciliationViewProps {
  accountId: number | null;
  days: number;
  onDaysChange: (days: number) => void;
  /** Rendered inside the history-gap banner as the CSV recovery affordance. */
  recoverySlot?: React.ReactNode;
  /**
   * Rendered next to the window selector. The CSV path is not only for a
   * flagged gap — a first-ever import of an account with years of history is
   * beyond the API horizon too, and no banner fires for that.
   */
  uploadSlot?: React.ReactNode;
}

const STATUS_LABEL: Record<TransactionMatch['status'], string> = {
  matched: 'Matched',
  broker_only: 'Not in your ledger',
  ic_only: 'Not at broker',
  non_trade: 'Cash / non-trade',
};

const STATUS_CLASS: Record<TransactionMatch['status'], string> = {
  matched: 'text-emerald-600 dark:text-emerald-400',
  broker_only: 'text-amber-600 dark:text-amber-400 font-medium',
  ic_only: 'text-blue-600 dark:text-blue-400',
  non_trade: 'text-neutral-400',
};

const WINDOWS = [30, 90, 365, 1095];

function fmt(value: string | null): string {
  if (value === null) return '—';
  const n = Number(value);
  return Number.isFinite(n) ? String(n) : value;
}

function fmtDate(value: string | null): string {
  if (!value) return '—';
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? value : d.toLocaleDateString();
}

/**
 * The activity half of reconciliation: broker fills vs logged IC trades.
 *
 * Where the positions view answers "how far off is my ledger", this answers
 * "which fills did I never write down" — the rows flagged `broker_only`. Cash
 * movements are shown as `non_trade` rather than dropped, so an unexplained
 * absence never looks like a data-loss bug.
 */
export function TransactionReconciliationView({
  accountId,
  days,
  onDaysChange,
  recoverySlot,
  uploadSlot,
}: TransactionReconciliationViewProps) {
  const { data, isLoading, error } = useAccountTransactionReconciliation(
    accountId,
    days
  );

  const noLink = error instanceof ApiError && error.status === 409;

  if (noLink) {
    return (
      <div className="rounded-lg border border-neutral-200 dark:border-neutral-700 bg-neutral-50 dark:bg-neutral-800/50 p-4 text-sm text-neutral-600 dark:text-neutral-300">
        This account isn&apos;t linked to a Schwab account yet. Link one to
        compare your logged trades against what the broker reports.
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <label
            htmlFor="recon-window"
            className="text-sm text-neutral-600 dark:text-neutral-300"
          >
            Window
          </label>
          <select
            id="recon-window"
            value={days}
            onChange={(e) => onDaysChange(Number(e.target.value))}
            className="px-2 py-1 text-sm border border-neutral-300 dark:border-neutral-600 rounded-lg bg-white dark:bg-neutral-700 text-neutral-900 dark:text-neutral-50"
          >
            {WINDOWS.map((d) => (
              <option key={d} value={d}>
                Last {d} days
              </option>
            ))}
          </select>
        </div>
        {uploadSlot}
      </div>

      {isLoading && (
        <div className="flex items-center gap-2 text-sm text-neutral-500">
          <Loader2 className="h-4 w-4 animate-spin" /> Loading activity…
        </div>
      )}

      {error && !noLink && (
        <div className="rounded-lg border border-red-200 dark:border-red-800 bg-red-50 dark:bg-red-900/20 p-4 text-sm text-red-600 dark:text-red-300">
          Could not load activity reconciliation. Please try again.
        </div>
      )}

      {data && (
        <>
          {data.history_gap && (
            <div
              role="alert"
              className="rounded-lg border border-amber-300 dark:border-amber-700 bg-amber-50 dark:bg-amber-900/20 p-3 text-sm text-amber-800 dark:text-amber-200 space-y-2"
            >
              <div className="flex items-start gap-2">
                <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" />
                <span>
                  Schwab only serves the last{' '}
                  {data.transaction_history_limit_days} days of transactions, so
                  older activity was skipped and can never be pulled from the
                  API. Upload a broker CSV to recover it.
                </span>
              </div>
              {recoverySlot}
            </div>
          )}

          {data.never_imported ? (
            <div className="rounded-lg border border-neutral-200 dark:border-neutral-700 bg-neutral-50 dark:bg-neutral-800/50 p-4 text-sm text-neutral-600 dark:text-neutral-300">
              No broker transactions have been imported for this account yet.
              Import from Schwab, or upload a broker CSV for older activity.
            </div>
          ) : (
            <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-neutral-500">
              <span data-testid="txn-matched-count">
                {data.matched_count} matched
              </span>
              <span
                data-testid="txn-broker-only-count"
                className={
                  data.broker_only_count > 0
                    ? 'text-amber-600 dark:text-amber-400 font-medium'
                    : undefined
                }
              >
                {data.broker_only_count} not in your ledger
              </span>
              <span data-testid="txn-ic-only-count">
                {data.ic_only_count} not at broker
              </span>
            </div>
          )}

          {data.transactions.length === 0 ? (
            <p className="text-sm text-neutral-500">
              No activity in this window.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm border border-neutral-200 dark:border-neutral-700 rounded-lg">
                <thead className="bg-neutral-50 dark:bg-neutral-800 text-neutral-600 dark:text-neutral-300">
                  <tr>
                    <th className="text-left px-3 py-2 font-medium">Date</th>
                    <th className="text-left px-3 py-2 font-medium">Symbol</th>
                    <th className="text-left px-3 py-2 font-medium">Side</th>
                    <th className="text-right px-3 py-2 font-medium">Qty</th>
                    <th className="text-right px-3 py-2 font-medium">Price</th>
                    <th className="text-left px-3 py-2 font-medium">Status</th>
                    <th className="text-left px-3 py-2 font-medium">Source</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-neutral-100 dark:divide-neutral-700">
                  {data.transactions.map((t, i) => (
                    <ActivityRow
                      key={`${t.broker_transaction_id ?? 'ic'}-${
                        t.trade_id ?? i
                      }`}
                      row={t}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function ActivityRow({ row }: { row: TransactionMatch }) {
  const date = row.broker_occurred_at ?? row.ic_executed_at;
  const side = row.broker_side ?? row.ic_side;
  const qty = row.broker_quantity ?? row.ic_quantity;
  const price = row.broker_price ?? row.ic_price;
  const priceMismatch =
    row.status === 'matched' &&
    row.broker_price !== null &&
    row.ic_price !== null &&
    Number(row.broker_price) !== Number(row.ic_price);
  return (
    <tr
      data-testid={`activity-row-${row.status}-${row.symbol ?? 'cash'}`}
      className={row.status === 'non_trade' ? 'opacity-60' : ''}
      title={row.note ?? undefined}
    >
      <td className="px-3 py-2 whitespace-nowrap">{fmtDate(date)}</td>
      <td className="px-3 py-2 font-medium text-neutral-900 dark:text-neutral-50">
        {row.symbol ?? '—'}
      </td>
      <td className="px-3 py-2 uppercase">{side ?? '—'}</td>
      <td className="px-3 py-2 text-right tabular-nums">{fmt(qty)}</td>
      <td className="px-3 py-2 text-right tabular-nums">
        {fmt(price)}
        {/* Matching deliberately ignores price (brokers and hand-entry differ
            in the last cent), so a genuine price typo would otherwise be
            invisible on a matched row. Show the ledger's value when the two
            actually disagree. */}
        {priceMismatch && (
          <div
            className="text-xs text-amber-600 dark:text-amber-400"
            data-testid={`activity-price-mismatch-${row.symbol}`}
            title="Your ledger's price differs from the broker's"
          >
            yours {fmt(row.ic_price)}
          </div>
        )}
      </td>
      <td className={`px-3 py-2 ${STATUS_CLASS[row.status]}`}>
        {STATUS_LABEL[row.status]}
      </td>
      <td className="px-3 py-2 text-xs text-neutral-500">
        {row.broker_source === 'csv_import'
          ? 'CSV'
          : row.broker_source === 'schwab_api'
            ? 'Schwab'
            : '—'}
      </td>
    </tr>
  );
}
