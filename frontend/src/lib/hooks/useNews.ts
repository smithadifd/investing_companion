/**
 * React Query hooks for news data
 */

import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api/client';

/**
 * Get news for a specific symbol
 */
export function useSymbolNews(symbol: string, limit = 10) {
  return useQuery({
    queryKey: ['news', 'symbol', symbol, limit],
    queryFn: () => api.getSymbolNews(symbol, limit),
    enabled: !!symbol,
    staleTime: 5 * 60 * 1000, // 5 minutes
    refetchInterval: 10 * 60 * 1000, // Refetch every 10 minutes
  });
}

/**
 * Get general market news
 */
export function useMarketNews(limit = 20) {
  return useQuery({
    queryKey: ['news', 'market', limit],
    queryFn: () => api.getMarketNews(limit),
    staleTime: 10 * 60 * 1000, // 10 minutes
    refetchInterval: 15 * 60 * 1000, // Refetch every 15 minutes
  });
}

/**
 * Get aggregated news for all watchlist symbols
 */
export function useWatchlistNews(limit = 20) {
  return useQuery({
    queryKey: ['news', 'watchlist', limit],
    queryFn: () => api.getWatchlistNews(limit),
    staleTime: 5 * 60 * 1000, // 5 minutes
    refetchInterval: 10 * 60 * 1000, // Refetch every 10 minutes
  });
}
