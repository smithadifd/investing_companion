/**
 * Hooks for the Schwab connection (opt-in real-time quotes).
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api/client';

/**
 * Schwab connection status for the settings page
 */
export function useSchwabStatus() {
  return useQuery({
    queryKey: ['schwabStatus'],
    queryFn: () => api.getSchwabStatus(),
    enabled: api.isAuthenticated(),
    staleTime: 60 * 1000, // 1 minute
  });
}

/**
 * Start the Schwab OAuth flow. On success, redirect the browser to
 * the returned auth_url.
 */
export function useConnectSchwab() {
  return useMutation({
    mutationFn: () => api.connectSchwab(),
  });
}

/**
 * Disconnect Schwab (forgets the stored token)
 */
export function useDisconnectSchwab() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: () => api.disconnectSchwab(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['schwabStatus'] });
    },
  });
}
