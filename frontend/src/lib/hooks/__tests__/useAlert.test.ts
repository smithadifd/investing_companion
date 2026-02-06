import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { createElement } from 'react';
import {
  useAlerts,
  useAlert,
  useAlertStats,
  useCreateAlert,
  useUpdateAlert,
  useDeleteAlert,
  useToggleAlert,
  useCheckAlert,
} from '../useAlert';
import type { Alert, AlertCreate, AlertStats, AlertWithHistory } from '../../api/types';

vi.mock('../../api/client', () => ({
  api: {
    getAlerts: vi.fn(),
    getAlert: vi.fn(),
    getAlertStats: vi.fn(),
    createAlert: vi.fn(),
    updateAlert: vi.fn(),
    deleteAlert: vi.fn(),
    toggleAlert: vi.fn(),
    checkAlert: vi.fn(),
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

const mockAlert: Alert = {
  id: 1,
  name: 'AAPL Above $200',
  notes: null,
  equity_id: 1,
  ratio_id: null,
  condition_type: 'above',
  threshold_value: 200,
  comparison_period: null,
  cooldown_minutes: 60,
  is_active: true,
  last_triggered_at: null,
  last_checked_value: 195.5,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  target: { type: 'equity', id: 1, symbol: 'AAPL', name: 'Apple Inc.' },
};

const mockStats: AlertStats = {
  total_alerts: 5,
  active_alerts: 3,
  triggered_today: 1,
  triggered_this_week: 4,
};

describe('useAlerts', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('fetches alerts with default params', async () => {
    mockedApi.getAlerts.mockResolvedValue([mockAlert]);
    const { result } = renderHook(() => useAlerts(), { wrapper: createWrapper() });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockedApi.getAlerts).toHaveBeenCalledWith(false, undefined, undefined);
    expect(result.current.data).toEqual([mockAlert]);
  });

  it('passes activeOnly filter', async () => {
    mockedApi.getAlerts.mockResolvedValue([mockAlert]);
    const { result } = renderHook(() => useAlerts(true), { wrapper: createWrapper() });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockedApi.getAlerts).toHaveBeenCalledWith(true, undefined, undefined);
  });

  it('passes equityId and ratioId filters', async () => {
    mockedApi.getAlerts.mockResolvedValue([]);
    const { result } = renderHook(() => useAlerts(false, 5, 10), { wrapper: createWrapper() });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockedApi.getAlerts).toHaveBeenCalledWith(false, 5, 10);
  });

  it('surfaces error state', async () => {
    mockedApi.getAlerts.mockRejectedValue(new Error('Network error'));
    const { result } = renderHook(() => useAlerts(), { wrapper: createWrapper() });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.message).toBe('Network error');
  });
});

describe('useAlert', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('fetches single alert with history', async () => {
    const mockWithHistory: AlertWithHistory = { ...mockAlert, recent_history: [] };
    mockedApi.getAlert.mockResolvedValue(mockWithHistory);
    const { result } = renderHook(() => useAlert(1), { wrapper: createWrapper() });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockedApi.getAlert).toHaveBeenCalledWith(1);
    expect(result.current.data).toEqual(mockWithHistory);
  });

  it('does not fetch when id is falsy', () => {
    renderHook(() => useAlert(0), { wrapper: createWrapper() });
    expect(mockedApi.getAlert).not.toHaveBeenCalled();
  });
});

describe('useAlertStats', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('fetches alert stats', async () => {
    mockedApi.getAlertStats.mockResolvedValue(mockStats);
    const { result } = renderHook(() => useAlertStats(), { wrapper: createWrapper() });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(mockStats);
  });
});

describe('useCreateAlert', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('calls createAlert API and invalidates alerts query', async () => {
    const newAlert: AlertCreate = {
      name: 'AAPL Below $180',
      equity_symbol: 'AAPL',
      condition_type: 'below',
      threshold_value: 180,
      cooldown_minutes: 60,
    };
    mockedApi.createAlert.mockResolvedValue({ ...mockAlert, ...newAlert, id: 2 });

    const wrapper = createWrapper();
    const { result } = renderHook(() => useCreateAlert(), { wrapper });

    result.current.mutate(newAlert);
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockedApi.createAlert).toHaveBeenCalledWith(newAlert);
  });
});

describe('useUpdateAlert', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('calls updateAlert with id and data', async () => {
    mockedApi.updateAlert.mockResolvedValue({ ...mockAlert, name: 'Updated' });

    const { result } = renderHook(() => useUpdateAlert(), { wrapper: createWrapper() });

    result.current.mutate({ id: 1, data: { name: 'Updated' } });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockedApi.updateAlert).toHaveBeenCalledWith(1, { name: 'Updated' });
  });
});

describe('useDeleteAlert', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('calls deleteAlert with id', async () => {
    mockedApi.deleteAlert.mockResolvedValue(undefined);

    const { result } = renderHook(() => useDeleteAlert(), { wrapper: createWrapper() });

    result.current.mutate(1);
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockedApi.deleteAlert).toHaveBeenCalledWith(1);
  });
});

describe('useToggleAlert', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('calls toggleAlert with id', async () => {
    mockedApi.toggleAlert.mockResolvedValue({ ...mockAlert, is_active: false });

    const { result } = renderHook(() => useToggleAlert(), { wrapper: createWrapper() });

    result.current.mutate(1);
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockedApi.toggleAlert).toHaveBeenCalledWith(1);
  });
});

describe('useCheckAlert', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('calls checkAlert with alertId and notify flag', async () => {
    const checkResult = {
      alert_id: 1,
      is_triggered: true,
      current_value: 205,
      threshold_value: 200,
      condition_met: 'Current value 205 is above threshold 200',
      should_notify: true,
    };
    mockedApi.checkAlert.mockResolvedValue(checkResult);

    const { result } = renderHook(() => useCheckAlert(), { wrapper: createWrapper() });

    result.current.mutate({ alertId: 1, notify: false });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockedApi.checkAlert).toHaveBeenCalledWith(1, false);
    expect(result.current.data).toEqual(checkResult);
  });
});
