'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import type {
  CashBackfillResult,
  CashTransaction,
  CashTransactionCreate,
  NavSummary,
} from '../api/types';

/**
 * Hook to fetch NAV / total return.
 *
 * `accountId` null/undefined means the WHOLE ledger (every account plus the
 * unassigned trade bucket) — not "the unassigned bucket". The backend is
 * deliberately a separate endpoint from `/trades/portfolio`, so this is never
 * on the dashboard's render path.
 */
export function useNav(accountId?: number | null) {
  return useQuery<NavSummary>({
    queryKey: ['nav', accountId ?? 'all'],
    queryFn: () => api.getNav(accountId),
  });
}

/** Hook to fetch cash transactions (deposits and withdrawals). */
export function useCashTransactions(params?: {
  account_id?: number | null;
  limit?: number;
  offset?: number;
}) {
  return useQuery<CashTransaction[]>({
    queryKey: ['cash', params],
    queryFn: () => api.getCashTransactions(params),
  });
}

/**
 * Every cash mutation invalidates `nav` as well as `cash`: NAV is a fold over
 * this table, so a stale NAV after a deposit is exactly the drift the
 * derived-not-stored design exists to prevent.
 */
function useCashInvalidation() {
  const queryClient = useQueryClient();
  return () => {
    queryClient.invalidateQueries({ queryKey: ['cash'] });
    queryClient.invalidateQueries({ queryKey: ['nav'] });
  };
}

export function useCreateCashTransaction() {
  const invalidate = useCashInvalidation();
  return useMutation({
    mutationFn: (data: CashTransactionCreate) => api.createCashTransaction(data),
    onSuccess: invalidate,
  });
}

export function useDeleteCashTransaction() {
  const invalidate = useCashInvalidation();
  return useMutation({
    mutationFn: (id: number) => api.deleteCashTransaction(id),
    onSuccess: invalidate,
  });
}

/**
 * Adopt already-imported broker cash movements. Idempotent — re-running is
 * safe and reports what was already there rather than duplicating it.
 */
export function useBackfillCash() {
  const invalidate = useCashInvalidation();
  return useMutation<CashBackfillResult, Error, number>({
    mutationFn: (accountId: number) => api.backfillCashFromBroker(accountId),
    onSuccess: invalidate,
  });
}
