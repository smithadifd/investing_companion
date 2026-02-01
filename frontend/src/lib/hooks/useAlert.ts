'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import type {
  Alert,
  AlertCheckResult,
  AlertCreate,
  AlertHistory,
  AlertStats,
  AlertUpdate,
  AlertWithHistory,
  NotificationStatus,
} from '../api/types';

/**
 * Hook to fetch all alerts
 */
export function useAlerts(activeOnly = false, equityId?: number, ratioId?: number) {
  return useQuery<Alert[]>({
    queryKey: ['alerts', { activeOnly, equityId, ratioId }],
    queryFn: () => api.getAlerts(activeOnly, equityId, ratioId),
  });
}

/**
 * Hook to fetch a single alert with history
 */
export function useAlert(id: number) {
  return useQuery<AlertWithHistory>({
    queryKey: ['alert', id],
    queryFn: () => api.getAlert(id),
    enabled: !!id,
  });
}

/**
 * Hook to fetch alert statistics
 */
export function useAlertStats() {
  return useQuery<AlertStats>({
    queryKey: ['alerts', 'stats'],
    queryFn: () => api.getAlertStats(),
    staleTime: 60 * 1000, // 1 minute
    refetchInterval: 60 * 1000,
  });
}

/**
 * Hook to fetch all alert history
 */
export function useAllAlertHistory(limit = 100, offset = 0) {
  return useQuery<AlertHistory[]>({
    queryKey: ['alerts', 'history', { limit, offset }],
    queryFn: () => api.getAllAlertHistory(limit, offset),
    staleTime: 30 * 1000, // 30 seconds
  });
}

/**
 * Hook to fetch history for a specific alert
 */
export function useAlertHistory(alertId: number, limit = 50) {
  return useQuery<AlertHistory[]>({
    queryKey: ['alert', alertId, 'history', { limit }],
    queryFn: () => api.getAlertHistory(alertId, limit),
    enabled: !!alertId,
    staleTime: 30 * 1000,
  });
}

/**
 * Hook to fetch notification status
 */
export function useNotificationStatus() {
  return useQuery<NotificationStatus>({
    queryKey: ['notifications', 'status'],
    queryFn: () => api.getNotificationStatus(),
  });
}

/**
 * Hook to create an alert
 */
export function useCreateAlert() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: AlertCreate) => api.createAlert(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['alerts'] });
    },
  });
}

/**
 * Hook to update an alert
 */
export function useUpdateAlert() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id, data }: { id: number; data: AlertUpdate }) =>
      api.updateAlert(id, data),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['alerts'] });
      queryClient.invalidateQueries({ queryKey: ['alert', variables.id] });
    },
  });
}

/**
 * Hook to delete an alert
 */
export function useDeleteAlert() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: number) => api.deleteAlert(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['alerts'] });
    },
  });
}

/**
 * Hook to toggle an alert's active state
 */
export function useToggleAlert() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: number) => api.toggleAlert(id),
    onSuccess: (_, id) => {
      queryClient.invalidateQueries({ queryKey: ['alerts'] });
      queryClient.invalidateQueries({ queryKey: ['alert', id] });
    },
  });
}

/**
 * Hook to manually check an alert
 */
export function useCheckAlert() {
  return useMutation<AlertCheckResult, Error, { alertId: number; notify?: boolean }>({
    mutationFn: ({ alertId, notify }) => api.checkAlert(alertId, notify),
  });
}

/**
 * Hook to test Discord notification
 */
export function useTestDiscordNotification() {
  return useMutation({
    mutationFn: () => api.testDiscordNotification(),
  });
}
