import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { createElement } from 'react';
import {
  useAccounts,
  useCreateAccount,
  useDeleteAccount,
} from '../useAccount';
import type { Account } from '../../api/types';

vi.mock('../../api/client', () => ({
  api: {
    getAccounts: vi.fn(),
    createAccount: vi.fn(),
    updateAccount: vi.fn(),
    deleteAccount: vi.fn(),
  },
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

const mockAccount: Account = {
  id: 1,
  name: 'Roth',
  broker: 'Schwab',
  account_type: 'roth',
  risk_profile: 'aggressive',
  display_order: 0,
  created_at: '2026-06-12T00:00:00Z',
  updated_at: '2026-06-12T00:00:00Z',
};

describe('useAccount hooks', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('fetches accounts', async () => {
    mockedApi.getAccounts.mockResolvedValue([mockAccount]);

    const { result } = renderHook(() => useAccounts(), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toHaveLength(1);
    expect(result.current.data?.[0].name).toBe('Roth');
  });

  it('creates an account', async () => {
    mockedApi.createAccount.mockResolvedValue(mockAccount);

    const { result } = renderHook(() => useCreateAccount(), {
      wrapper: createWrapper(),
    });

    result.current.mutate({ name: 'Roth' });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockedApi.createAccount).toHaveBeenCalledWith({ name: 'Roth' });
  });

  it('deletes an account', async () => {
    mockedApi.deleteAccount.mockResolvedValue(undefined);

    const { result } = renderHook(() => useDeleteAccount(), {
      wrapper: createWrapper(),
    });

    result.current.mutate(1);
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockedApi.deleteAccount).toHaveBeenCalledWith(1);
  });
});
