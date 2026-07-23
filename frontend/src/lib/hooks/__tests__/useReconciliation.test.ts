import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { createElement } from 'react';
import { useAccountReconciliation } from '../useReconciliation';
import type { AccountReconciliation } from '../../api/types';

vi.mock('../../api/client', () => ({
  api: {
    getAccountReconciliation: vi.fn(),
  },
  ApiError: class ApiError extends Error {},
}));

import { api } from '../../api/client';

const mockedApi = vi.mocked(api);

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
      mutations: { retry: false },
    },
  });
  return function Wrapper({ children }: { children: ReactNode }) {
    return createElement(QueryClientProvider, { client: queryClient }, children);
  };
}

const reconciliation: AccountReconciliation = {
  last_import_at: '2026-07-23T00:00:00Z',
  never_imported: false,
  newer_failed_import_at: null,
  positions: [
    {
      symbol: 'AAPL',
      asset_type: 'EQUITY',
      eligible: true,
      ineligible_reason: null,
      schwab_quantity: '10',
      ic_quantity: '8',
      quantity_delta: '2',
      schwab_basis: '150',
      ic_basis: '100',
      basis_delta: '50',
      ledger_inconsistent: false,
    },
  ],
};

describe('useAccountReconciliation', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('fetches reconciliation for an account', async () => {
    mockedApi.getAccountReconciliation.mockResolvedValue(reconciliation);

    const { result } = renderHook(() => useAccountReconciliation(1), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.positions[0].symbol).toBe('AAPL');
    expect(mockedApi.getAccountReconciliation).toHaveBeenCalledWith(1);
  });

  it('does not fetch when accountId is null', async () => {
    const { result } = renderHook(() => useAccountReconciliation(null), {
      wrapper: createWrapper(),
    });
    // Query is disabled — never fires.
    expect(result.current.fetchStatus).toBe('idle');
    expect(mockedApi.getAccountReconciliation).not.toHaveBeenCalled();
  });

  it('does not fetch when disabled', async () => {
    renderHook(() => useAccountReconciliation(1, false), {
      wrapper: createWrapper(),
    });
    expect(mockedApi.getAccountReconciliation).not.toHaveBeenCalled();
  });
});
