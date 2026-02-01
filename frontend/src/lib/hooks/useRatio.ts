'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import type { Ratio, RatioCreate, RatioHistory, RatioQuote, RatioUpdate } from '../api/types';

/**
 * Hook to fetch all ratios
 */
export function useRatios(favoritesOnly = false, category?: string) {
  return useQuery<Ratio[]>({
    queryKey: ['ratios', { favoritesOnly, category }],
    queryFn: () => api.getRatios(favoritesOnly, category),
  });
}

/**
 * Hook to fetch a single ratio
 */
export function useRatio(id: number) {
  return useQuery<Ratio>({
    queryKey: ['ratio', id],
    queryFn: () => api.getRatio(id),
    enabled: !!id,
  });
}

/**
 * Hook to fetch all ratio quotes
 */
export function useRatioQuotes() {
  return useQuery<RatioQuote[]>({
    queryKey: ['ratios', 'quotes'],
    queryFn: () => api.getRatioQuotes(),
    staleTime: 60 * 1000, // 1 minute
    refetchInterval: 60 * 1000,
  });
}

/**
 * Hook to fetch a single ratio quote
 */
export function useRatioQuote(id: number) {
  return useQuery<RatioQuote>({
    queryKey: ['ratio', id, 'quote'],
    queryFn: () => api.getRatioQuote(id),
    enabled: !!id,
    staleTime: 60 * 1000,
    refetchInterval: 60 * 1000,
  });
}

/**
 * Hook to fetch ratio history
 */
export function useRatioHistory(id: number, period = '1y') {
  return useQuery<RatioHistory>({
    queryKey: ['ratio', id, 'history', period],
    queryFn: () => api.getRatioHistory(id, period),
    enabled: !!id,
    staleTime: 5 * 60 * 1000, // 5 minutes
  });
}

/**
 * Hook to create a ratio
 */
export function useCreateRatio() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: RatioCreate) => api.createRatio(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['ratios'] });
    },
  });
}

/**
 * Hook to update a ratio
 */
export function useUpdateRatio() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id, data }: { id: number; data: RatioUpdate }) =>
      api.updateRatio(id, data),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['ratios'] });
      queryClient.invalidateQueries({ queryKey: ['ratio', variables.id] });
    },
  });
}

/**
 * Hook to delete a ratio
 */
export function useDeleteRatio() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: number) => api.deleteRatio(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['ratios'] });
    },
  });
}

/**
 * Hook to toggle ratio favorite
 */
export function useToggleRatioFavorite() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id, isFavorite }: { id: number; isFavorite: boolean }) =>
      api.updateRatio(id, { is_favorite: isFavorite }),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['ratios'] });
      queryClient.invalidateQueries({ queryKey: ['ratio', variables.id] });
    },
  });
}

/**
 * Hook to initialize system ratios
 */
export function useInitializeRatios() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: () => api.initializeRatios(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['ratios'] });
    },
  });
}
