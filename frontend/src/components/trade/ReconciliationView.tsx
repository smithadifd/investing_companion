'use client';

import { useState } from 'react';
import { AlertTriangle, Loader2 } from 'lucide-react';
import { useAccountReconciliation } from '@/lib/hooks/useReconciliation';
import { ApiError } from '@/lib/api/client';
import type { Account, ReconciliationPosition } from '@/lib/api/types';

interface ReconciliationViewProps {
  accounts: Account[] | undefined;
}

/** Trim a Decimal-string like "10.00000000" to a readable "10". */
function fmt(value: string | null): string {
  if (value === null) return '—';
  const n = Number(value);
  return Number.isFinite(n) ? String(n) : value;
}

function fmtDate(value: string | null): string {
  if (!value) return '';
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? value : d.toLocaleString();
}

/**
 * Read-only §6 reconciliation view: the Schwab-vs-IC delta table for a linked
 * account. STRICTLY read-only — it renders deltas and never writes trades or
 * adopts positions (no "Adopt" control by design). Ineligible rows are greyed,
 * never hidden (§5); a never-imported account shows a plain banner instead of
 * drift-styled rows.
 */
export function ReconciliationView({ accounts }: ReconciliationViewProps) {
  const [accountId, setAccountId] = useState<number | null>(
    accounts && accounts.length > 0 ? accounts[0].id : null
  );

  const { data, isLoading, error } = useAccountReconciliation(accountId);

  const noLink = error instanceof ApiError && error.status === 409;

  if (!accounts || accounts.length === 0) {
    return (
      <p className="text-sm text-neutral-500 p-1">
        Add an account first, then link a Schwab account to reconcile it.
      </p>
    );
  }

  return (
    <div className="space-y-4">
      <div>
        <label
          htmlFor="recon-account"
          className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1"
        >
          Account
        </label>
        <select
          id="recon-account"
          value={accountId ?? ''}
          onChange={(e) => setAccountId(Number(e.target.value))}
          className="w-full px-3 py-2 border border-neutral-300 dark:border-neutral-600 rounded-lg bg-white dark:bg-neutral-700 text-neutral-900 dark:text-neutral-50"
        >
          {accounts.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name}
            </option>
          ))}
        </select>
      </div>

      {isLoading && (
        <div className="flex items-center gap-2 text-sm text-neutral-500">
          <Loader2 className="h-4 w-4 animate-spin" /> Loading reconciliation…
        </div>
      )}

      {noLink && (
        <div className="rounded-lg border border-neutral-200 dark:border-neutral-700 bg-neutral-50 dark:bg-neutral-800/50 p-4 text-sm text-neutral-600 dark:text-neutral-300">
          This account isn&apos;t linked to a Schwab account yet. Link one to see
          how your ledger compares to what Schwab reports.
        </div>
      )}

      {error && !noLink && (
        <div className="rounded-lg border border-red-200 dark:border-red-800 bg-red-50 dark:bg-red-900/20 p-4 text-sm text-red-600 dark:text-red-300">
          Could not load reconciliation. Please try again.
        </div>
      )}

      {data && (
        <>
          {data.newer_failed_import_at && (
            <div
              role="alert"
              className="flex items-start gap-2 rounded-lg border border-amber-300 dark:border-amber-700 bg-amber-50 dark:bg-amber-900/20 p-3 text-sm text-amber-800 dark:text-amber-200"
            >
              <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" />
              <span>
                Your most recent Schwab pull failed (
                {fmtDate(data.newer_failed_import_at)}). This snapshot may be out
                of date.
              </span>
            </div>
          )}

          {data.never_imported ? (
            <div className="rounded-lg border border-neutral-200 dark:border-neutral-700 bg-neutral-50 dark:bg-neutral-800/50 p-4 text-sm text-neutral-600 dark:text-neutral-300">
              This account is linked, but no Schwab positions have been imported
              yet. Once a pull completes, drift will appear here.
            </div>
          ) : (
            <p className="text-xs text-neutral-500">
              Latest import: {fmtDate(data.last_import_at)}
            </p>
          )}

          {data.positions.length === 0 ? (
            <p className="text-sm text-neutral-500">
              No positions to reconcile.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm border border-neutral-200 dark:border-neutral-700 rounded-lg">
                <thead className="bg-neutral-50 dark:bg-neutral-800 text-neutral-600 dark:text-neutral-300">
                  <tr>
                    <th className="text-left px-3 py-2 font-medium">Symbol</th>
                    <th className="text-right px-3 py-2 font-medium">Schwab</th>
                    <th className="text-right px-3 py-2 font-medium">IC</th>
                    <th className="text-right px-3 py-2 font-medium">Δ Qty</th>
                    <th className="text-right px-3 py-2 font-medium">
                      Schwab Basis
                    </th>
                    <th className="text-right px-3 py-2 font-medium">IC Basis</th>
                    <th className="text-right px-3 py-2 font-medium">Δ Basis</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-neutral-100 dark:divide-neutral-700">
                  {data.positions.map((p) => (
                    <ReconciliationRow key={p.symbol} position={p} />
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

function ReconciliationRow({ position: p }: { position: ReconciliationPosition }) {
  const deltaNonZero = Number(p.quantity_delta) !== 0;
  return (
    <tr
      data-testid={`recon-row-${p.symbol}`}
      className={
        p.eligible
          ? ''
          : 'opacity-50 bg-neutral-50/60 dark:bg-neutral-800/40 text-neutral-500'
      }
      title={p.eligible ? undefined : p.ineligible_reason ?? undefined}
    >
      <td className="px-3 py-2">
        <span className="font-medium text-neutral-900 dark:text-neutral-50">
          {p.symbol}
        </span>
        {!p.eligible && (
          <span className="ml-2 text-xs text-neutral-400">
            {p.ineligible_reason ?? 'not reconcilable'}
          </span>
        )}
        {p.ledger_inconsistent && (
          <span className="ml-2 text-xs text-amber-600 dark:text-amber-400">
            ledger inconsistent
          </span>
        )}
      </td>
      <td className="px-3 py-2 text-right tabular-nums">
        {fmt(p.schwab_quantity)}
      </td>
      <td className="px-3 py-2 text-right tabular-nums">
        {fmt(p.ic_quantity)}
      </td>
      <td
        className={`px-3 py-2 text-right tabular-nums ${
          deltaNonZero
            ? 'text-amber-600 dark:text-amber-400 font-medium'
            : 'text-neutral-500'
        }`}
      >
        {fmt(p.quantity_delta)}
      </td>
      <td className="px-3 py-2 text-right tabular-nums">{fmt(p.schwab_basis)}</td>
      <td className="px-3 py-2 text-right tabular-nums">{fmt(p.ic_basis)}</td>
      <td className="px-3 py-2 text-right tabular-nums">{fmt(p.basis_delta)}</td>
    </tr>
  );
}
