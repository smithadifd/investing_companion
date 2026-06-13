'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import type { OutboxStatus } from '../api/types';

/**
 * Fetch the advisor context pack markdown on demand (copy/download).
 */
export function useContextPackMarkdown() {
  return useMutation({
    mutationFn: () => api.getContextPackMarkdown(),
  });
}

/**
 * Publish the context pack to the server outbox; refreshes outbox status.
 */
export function usePublishContextPack() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: () => api.publishContextPack(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['outbox-status'] });
    },
  });
}

/**
 * Whether the server has an outbox configured (gates the publish button).
 */
export function useOutboxStatus() {
  return useQuery<OutboxStatus>({
    queryKey: ['outbox-status'],
    queryFn: () => api.getOutboxStatus(),
  });
}
