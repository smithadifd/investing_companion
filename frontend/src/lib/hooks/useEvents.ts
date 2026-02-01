'use client';

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api/client';
import type {
  CalendarMonth,
  EconomicEvent,
  EconomicEventCreate,
  EconomicEventUpdate,
  EventFilters,
  EventStats,
  EventType,
  UpcomingEventsResponse,
} from '@/lib/api/types';

// Query keys
const eventKeys = {
  all: ['events'] as const,
  lists: () => [...eventKeys.all, 'list'] as const,
  list: (filters?: EventFilters) => [...eventKeys.lists(), filters] as const,
  upcoming: (days?: number, filters?: { event_types?: EventType[]; watchlist_only?: boolean }) =>
    [...eventKeys.all, 'upcoming', days, filters] as const,
  calendar: (year: number, month: number, filters?: { event_types?: EventType[]; watchlist_only?: boolean }) =>
    [...eventKeys.all, 'calendar', year, month, filters] as const,
  watchlist: (watchlistId?: number, days?: number) =>
    [...eventKeys.all, 'watchlist', watchlistId, days] as const,
  stats: () => [...eventKeys.all, 'stats'] as const,
  detail: (id: string) => [...eventKeys.all, 'detail', id] as const,
  equity: (symbol: string) => [...eventKeys.all, 'equity', symbol] as const,
};

/**
 * Hook to fetch events with filtering
 */
export function useEvents(filters?: EventFilters & { limit?: number; offset?: number }) {
  return useQuery({
    queryKey: eventKeys.list(filters),
    queryFn: () => api.getEvents(filters),
  });
}

/**
 * Hook to fetch upcoming events
 */
export function useUpcomingEvents(
  days = 7,
  filters?: { event_types?: EventType[]; watchlist_only?: boolean; limit?: number }
) {
  return useQuery({
    queryKey: eventKeys.upcoming(days, filters),
    queryFn: () => api.getUpcomingEvents(days, filters),
  });
}

/**
 * Hook to fetch calendar month data
 */
export function useCalendarMonth(
  year: number,
  month: number,
  filters?: { event_types?: EventType[]; watchlist_only?: boolean }
) {
  return useQuery({
    queryKey: eventKeys.calendar(year, month, filters),
    queryFn: () => api.getCalendarMonth(year, month, filters),
  });
}

/**
 * Hook to fetch watchlist events
 */
export function useWatchlistEvents(watchlistId?: number, days = 14) {
  return useQuery({
    queryKey: eventKeys.watchlist(watchlistId, days),
    queryFn: () => api.getWatchlistEvents(watchlistId, days),
  });
}

/**
 * Hook to fetch event statistics
 */
export function useEventStats() {
  return useQuery({
    queryKey: eventKeys.stats(),
    queryFn: () => api.getEventStats(),
  });
}

/**
 * Hook to fetch a single event
 */
export function useEvent(eventId: string) {
  return useQuery({
    queryKey: eventKeys.detail(eventId),
    queryFn: () => api.getEvent(eventId),
    enabled: !!eventId,
  });
}

/**
 * Hook to fetch events for a specific equity
 */
export function useEquityEvents(symbol: string, includePast = false, limit = 10) {
  return useQuery({
    queryKey: eventKeys.equity(symbol),
    queryFn: () => api.getEquityEvents(symbol, includePast, limit),
    enabled: !!symbol,
  });
}

/**
 * Hook to create a custom event
 */
export function useCreateEvent() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: EconomicEventCreate) => api.createEvent(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: eventKeys.all });
    },
  });
}

/**
 * Hook to update an event
 */
export function useUpdateEvent() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ eventId, data }: { eventId: string; data: EconomicEventUpdate }) =>
      api.updateEvent(eventId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: eventKeys.all });
    },
  });
}

/**
 * Hook to delete an event
 */
export function useDeleteEvent() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (eventId: string) => api.deleteEvent(eventId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: eventKeys.all });
    },
  });
}

/**
 * Hook to refresh events for an equity
 */
export function useRefreshEquityEvents() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (symbol: string) => api.refreshEquityEvents(symbol),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: eventKeys.all });
    },
  });
}

/**
 * Hook to refresh watchlist events
 */
export function useRefreshWatchlistEvents() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (watchlistId?: number) => api.refreshWatchlistEvents(watchlistId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: eventKeys.all });
    },
  });
}
