/**
 * React Query hooks for equity data
 */

import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api/client';

/**
 * Search for equities by symbol or name
 */
export function useEquitySearch(query: string, enabled = true) {
  return useQuery({
    queryKey: ['equity', 'search', query],
    queryFn: () => api.searchEquities(query),
    enabled: enabled && query.length > 0,
    staleTime: 30 * 1000, // 30 seconds
  });
}

/**
 * Get equity details including quote and fundamentals
 */
export function useEquity(symbol: string) {
  return useQuery({
    queryKey: ['equity', symbol],
    queryFn: () => api.getEquity(symbol),
    enabled: !!symbol,
    staleTime: 60 * 1000, // 1 minute
  });
}

/**
 * Get current quote for an equity
 */
export function useQuote(symbol: string) {
  return useQuery({
    queryKey: ['equity', symbol, 'quote'],
    queryFn: () => api.getQuote(symbol),
    enabled: !!symbol,
    staleTime: 15 * 1000, // 15 seconds - matches backend cache TTL
    refetchInterval: 60 * 1000, // Refetch every minute
  });
}

/**
 * Get historical price data
 */
export function useHistory(symbol: string, period = '1y', interval = '1d') {
  return useQuery({
    queryKey: ['equity', symbol, 'history', period, interval],
    queryFn: () => api.getHistory(symbol, period, interval),
    enabled: !!symbol,
    staleTime: 5 * 60 * 1000, // 5 minutes
  });
}

/**
 * Get technical indicators
 */
export function useTechnicals(symbol: string, period = '1y') {
  return useQuery({
    queryKey: ['equity', symbol, 'technicals', period],
    queryFn: () => api.getTechnicals(symbol, period),
    enabled: !!symbol,
    staleTime: 5 * 60 * 1000, // 5 minutes
  });
}

/**
 * Get technical indicators summary
 */
export function useTechnicalsSummary(symbol: string) {
  return useQuery({
    queryKey: ['equity', symbol, 'technicals', 'summary'],
    queryFn: () => api.getTechnicalsSummary(symbol),
    enabled: !!symbol,
    staleTime: 60 * 1000, // 1 minute
  });
}

/**
 * Get peer companies for comparison
 */
export function usePeers(symbol: string, limit = 5) {
  return useQuery({
    queryKey: ['equity', symbol, 'peers', limit],
    queryFn: () => api.getPeers(symbol, limit),
    enabled: !!symbol,
    staleTime: 10 * 60 * 1000, // 10 minutes - peers don't change often
  });
}
