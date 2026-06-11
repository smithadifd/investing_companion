import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { createElement } from 'react';
import {
  useTriggers,
  useTrigger,
  useCreateTrigger,
  useUpdateTrigger,
  useDeleteTrigger,
  useExecuteTrigger,
  useRearmTrigger,
} from '../useTrigger';
import type { Trigger, TriggerCreate } from '../../api/types';

vi.mock('../../api/client', () => ({
  api: {
    getTriggers: vi.fn(),
    getTrigger: vi.fn(),
    createTrigger: vi.fn(),
    updateTrigger: vi.fn(),
    deleteTrigger: vi.fn(),
    executeTrigger: vi.fn(),
    rearmTrigger: vi.fn(),
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

const mockTrigger: Trigger = {
  id: 1,
  name: 'SPY Crisis Tier 1',
  rule: 'SPY closes 10% below its 1y high',
  action: 'Deploy first tranche',
  tier: 'yellow',
  display_order: 1,
  status: 'active',
  signal: 'armed',
  executed_at: null,
  execution_note: null,
  alerts: [
    {
      id: 10,
      name: 'SPY % From High 10%',
      is_active: true,
      distance_percent: '2.5',
      last_triggered_at: null,
    },
  ],
  created_at: '2026-06-11T00:00:00Z',
};

describe('useTriggers', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('fetches triggers without retired by default', async () => {
    mockedApi.getTriggers.mockResolvedValue([mockTrigger]);
    const { result } = renderHook(() => useTriggers(), { wrapper: createWrapper() });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockedApi.getTriggers).toHaveBeenCalledWith(false);
    expect(result.current.data).toEqual([mockTrigger]);
  });

  it('passes includeRetired flag', async () => {
    mockedApi.getTriggers.mockResolvedValue([]);
    const { result } = renderHook(() => useTriggers(true), { wrapper: createWrapper() });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockedApi.getTriggers).toHaveBeenCalledWith(true);
  });

  it('surfaces error state', async () => {
    mockedApi.getTriggers.mockRejectedValue(new Error('Network error'));
    const { result } = renderHook(() => useTriggers(), { wrapper: createWrapper() });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.message).toBe('Network error');
  });
});

describe('useTrigger', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('fetches a single trigger', async () => {
    mockedApi.getTrigger.mockResolvedValue(mockTrigger);
    const { result } = renderHook(() => useTrigger(1), { wrapper: createWrapper() });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockedApi.getTrigger).toHaveBeenCalledWith(1);
    expect(result.current.data).toEqual(mockTrigger);
  });

  it('does not fetch when id is falsy', () => {
    renderHook(() => useTrigger(0), { wrapper: createWrapper() });
    expect(mockedApi.getTrigger).not.toHaveBeenCalled();
  });
});

describe('useCreateTrigger', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('calls createTrigger API', async () => {
    const newTrigger: TriggerCreate = {
      name: 'LNG Stop Loss',
      rule: 'LNG closes below $170',
      action: 'Sell the full position',
      tier: 'red',
      display_order: 0,
      alert_ids: [11],
    };
    mockedApi.createTrigger.mockResolvedValue({ ...mockTrigger, ...newTrigger, id: 2 });

    const { result } = renderHook(() => useCreateTrigger(), { wrapper: createWrapper() });

    result.current.mutate(newTrigger);
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockedApi.createTrigger).toHaveBeenCalledWith(newTrigger);
  });
});

describe('useUpdateTrigger', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('calls updateTrigger with id and data', async () => {
    mockedApi.updateTrigger.mockResolvedValue({ ...mockTrigger, name: 'Updated' });

    const { result } = renderHook(() => useUpdateTrigger(), { wrapper: createWrapper() });

    result.current.mutate({ id: 1, data: { name: 'Updated' } });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockedApi.updateTrigger).toHaveBeenCalledWith(1, { name: 'Updated' });
  });
});

describe('useDeleteTrigger', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('calls deleteTrigger with id', async () => {
    mockedApi.deleteTrigger.mockResolvedValue(undefined);

    const { result } = renderHook(() => useDeleteTrigger(), { wrapper: createWrapper() });

    result.current.mutate(1);
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockedApi.deleteTrigger).toHaveBeenCalledWith(1);
  });
});

describe('useExecuteTrigger', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('calls executeTrigger with id and note', async () => {
    mockedApi.executeTrigger.mockResolvedValue({
      ...mockTrigger,
      status: 'executed',
      execution_note: 'Bought the dip',
    });

    const { result } = renderHook(() => useExecuteTrigger(), { wrapper: createWrapper() });

    result.current.mutate({ id: 1, note: 'Bought the dip' });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockedApi.executeTrigger).toHaveBeenCalledWith(1, 'Bought the dip');
  });
});

describe('useRearmTrigger', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('calls rearmTrigger with id', async () => {
    mockedApi.rearmTrigger.mockResolvedValue({ ...mockTrigger, status: 'active' });

    const { result } = renderHook(() => useRearmTrigger(), { wrapper: createWrapper() });

    result.current.mutate(1);
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockedApi.rearmTrigger).toHaveBeenCalledWith(1);
  });
});
