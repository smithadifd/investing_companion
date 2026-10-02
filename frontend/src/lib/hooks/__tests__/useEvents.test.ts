import { beforeEach, describe, expect, it, vi } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { createElement, type ReactNode } from 'react';
import {
  useEvents,
  useUpcomingEvents,
  useCalendarMonth,
  useWatchlistEvents,
  useEventStats,
  useEvent,
  useEquityEvents,
  useCreateEvent,
  useUpdateEvent,
  useDeleteEvent,
  useRefreshEquityEvents,
  useRefreshWatchlistEvents,
  useDeleteEquityEvents,
} from '../useEvents';

vi.mock('../../api/client', () => ({
  api: {
    getEvents: vi.fn(),
    getUpcomingEvents: vi.fn(),
    getCalendarMonth: vi.fn(),
    getWatchlistEvents: vi.fn(),
    getEventStats: vi.fn(),
    getEvent: vi.fn(),
    getEquityEvents: vi.fn(),
    createEvent: vi.fn(),
    updateEvent: vi.fn(),
    deleteEvent: vi.fn(),
    refreshEquityEvents: vi.fn(),
    refreshWatchlistEvents: vi.fn(),
    deleteEquityEvents: vi.fn(),
  },
}));

import { api } from '../../api/client';
import type { EconomicEvent } from '../../api/types';

const mockedApi = vi.mocked(api);
const event: EconomicEvent = {
  id: 'event-1', event_type: 'custom', equity_id: null, user_id: null,
  event_date: '2026-10-02', event_time: null, all_day: true, title: 'Meeting',
  description: null, actual_value: null, forecast_value: null, previous_value: null,
  importance: 'medium', source: 'manual', is_confirmed: true, recurrence_key: null,
  created_at: '2026-10-01T00:00:00Z', updated_at: '2026-10-01T00:00:00Z', equity: null,
};

function createWrapper() {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
      mutations: { retry: false },
    },
  });
  const wrapper = ({ children }: { children: ReactNode }) =>
    createElement(QueryClientProvider, { client }, children);
  return { client, wrapper };
}

function expectOnlyKey(client: QueryClient, key: readonly unknown[]) {
  expect(client.getQueryCache().getAll().map((query) => query.queryKey)).toEqual([key]);
}

describe('event query hooks', () => {
  beforeEach(() => vi.clearAllMocks());

  it('fetches filtered events under the list key', async () => {
    const filters = { event_types: ['earnings'] as const, limit: 5, offset: 10 };
    mockedApi.getEvents.mockResolvedValue([]);
    const { client, wrapper } = createWrapper();
    const { result } = renderHook(() => useEvents({ ...filters, event_types: ['earnings'] }), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockedApi.getEvents).toHaveBeenCalledWith({ ...filters, event_types: ['earnings'] });
    expectOnlyKey(client, ['events', 'list', { ...filters, event_types: ['earnings'] }]);
  });

  it('fetches upcoming events under the days and filters key', async () => {
    const filters = { event_types: ['cpi'] as const, watchlist_only: true, limit: 4 };
    mockedApi.getUpcomingEvents.mockResolvedValue({ events: [], total: 0, days_ahead: 3 });
    const { client, wrapper } = createWrapper();
    const { result } = renderHook(() => useUpcomingEvents(3, { ...filters, event_types: ['cpi'] }), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockedApi.getUpcomingEvents).toHaveBeenCalledWith(3, { ...filters, event_types: ['cpi'] });
    expectOnlyKey(client, ['events', 'upcoming', 3, { ...filters, event_types: ['cpi'] }]);
  });

  it('fetches a calendar month under the year, month, and filters key', async () => {
    const filters = { watchlist_only: true };
    mockedApi.getCalendarMonth.mockResolvedValue({ year: 2026, month: 10, days: [], total_events: 0 });
    const { client, wrapper } = createWrapper();
    const { result } = renderHook(() => useCalendarMonth(2026, 10, filters), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockedApi.getCalendarMonth).toHaveBeenCalledWith(2026, 10, filters);
    expectOnlyKey(client, ['events', 'calendar', 2026, 10, filters]);
  });

  it('fetches watchlist events under the watchlist and days key', async () => {
    mockedApi.getWatchlistEvents.mockResolvedValue([]);
    const { client, wrapper } = createWrapper();
    const { result } = renderHook(() => useWatchlistEvents(8, 21), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockedApi.getWatchlistEvents).toHaveBeenCalledWith(8, 21);
    expectOnlyKey(client, ['events', 'watchlist', 8, 21]);
  });

  it('fetches statistics under the stats key', async () => {
    mockedApi.getEventStats.mockResolvedValue({ total_events: 0, earnings_this_week: 0, macro_events_this_week: 0, next_fomc_date: null, watchlist_earnings_upcoming: 0 });
    const { client, wrapper } = createWrapper();
    const { result } = renderHook(() => useEventStats(), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockedApi.getEventStats).toHaveBeenCalledOnce();
    expectOnlyKey(client, ['events', 'stats']);
  });

  it('fetches an event by id and waits for a nonempty id', async () => {
    mockedApi.getEvent.mockResolvedValue(event);
    const { client, wrapper } = createWrapper();
    const { result, rerender } = renderHook(({ id }) => useEvent(id), {
      initialProps: { id: '' }, wrapper,
    });
    expect(result.current.fetchStatus).toBe('idle');
    expect(mockedApi.getEvent).not.toHaveBeenCalled();
    expectOnlyKey(client, ['events', 'detail', '']);
    rerender({ id: 'event-1' });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockedApi.getEvent).toHaveBeenCalledWith('event-1');
    expect(client.getQueryCache().find({ queryKey: ['events', 'detail', 'event-1'], exact: true })).toBeDefined();
  });

  it('fetches equity events and waits for a nonempty symbol', async () => {
    mockedApi.getEquityEvents.mockResolvedValue([]);
    const { client, wrapper } = createWrapper();
    const { result, rerender } = renderHook(({ symbol }) => useEquityEvents(symbol, true, 6), {
      initialProps: { symbol: '' }, wrapper,
    });
    expect(result.current.fetchStatus).toBe('idle');
    expect(mockedApi.getEquityEvents).not.toHaveBeenCalled();
    expectOnlyKey(client, ['events', 'equity', '']);
    rerender({ symbol: 'AAPL' });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockedApi.getEquityEvents).toHaveBeenCalledWith('AAPL', true, 6);
    expect(client.getQueryCache().find({ queryKey: ['events', 'equity', 'AAPL'], exact: true })).toBeDefined();
  });
});

describe('event mutation hooks', () => {
  beforeEach(() => vi.clearAllMocks());

  it('creates an event and invalidates events', async () => {
    mockedApi.createEvent.mockResolvedValue(event);
    const { client, wrapper } = createWrapper();
    const invalidate = vi.spyOn(client, 'invalidateQueries');
    const { result } = renderHook(() => useCreateEvent(), { wrapper });
    const data = { event_type: 'custom' as const, event_date: '2026-10-02', title: 'Meeting' };
    result.current.mutate(data);
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockedApi.createEvent).toHaveBeenCalledWith(data);
    expect(invalidate).toHaveBeenCalledExactlyOnceWith({ queryKey: ['events'] });
  });

  it('updates an event and invalidates events', async () => {
    mockedApi.updateEvent.mockResolvedValue(event);
    const { client, wrapper } = createWrapper();
    const invalidate = vi.spyOn(client, 'invalidateQueries');
    const { result } = renderHook(() => useUpdateEvent(), { wrapper });
    result.current.mutate({ eventId: 'event-1', data: { title: 'Updated' } });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockedApi.updateEvent).toHaveBeenCalledWith('event-1', { title: 'Updated' });
    expect(invalidate).toHaveBeenCalledExactlyOnceWith({ queryKey: ['events'] });
  });

  it('deletes an event and invalidates events', async () => {
    mockedApi.deleteEvent.mockResolvedValue(undefined);
    const { client, wrapper } = createWrapper();
    const invalidate = vi.spyOn(client, 'invalidateQueries');
    const { result } = renderHook(() => useDeleteEvent(), { wrapper });
    result.current.mutate('event-1');
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockedApi.deleteEvent).toHaveBeenCalledWith('event-1');
    expect(invalidate).toHaveBeenCalledExactlyOnceWith({ queryKey: ['events'] });
  });

  it('refreshes equity events and invalidates events', async () => {
    mockedApi.refreshEquityEvents.mockResolvedValue([event]);
    const { client, wrapper } = createWrapper();
    const invalidate = vi.spyOn(client, 'invalidateQueries');
    const { result } = renderHook(() => useRefreshEquityEvents(), { wrapper });
    result.current.mutate('AAPL');
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockedApi.refreshEquityEvents).toHaveBeenCalledWith('AAPL');
    expect(invalidate).toHaveBeenCalledExactlyOnceWith({ queryKey: ['events'] });
  });

  it('refreshes watchlist events and invalidates events', async () => {
    mockedApi.refreshWatchlistEvents.mockResolvedValue({ events_updated: 1 });
    const { client, wrapper } = createWrapper();
    const invalidate = vi.spyOn(client, 'invalidateQueries');
    const { result } = renderHook(() => useRefreshWatchlistEvents(), { wrapper });
    result.current.mutate(8);
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockedApi.refreshWatchlistEvents).toHaveBeenCalledWith(8);
    expect(invalidate).toHaveBeenCalledExactlyOnceWith({ queryKey: ['events'] });
  });

  it('deletes equity events and invalidates events', async () => {
    mockedApi.deleteEquityEvents.mockResolvedValue({ symbol: 'AAPL', events_deleted: 1 });
    const { client, wrapper } = createWrapper();
    const invalidate = vi.spyOn(client, 'invalidateQueries');
    const { result } = renderHook(() => useDeleteEquityEvents(), { wrapper });
    result.current.mutate('AAPL');
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockedApi.deleteEquityEvents).toHaveBeenCalledWith('AAPL');
    expect(invalidate).toHaveBeenCalledExactlyOnceWith({ queryKey: ['events'] });
  });
});
