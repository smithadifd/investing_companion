import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { createElement, type ReactNode } from 'react';
import {
  useAppSettings,
  useChangePassword,
  useCurrentUser,
  useLogin,
  useLogout,
  useLogoutAll,
  useRegister,
  useRegistrationStatus,
  useSessions,
  useUpdateAppSettings,
  useUpdateEmail,
} from '../useAuth';
import type { AppSettings, SessionInfo, User } from '../../api/types';

vi.mock('../../api/client', () => ({
  api: {
    isAuthenticated: vi.fn(),
    getCurrentUser: vi.fn(),
    getRegistrationStatus: vi.fn(),
    register: vi.fn(),
    login: vi.fn(),
    logout: vi.fn(),
    logoutAll: vi.fn(),
    changePassword: vi.fn(),
    updateCurrentUser: vi.fn(),
    getSessions: vi.fn(),
    getAppSettings: vi.fn(),
    updateAppSettings: vi.fn(),
  },
}));

import { api } from '../../api/client';

const mockedApi = vi.mocked(api);

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  function Wrapper({ children }: { children: ReactNode }) {
    return createElement(QueryClientProvider, { client: queryClient }, children);
  }
  return { queryClient, wrapper: Wrapper };
}

const user: User = {
  id: 'user-1',
  email: 'user@example.com',
  is_active: true,
  is_admin: false,
  created_at: '2026-01-01T00:00:00Z',
  last_login_at: null,
};

const settings: AppSettings = {
  claude_api_key: null,
  alpha_vantage_api_key: null,
  polygon_api_key: null,
  discord_webhook_url: null,
  default_watchlist_id: null,
  theme: 'system',
  morning_notification_time: '08:00',
  eod_notification_time: '17:00',
  news_agent_enabled: false,
  trade_journal_agent_enabled: false,
  strategy_agent_enabled: false,
};

const session: SessionInfo = {
  id: 'session-1',
  user_agent: null,
  ip_address: null,
  created_at: '2026-01-01T00:00:00Z',
  expires_at: '2026-01-02T00:00:00Z',
  is_current: true,
};

describe('useAuth hooks', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedApi.isAuthenticated.mockReturnValue(false);
  });

  it('fetches the current user only when authenticated', async () => {
    mockedApi.getCurrentUser.mockResolvedValue(user);
    const { wrapper } = createWrapper();
    const { result, rerender } = renderHook(() => useCurrentUser(), { wrapper });

    expect(mockedApi.getCurrentUser).not.toHaveBeenCalled();
    mockedApi.isAuthenticated.mockReturnValue(true);
    rerender();
    await waitFor(() => expect(result.current.data).toEqual(user));
    expect(mockedApi.getCurrentUser).toHaveBeenCalledOnce();
  });

  it('fetches registration status without authentication', async () => {
    const status = { enabled: true, message: null };
    mockedApi.getRegistrationStatus.mockResolvedValue(status);
    const { result } = renderHook(() => useRegistrationStatus(), createWrapper());

    await waitFor(() => expect(result.current.data).toEqual(status));
    expect(mockedApi.getRegistrationStatus).toHaveBeenCalledOnce();
  });

  it('registers with the supplied credentials', async () => {
    const credentials = {
      email: 'new@example.com', password: 'example-password', password_confirm: 'example-password',
    };
    mockedApi.register.mockResolvedValue(user);
    const { result } = renderHook(() => useRegister(), createWrapper());

    let registered: User | undefined;
    await act(async () => { registered = await result.current.mutateAsync(credentials); });
    expect(mockedApi.register).toHaveBeenCalledWith(credentials);
    expect(registered).toEqual(user);
  });

  it('logs in and invalidates the cached current user', async () => {
    const credentials = { email: 'user@example.com', password: 'example-password' };
    const tokens = { access_token: 'example-access', refresh_token: 'example-refresh', token_type: 'bearer', expires_in: 3600 };
    mockedApi.login.mockResolvedValue(tokens);
    const { queryClient, wrapper } = createWrapper();
    queryClient.setQueryData(['currentUser'], user);
    const { result } = renderHook(() => useLogin(), { wrapper });

    await act(async () => { expect(await result.current.mutateAsync(credentials)).toEqual(tokens); });
    expect(mockedApi.login).toHaveBeenCalledWith(credentials);
    expect(queryClient.getQueryState(['currentUser'])?.isInvalidated).toBe(true);
  });

  it('logs out and clears the entire query cache', async () => {
    mockedApi.logout.mockResolvedValue(undefined);
    const { queryClient, wrapper } = createWrapper();
    queryClient.setQueryData(['currentUser'], user);
    queryClient.setQueryData(['watchlists'], [{ id: 1 }]);
    const { result } = renderHook(() => useLogout(), { wrapper });

    await act(async () => { await result.current.mutateAsync(); });
    expect(mockedApi.logout).toHaveBeenCalledOnce();
    expect(queryClient.getQueryCache().getAll()).toHaveLength(0);
  });

  it('logs out of all sessions and clears the cache', async () => {
    mockedApi.logoutAll.mockResolvedValue(undefined);
    const { queryClient, wrapper } = createWrapper();
    queryClient.setQueryData(['sessions'], [session]);
    const { result } = renderHook(() => useLogoutAll(), { wrapper });

    await act(async () => { await result.current.mutateAsync(); });
    expect(mockedApi.logoutAll).toHaveBeenCalledOnce();
    expect(queryClient.getQueryCache().getAll()).toHaveLength(0);
  });

  it('changes the password and clears the cache', async () => {
    const passwords = {
      current_password: 'old-example', new_password: 'new-example', new_password_confirm: 'new-example',
    };
    mockedApi.changePassword.mockResolvedValue(undefined);
    const { queryClient, wrapper } = createWrapper();
    queryClient.setQueryData(['currentUser'], user);
    const { result } = renderHook(() => useChangePassword(), { wrapper });

    await act(async () => { await result.current.mutateAsync(passwords); });
    expect(mockedApi.changePassword).toHaveBeenCalledWith(passwords);
    expect(queryClient.getQueryCache().getAll()).toHaveLength(0);
  });

  it('updates email and invalidates the current user', async () => {
    mockedApi.updateCurrentUser.mockResolvedValue({ ...user, email: 'updated@example.com' });
    const { queryClient, wrapper } = createWrapper();
    queryClient.setQueryData(['currentUser'], user);
    const { result } = renderHook(() => useUpdateEmail(), { wrapper });

    await act(async () => { await result.current.mutateAsync('updated@example.com'); });
    expect(mockedApi.updateCurrentUser).toHaveBeenCalledWith('updated@example.com');
    expect(queryClient.getQueryState(['currentUser'])?.isInvalidated).toBe(true);
  });

  it('fetches sessions only when authenticated', async () => {
    mockedApi.getSessions.mockResolvedValue([session]);
    const { wrapper } = createWrapper();
    const { result, rerender } = renderHook(() => useSessions(), { wrapper });

    expect(mockedApi.getSessions).not.toHaveBeenCalled();
    mockedApi.isAuthenticated.mockReturnValue(true);
    rerender();
    await waitFor(() => expect(result.current.data).toEqual([session]));
    expect(mockedApi.getSessions).toHaveBeenCalledOnce();
  });

  it('fetches app settings only when authenticated', async () => {
    mockedApi.getAppSettings.mockResolvedValue(settings);
    const { wrapper } = createWrapper();
    const { result, rerender } = renderHook(() => useAppSettings(), { wrapper });

    expect(mockedApi.getAppSettings).not.toHaveBeenCalled();
    mockedApi.isAuthenticated.mockReturnValue(true);
    rerender();
    await waitFor(() => expect(result.current.data).toEqual(settings));
    expect(mockedApi.getAppSettings).toHaveBeenCalledOnce();
  });

  it('updates app settings and invalidates their query', async () => {
    mockedApi.updateAppSettings.mockResolvedValue({ ...settings, theme: 'dark' });
    const { queryClient, wrapper } = createWrapper();
    queryClient.setQueryData(['appSettings'], settings);
    const { result } = renderHook(() => useUpdateAppSettings(), { wrapper });

    await act(async () => { await result.current.mutateAsync({ theme: 'dark' }); });
    expect(mockedApi.updateAppSettings).toHaveBeenCalledWith({ theme: 'dark' });
    expect(queryClient.getQueryState(['appSettings'])?.isInvalidated).toBe(true);
  });
});
