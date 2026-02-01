'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import type {
  PerformanceReport,
  PortfolioSummary,
  PositionSizeRequest,
  PositionSizeResponse,
  PositionSummary,
  Trade,
  TradeCreate,
  TradePair,
  TradeType,
  TradeUpdate,
} from '../api/types';

/**
 * Hook to fetch trades with optional filters
 */
export function useTrades(params?: {
  equity_id?: number;
  trade_type?: TradeType;
  start_date?: string;
  end_date?: string;
  limit?: number;
  offset?: number;
}) {
  return useQuery({
    queryKey: ['trades', params],
    queryFn: () => api.getTrades(params),
  });
}

/**
 * Hook to fetch a single trade
 */
export function useTrade(id: number) {
  return useQuery<Trade>({
    queryKey: ['trade', id],
    queryFn: () => api.getTrade(id),
    enabled: !!id,
  });
}

/**
 * Hook to create a trade
 */
export function useCreateTrade() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: TradeCreate) => api.createTrade(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['trades'] });
      queryClient.invalidateQueries({ queryKey: ['portfolio'] });
      queryClient.invalidateQueries({ queryKey: ['performance'] });
      queryClient.invalidateQueries({ queryKey: ['trade-pairs'] });
    },
  });
}

/**
 * Hook to update a trade
 */
export function useUpdateTrade() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id, data }: { id: number; data: TradeUpdate }) =>
      api.updateTrade(id, data),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['trades'] });
      queryClient.invalidateQueries({ queryKey: ['trade', variables.id] });
      queryClient.invalidateQueries({ queryKey: ['portfolio'] });
      queryClient.invalidateQueries({ queryKey: ['performance'] });
      queryClient.invalidateQueries({ queryKey: ['trade-pairs'] });
    },
  });
}

/**
 * Hook to delete a trade
 */
export function useDeleteTrade() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: number) => api.deleteTrade(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['trades'] });
      queryClient.invalidateQueries({ queryKey: ['portfolio'] });
      queryClient.invalidateQueries({ queryKey: ['performance'] });
      queryClient.invalidateQueries({ queryKey: ['trade-pairs'] });
    },
  });
}

/**
 * Hook to fetch portfolio summary
 */
export function usePortfolio() {
  return useQuery<PortfolioSummary>({
    queryKey: ['portfolio'],
    queryFn: () => api.getPortfolio(),
    staleTime: 60 * 1000, // 1 minute
  });
}

/**
 * Hook to fetch performance report
 */
export function usePerformance(startDate?: string, endDate?: string) {
  return useQuery<PerformanceReport>({
    queryKey: ['performance', { startDate, endDate }],
    queryFn: () => api.getPerformance(startDate, endDate),
    staleTime: 60 * 1000, // 1 minute
  });
}

/**
 * Hook to fetch trade pairs
 */
export function useTradePairs(equityId?: number, limit = 100) {
  return useQuery<TradePair[]>({
    queryKey: ['trade-pairs', { equityId, limit }],
    queryFn: () => api.getTradePairs(equityId, limit),
  });
}

/**
 * Hook to fetch position for a specific equity
 */
export function usePosition(equityId: number) {
  return useQuery<PositionSummary>({
    queryKey: ['position', equityId],
    queryFn: () => api.getPosition(equityId),
    enabled: !!equityId,
  });
}

/**
 * Hook to calculate position size
 */
export function useCalculatePositionSize() {
  return useMutation<PositionSizeResponse, Error, PositionSizeRequest>({
    mutationFn: (data) => api.calculatePositionSize(data),
  });
}
