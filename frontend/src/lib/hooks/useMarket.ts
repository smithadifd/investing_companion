'use client';

import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';
import type { MarketOverview } from '../api/types';

/**
 * Hook to fetch market overview data
 */
export function useMarketOverview() {
  return useQuery<MarketOverview>({
    queryKey: ['market', 'overview'],
    queryFn: () => api.getMarketOverview(),
    staleTime: 60 * 1000, // 1 minute
    refetchInterval: 60 * 1000, // Refresh every minute
  });
}
