'use client';

import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';
import type {
  ExposureResponse,
  NeedsAttentionResponse,
  TradeReadinessResponse,
} from '../api/types';

/**
 * Hook to fetch the needs-attention list (the morning pulse's ⚡ section)
 */
export function useNeedsAttention() {
  return useQuery<NeedsAttentionResponse>({
    queryKey: ['dashboard', 'needs-attention'],
    queryFn: () => api.getNeedsAttention(),
    staleTime: 60 * 1000, // 1 minute
    refetchInterval: 5 * 60 * 1000, // 5 minutes
  });
}

/**
 * Hook to fetch trade readiness (actionable triggers with context)
 */
export function useTradeReadiness() {
  return useQuery<TradeReadinessResponse>({
    queryKey: ['dashboard', 'trade-readiness'],
    queryFn: () => api.getTradeReadiness(),
    staleTime: 60 * 1000, // 1 minute
    refetchInterval: 5 * 60 * 1000, // 5 minutes
  });
}

/**
 * Hook to fetch catalyst-cluster exposure (held value per catalyst)
 */
export function useExposure() {
  return useQuery<ExposureResponse>({
    queryKey: ['dashboard', 'exposure'],
    queryFn: () => api.getExposure(),
    staleTime: 60 * 1000, // 1 minute
  });
}
