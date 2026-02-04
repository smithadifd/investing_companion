/**
 * React Query hooks for watchlist data
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api/client';
import type {
  WatchlistCreate,
  WatchlistImport,
  WatchlistItemCreate,
  WatchlistItemUpdate,
  WatchlistUpdate,
} from '@/lib/api/types';

/**
 * Get all watchlists
 */
export function useWatchlists() {
  return useQuery({
    queryKey: ['watchlists'],
    queryFn: () => api.getWatchlists(),
    staleTime: 60 * 1000, // 1 minute
  });
}

/**
 * Get top movers across all watchlists
 */
export function useAllWatchlistMovers(limit = 10) {
  return useQuery({
    queryKey: ['watchlists', 'movers', limit],
    queryFn: () => api.getAllWatchlistMovers(limit),
    staleTime: 60 * 1000, // 1 minute
  });
}

/**
 * Get a single watchlist with items
 */
export function useWatchlist(id: number | null, includeQuotes = true) {
  return useQuery({
    queryKey: ['watchlist', id, includeQuotes],
    queryFn: () => api.getWatchlist(id!, includeQuotes),
    enabled: id !== null,
    staleTime: 30 * 1000, // 30 seconds
  });
}

/**
 * Create a new watchlist
 */
export function useCreateWatchlist() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: WatchlistCreate) => api.createWatchlist(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['watchlists'] });
    },
  });
}

/**
 * Update a watchlist
 */
export function useUpdateWatchlist() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id, data }: { id: number; data: WatchlistUpdate }) =>
      api.updateWatchlist(id, data),
    onSuccess: (_, { id }) => {
      queryClient.invalidateQueries({ queryKey: ['watchlists'] });
      queryClient.invalidateQueries({ queryKey: ['watchlist', id] });
    },
  });
}

/**
 * Delete a watchlist
 */
export function useDeleteWatchlist() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: number) => api.deleteWatchlist(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['watchlists'] });
    },
  });
}

/**
 * Add an item to a watchlist
 */
export function useAddWatchlistItem() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      watchlistId,
      data,
    }: {
      watchlistId: number;
      data: WatchlistItemCreate;
    }) => api.addWatchlistItem(watchlistId, data),
    onSuccess: (_, { watchlistId }) => {
      queryClient.invalidateQueries({ queryKey: ['watchlists'] });
      queryClient.invalidateQueries({ queryKey: ['watchlist', watchlistId] });
    },
  });
}

/**
 * Update a watchlist item
 */
export function useUpdateWatchlistItem() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      watchlistId,
      itemId,
      data,
    }: {
      watchlistId: number;
      itemId: number;
      data: WatchlistItemUpdate;
    }) => api.updateWatchlistItem(watchlistId, itemId, data),
    onSuccess: (_, { watchlistId }) => {
      queryClient.invalidateQueries({ queryKey: ['watchlist', watchlistId] });
    },
  });
}

/**
 * Remove an item from a watchlist
 */
export function useRemoveWatchlistItem() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      watchlistId,
      itemId,
    }: {
      watchlistId: number;
      itemId: number;
    }) => api.removeWatchlistItem(watchlistId, itemId),
    onSuccess: (_, { watchlistId }) => {
      queryClient.invalidateQueries({ queryKey: ['watchlists'] });
      queryClient.invalidateQueries({ queryKey: ['watchlist', watchlistId] });
    },
  });
}

/**
 * Export a watchlist
 */
export function useExportWatchlist() {
  return useMutation({
    mutationFn: (id: number) => api.exportWatchlist(id),
  });
}

/**
 * Import a watchlist
 */
export function useImportWatchlist() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: WatchlistImport) => api.importWatchlist(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['watchlists'] });
    },
  });
}
