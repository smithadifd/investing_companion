/**
 * Hook for the read-only §6 Schwab reconciliation view.
 *
 * Strictly read-only: it fetches the Schwab-vs-IC delta table for one account.
 * There is no adopt/mutation hook here by design (that surface belongs to a
 * later wave).
 */

import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';
import type { AccountReconciliation } from '../api/types';

/**
 * Fetch the reconciliation view for one account.
 *
 * Only runs when an account id is provided and `enabled` (e.g. the tab is
 * open). A 409 (no active Schwab link) surfaces as the query error, which the
 * view renders as a "link a Schwab account" prompt.
 */
export function useAccountReconciliation(
  accountId: number | null,
  enabled = true
) {
  return useQuery<AccountReconciliation>({
    queryKey: ['reconciliation', accountId],
    queryFn: () => api.getAccountReconciliation(accountId as number),
    enabled: enabled && accountId !== null,
    retry: false,
    staleTime: 60 * 1000,
  });
}
