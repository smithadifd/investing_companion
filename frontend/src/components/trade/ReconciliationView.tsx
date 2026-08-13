'use client';

import { useState } from 'react';
import { AlertTriangle, Download, Loader2, Wand2 } from 'lucide-react';
import {
  useAccountReconciliation,
  useAdoptReconciliation,
  useTriggerBrokerImport,
} from '@/lib/hooks/useReconciliation';
import { ApiError } from '@/lib/api/client';
import { ConfirmModal } from '@/components/ui/ConfirmModal';
import type {
  Account,
  AdoptionResult,
  ReconciliationPosition,
} from '@/lib/api/types';
import { BrokerCsvUpload } from './BrokerCsvUpload';
import { TransactionReconciliationView } from './TransactionReconciliationView';

interface ReconciliationViewProps {
  accounts: Account[] | undefined;
}

type ReconTab = 'positions' | 'activity';

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
 * The Schwab reconciliation surface for one linked account.
 *
 * Three things live here, and they are meant to be used in this order:
 *   1. **Import from Schwab** — pulls positions + transactions. Nothing else
 *      on this screen has anything to show until a pull has happened.
 *   2. **Positions** — the §6 delta table (Schwab vs the IC ledger), with the
 *      §2 Adopt action that writes the deltas as synthetic trades. Ineligible
 *      rows are greyed, never hidden (§5).
 *   3. **Activity** — broker fills vs logged trades, which is where a fill you
 *      never wrote down actually shows up by name.
 */
export function ReconciliationView({ accounts }: ReconciliationViewProps) {
  const [accountId, setAccountId] = useState<number | null>(
    accounts && accounts.length > 0 ? accounts[0].id : null
  );
  const [tab, setTab] = useState<ReconTab>('positions');
  const [days, setDays] = useState(90);
  const [confirmAdopt, setConfirmAdopt] = useState(false);
  const [adoptResult, setAdoptResult] = useState<AdoptionResult | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const { data, isLoading, error } = useAccountReconciliation(accountId);
  const triggerImport = useTriggerBrokerImport();
  const adopt = useAdoptReconciliation();

  const noLink = error instanceof ApiError && error.status === 409;

  const adoptableCount =
    data?.positions.filter((p) => p.eligible && Number(p.quantity_delta) !== 0)
      .length ?? 0;

  const handleImport = async () => {
    if (accountId === null) return;
    setActionError(null);
    setAdoptResult(null);
    try {
      await triggerImport.mutateAsync({ accountId });
    } catch (e) {
      // 409 = not linked / Schwab needs reconnecting; 502 = Schwab said no.
      // Both are actionable by the user, so show the server's own wording.
      setActionError(
        e instanceof ApiError ? e.message : 'Could not import from Schwab.'
      );
    }
  };

  const handleAdopt = async () => {
    if (accountId === null) return;
    setActionError(null);
    try {
      const result = await adopt.mutateAsync(accountId);
      setAdoptResult(result);
    } catch (e) {
      setActionError(
        e instanceof ApiError ? e.message : 'Could not adopt these positions.'
      );
    } finally {
      setConfirmAdopt(false);
    }
  };

  if (!accounts || accounts.length === 0) {
    return (
      <p className="text-sm text-neutral-500 p-1">
        Add an account first, then link a Schwab account to reconcile it.
      </p>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-3">
        <div className="flex-1 min-w-[12rem]">
          <label
            htmlFor="recon-account"
            className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1"
          >
            Account
          </label>
          <select
            id="recon-account"
            value={accountId ?? ''}
            onChange={(e) => {
              setAccountId(Number(e.target.value));
              setAdoptResult(null);
              setActionError(null);
            }}
            className="w-full px-3 py-2 border border-neutral-300 dark:border-neutral-600 rounded-lg bg-white dark:bg-neutral-700 text-neutral-900 dark:text-neutral-50"
          >
            {accounts.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
        </div>
        <button
          type="button"
          onClick={handleImport}
          disabled={triggerImport.isPending || accountId === null}
          className="inline-flex items-center gap-2 px-3 py-2 rounded-lg bg-blue-600 hover:bg-blue-700 disabled:bg-blue-600/50 text-white text-sm font-medium transition-colors"
        >
          {triggerImport.isPending ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Download className="h-4 w-4" />
          )}
          Import from Schwab
        </button>
      </div>

      {actionError && (
        <div
          role="alert"
          className="rounded-lg border border-red-200 dark:border-red-800 bg-red-50 dark:bg-red-900/20 p-3 text-sm text-red-600 dark:text-red-300"
        >
          {actionError}
        </div>
      )}

      {triggerImport.isSuccess && !actionError && (
        <div className="rounded-lg border border-emerald-200 dark:border-emerald-800 bg-emerald-50 dark:bg-emerald-900/20 p-3 text-sm text-emerald-700 dark:text-emerald-300">
          Imported{' '}
          {triggerImport.data.runs
            .map((r) => `${r.item_count ?? 0} ${r.kind}`)
            .join(' and ')}
          .
        </div>
      )}

      {adoptResult && (
        <div className="rounded-lg border border-emerald-200 dark:border-emerald-800 bg-emerald-50 dark:bg-emerald-900/20 p-3 text-sm text-emerald-700 dark:text-emerald-300">
          Adopted {adoptResult.adopted.length} position
          {adoptResult.adopted.length === 1 ? '' : 's'}
          {adoptResult.skipped.length > 0 && (
            <>
              {' '}
              · skipped {adoptResult.skipped.length} needing review (
              {adoptResult.skipped.map((s) => s.symbol).join(', ')})
            </>
          )}
        </div>
      )}

      <div
        role="tablist"
        aria-label="Reconciliation views"
        className="flex gap-1 border-b border-neutral-200 dark:border-neutral-700"
      >
        {(['positions', 'activity'] as ReconTab[]).map((t) => (
          <button
            key={t}
            role="tab"
            aria-selected={tab === t}
            onClick={() => setTab(t)}
            className={`px-3 py-2 text-sm font-medium border-b-2 -mb-px capitalize transition-colors ${
              tab === t
                ? 'border-blue-600 text-blue-600 dark:text-blue-400'
                : 'border-transparent text-neutral-500 hover:text-neutral-700 dark:hover:text-neutral-300'
            }`}
          >
            {t}
          </button>
        ))}
      </div>

      {tab === 'activity' ? (
        <TransactionReconciliationView
          accountId={accountId}
          days={days}
          onDaysChange={setDays}
          recoverySlot={<BrokerCsvUpload accountId={accountId} compact />}
          uploadSlot={<BrokerCsvUpload accountId={accountId} />}
        />
      ) : (
        <>
          {isLoading && (
            <div className="flex items-center gap-2 text-sm text-neutral-500">
              <Loader2 className="h-4 w-4 animate-spin" /> Loading
              reconciliation…
            </div>
          )}

          {noLink && (
            <div className="rounded-lg border border-neutral-200 dark:border-neutral-700 bg-neutral-50 dark:bg-neutral-800/50 p-4 text-sm text-neutral-600 dark:text-neutral-300">
              This account isn&apos;t linked to a Schwab account yet. Link one to
              see how your ledger compares to what Schwab reports.
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
                    {fmtDate(data.newer_failed_import_at)}). This snapshot may be
                    out of date.
                  </span>
                </div>
              )}

              {data.never_imported ? (
                <div className="rounded-lg border border-neutral-200 dark:border-neutral-700 bg-neutral-50 dark:bg-neutral-800/50 p-4 text-sm text-neutral-600 dark:text-neutral-300">
                  This account is linked, but no Schwab positions have been
                  imported yet. Use Import from Schwab above and drift will
                  appear here.
                </div>
              ) : (
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="text-xs text-neutral-500">
                    Latest import: {fmtDate(data.last_import_at)}
                  </p>
                  <button
                    type="button"
                    onClick={() => setConfirmAdopt(true)}
                    disabled={adoptableCount === 0 || adopt.isPending}
                    title={
                      adoptableCount === 0
                        ? 'Nothing to adopt — your ledger already matches Schwab.'
                        : undefined
                    }
                    className="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg border border-blue-600 text-blue-600 dark:text-blue-400 hover:bg-blue-50 dark:hover:bg-blue-900/20 disabled:opacity-40 disabled:hover:bg-transparent text-sm font-medium transition-colors"
                  >
                    {adopt.isPending ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <Wand2 className="h-4 w-4" />
                    )}
                    Adopt {adoptableCount > 0 ? `(${adoptableCount})` : ''}
                  </button>
                </div>
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
                        <th className="text-left px-3 py-2 font-medium">
                          Symbol
                        </th>
                        <th className="text-right px-3 py-2 font-medium">
                          Schwab
                        </th>
                        <th className="text-right px-3 py-2 font-medium">IC</th>
                        <th className="text-right px-3 py-2 font-medium">
                          Δ Qty
                        </th>
                        <th className="text-right px-3 py-2 font-medium">
                          Schwab Basis
                        </th>
                        <th className="text-right px-3 py-2 font-medium">
                          IC Basis
                        </th>
                        <th className="text-right px-3 py-2 font-medium">
                          Δ Basis
                        </th>
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
        </>
      )}

      {confirmAdopt && (
        <ConfirmModal
          title="Adopt Schwab positions?"
          message={
            `This writes ${adoptableCount} synthetic trade` +
            `${adoptableCount === 1 ? '' : 's'} sized to the quantity ` +
            'difference, so your ledger matches what Schwab reports. Basis is ' +
            'not converged (v1 reconciles quantity only), rows needing manual ' +
            'review are skipped, and re-running against the same import ' +
            'creates no duplicates.\n\n' +
            'Afterwards, the individual fills behind that difference will ' +
            'still show as "Not in your ledger" on the Activity tab — they are ' +
            'covered by the synthetic trade, so entering them by hand as well ' +
            'would double-count. Delete the synthetic trade first if you want ' +
            'to log them individually.'
          }
          confirmLabel="Adopt"
          variant="warning"
          isLoading={adopt.isPending}
          onConfirm={handleAdopt}
          onCancel={() => setConfirmAdopt(false)}
        />
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
