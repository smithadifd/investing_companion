/**
 * Hooks for the Schwab reconciliation surface.
 *
 * Two read hooks (the §6 positions delta table and the transactions activity
 * view) and two mutations (pull from Schwab, adopt the delta). The mutations
 * invalidate BOTH reconciliation queries plus trades/portfolio, because an
 * import changes what the broker side reports and an adoption writes real
 * trades that every position read is derived from.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import type {
  AccountReconciliation,
  AdoptionResult,
  ImportKindRequest,
  ImportTriggerResult,
  TransactionReconciliation,
} from '../api/types';

/**
 * Fetch the positions reconciliation view for one account.
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

/**
 * Fetch the transactions activity reconciliation for one account.
 *
 * `days` is part of the query key so widening the window refetches rather than
 * serving a narrower cached window.
 */
export function useAccountTransactionReconciliation(
  accountId: number | null,
  days = 90,
  enabled = true
) {
  return useQuery<TransactionReconciliation>({
    queryKey: ['reconciliation', 'transactions', accountId, days],
    queryFn: () =>
      api.getAccountTransactionReconciliation(accountId as number, days),
    enabled: enabled && accountId !== null,
    retry: false,
    staleTime: 60 * 1000,
  });
}

/** Query keys every reconciliation-affecting mutation must invalidate. */
function invalidateReconciliation(
  queryClient: ReturnType<typeof useQueryClient>
) {
  queryClient.invalidateQueries({ queryKey: ['reconciliation'] });
  queryClient.invalidateQueries({ queryKey: ['trades'] });
  queryClient.invalidateQueries({ queryKey: ['portfolio'] });
}

/**
 * Trigger a Schwab pull for one account. This is what takes a linked account
 * out of its "never imported" state — before this existed, nothing in the app
 * ever called the ingestion service.
 */
export function useTriggerBrokerImport() {
  const queryClient = useQueryClient();
  return useMutation<
    ImportTriggerResult,
    Error,
    { accountId: number; kind?: ImportKindRequest }
  >({
    mutationFn: ({ accountId, kind }) =>
      api.triggerBrokerImport(accountId, kind ?? 'both'),
    onSuccess: () => invalidateReconciliation(queryClient),
  });
}

/**
 * Adopt the reconciliation delta into synthetic trades. Replay-safe server
 * side, so a double click cannot double-adopt.
 */
export function useAdoptReconciliation() {
  const queryClient = useQueryClient();
  return useMutation<AdoptionResult, Error, number>({
    mutationFn: (accountId) => api.adoptAccountReconciliation(accountId),
    onSuccess: () => invalidateReconciliation(queryClient),
  });
}
