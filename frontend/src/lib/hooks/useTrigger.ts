'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import type { Trigger, TriggerCreate, TriggerUpdate } from '../api/types';

/**
 * Hook to fetch all triggers (the playbook), ordered by display_order
 */
export function useTriggers(includeRetired = false) {
  return useQuery<Trigger[]>({
    queryKey: ['triggers', { includeRetired }],
    queryFn: () => api.getTriggers(includeRetired),
  });
}

/**
 * Hook to fetch a single trigger
 */
export function useTrigger(id: number) {
  return useQuery<Trigger>({
    queryKey: ['trigger', id],
    queryFn: () => api.getTrigger(id),
    enabled: !!id,
  });
}

/**
 * Hook to create a trigger
 */
export function useCreateTrigger() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: TriggerCreate) => api.createTrigger(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['triggers'] });
    },
  });
}

/**
 * Hook to update a trigger (including its linked alerts)
 */
export function useUpdateTrigger() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id, data }: { id: number; data: TriggerUpdate }) =>
      api.updateTrigger(id, data),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['triggers'] });
      queryClient.invalidateQueries({ queryKey: ['trigger', variables.id] });
    },
  });
}

/**
 * Hook to delete a trigger
 */
export function useDeleteTrigger() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: number) => api.deleteTrigger(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['triggers'] });
    },
  });
}

/**
 * Hook to mark a trigger executed with an optional note
 */
export function useExecuteTrigger() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id, note }: { id: number; note?: string }) =>
      api.executeTrigger(id, note),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['triggers'] });
      queryClient.invalidateQueries({ queryKey: ['trigger', variables.id] });
    },
  });
}

/**
 * Hook to re-arm an executed trigger back to active
 */
export function useRearmTrigger() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: number) => api.rearmTrigger(id),
    onSuccess: (_, id) => {
      queryClient.invalidateQueries({ queryKey: ['triggers'] });
      queryClient.invalidateQueries({ queryKey: ['trigger', id] });
    },
  });
}
