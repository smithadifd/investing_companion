import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { createElement } from 'react';
import {
  useAccountReconciliation,
  useAccountTransactionReconciliation,
  useAdoptReconciliation,
  useImportBrokerCsv,
  useTriggerBrokerImport,
} from '../useReconciliation';
import type {
  AccountReconciliation,
  TransactionReconciliation,
} from '../../api/types';

vi.mock('../../api/client', () => ({
  api: {
    getAccountReconciliation: vi.fn(),
    getAccountTransactionReconciliation: vi.fn(),
    triggerBrokerImport: vi.fn(),
    adoptAccountReconciliation: vi.fn(),
    importBrokerCsv: vi.fn(),
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


const transactionView: TransactionReconciliation = {
  window_start: '2026-05-01T00:00:00Z',
  window_end: '2026-08-01T00:00:00Z',
  last_import_at: '2026-07-31T00:00:00Z',
  never_imported: false,
  newer_failed_import_at: null,
  history_gap: true,
  history_gap_note: 'HISTORY GAP: ...',
  transaction_history_limit_days: 60,
  matched_count: 1,
  broker_only_count: 2,
  ic_only_count: 0,
  transactions: [],
};

describe('useAccountTransactionReconciliation', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('passes the window through to the API', async () => {
    mockedApi.getAccountTransactionReconciliation.mockResolvedValue(
      transactionView
    );

    const { result } = renderHook(
      () => useAccountTransactionReconciliation(1, 365),
      { wrapper: createWrapper() }
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.broker_only_count).toBe(2);
    expect(
      mockedApi.getAccountTransactionReconciliation
    ).toHaveBeenCalledWith(1, 365);
  });

  it('does not fetch when accountId is null', () => {
    const { result } = renderHook(
      () => useAccountTransactionReconciliation(null),
      { wrapper: createWrapper() }
    );
    expect(result.current.fetchStatus).toBe('idle');
    expect(
      mockedApi.getAccountTransactionReconciliation
    ).not.toHaveBeenCalled();
  });
});

describe('useTriggerBrokerImport', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('defaults to importing both kinds', async () => {
    mockedApi.triggerBrokerImport.mockResolvedValue({
      account_id: 1,
      runs: [],
    });

    const { result } = renderHook(() => useTriggerBrokerImport(), {
      wrapper: createWrapper(),
    });
    await result.current.mutateAsync({ accountId: 1 });

    expect(mockedApi.triggerBrokerImport).toHaveBeenCalledWith(1, 'both');
  });

  it('forwards an explicit kind', async () => {
    mockedApi.triggerBrokerImport.mockResolvedValue({
      account_id: 1,
      runs: [],
    });

    const { result } = renderHook(() => useTriggerBrokerImport(), {
      wrapper: createWrapper(),
    });
    await result.current.mutateAsync({ accountId: 1, kind: 'transactions' });

    expect(mockedApi.triggerBrokerImport).toHaveBeenCalledWith(
      1,
      'transactions'
    );
  });
});

describe('useAdoptReconciliation', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('adopts for the given account', async () => {
    mockedApi.adoptAccountReconciliation.mockResolvedValue({
      account_id: 7,
      source_import_run_id: 3,
      adopted: [],
      skipped: [],
    });

    const { result } = renderHook(() => useAdoptReconciliation(), {
      wrapper: createWrapper(),
    });
    await result.current.mutateAsync(7);

    expect(mockedApi.adoptAccountReconciliation).toHaveBeenCalledWith(7);
  });
});

describe('useImportBrokerCsv', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('forwards the file contents and name', async () => {
    mockedApi.importBrokerCsv.mockResolvedValue({
      account_id: 1,
      run: {
        id: 1,
        source: 'csv_import',
        kind: 'transactions',
        status: 'complete',
        window_start: null,
        window_end: null,
        item_count: 2,
        error_message: null,
        notes: null,
        created_at: '2026-08-13T00:00:00Z',
      },
      imported_count: 2,
      skipped: [],
      earliest_occurred_at: null,
      latest_occurred_at: null,
    });

    const { result } = renderHook(() => useImportBrokerCsv(), {
      wrapper: createWrapper(),
    });
    await result.current.mutateAsync({
      accountId: 1,
      content: 'Date,Action\n',
      filename: 'x.csv',
    });

    expect(mockedApi.importBrokerCsv).toHaveBeenCalledWith(
      1,
      'Date,Action\n',
      'x.csv'
    );
  });
});
