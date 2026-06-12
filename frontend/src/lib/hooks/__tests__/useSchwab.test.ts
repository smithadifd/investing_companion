import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { createElement } from 'react';
import {
  useSchwabStatus,
  useConnectSchwab,
  useDisconnectSchwab,
} from '../useSchwab';
import type { SchwabStatus } from '../../api/types';

vi.mock('../../api/client', () => ({
  api: {
    isAuthenticated: vi.fn(() => true),
    getSchwabStatus: vi.fn(),
    connectSchwab: vi.fn(),
    disconnectSchwab: vi.fn(),
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

const connectedStatus: SchwabStatus = {
  configured: true,
  connected: true,
  needs_reconnect: false,
  token_age_days: 1.5,
  expires_in_days: 5.5,
};

describe('useSchwab hooks', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedApi.isAuthenticated.mockReturnValue(true);
  });

  it('useSchwabStatus fetches connection status', async () => {
    mockedApi.getSchwabStatus.mockResolvedValue(connectedStatus);

    const { result } = renderHook(() => useSchwabStatus(), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(connectedStatus);
  });

  it('useConnectSchwab returns the auth URL to redirect to', async () => {
    mockedApi.connectSchwab.mockResolvedValue({
      auth_url: 'https://api.schwabapi.com/v1/oauth/authorize?x=1',
    });

    const { result } = renderHook(() => useConnectSchwab(), {
      wrapper: createWrapper(),
    });

    const response = await result.current.mutateAsync();
    expect(response.auth_url).toContain('schwabapi.com');
    expect(mockedApi.connectSchwab).toHaveBeenCalledOnce();
  });

  it('useDisconnectSchwab calls the API', async () => {
    mockedApi.disconnectSchwab.mockResolvedValue({
      ...connectedStatus,
      connected: false,
    });

    const { result } = renderHook(() => useDisconnectSchwab(), {
      wrapper: createWrapper(),
    });

    const response = await result.current.mutateAsync();
    expect(response.connected).toBe(false);
    expect(mockedApi.disconnectSchwab).toHaveBeenCalledOnce();
  });
});
