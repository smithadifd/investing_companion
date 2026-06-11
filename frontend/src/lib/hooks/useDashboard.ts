'use client';

import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';
import type { NeedsAttentionResponse } from '../api/types';

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
