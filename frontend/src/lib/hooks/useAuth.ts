/**
 * React Query hooks for authentication
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api/client';
import type {
  AppSettingsUpdate,
  PasswordChange,
  UserCreate,
  UserLogin,
} from '@/lib/api/types';

/**
 * Get current user
 */
export function useCurrentUser() {
  return useQuery({
    queryKey: ['currentUser'],
    queryFn: () => api.getCurrentUser(),
    enabled: api.isAuthenticated(),
    staleTime: 5 * 60 * 1000, // 5 minutes
    retry: false,
  });
}

/**
 * Get registration status
 */
export function useRegistrationStatus() {
  return useQuery({
    queryKey: ['registrationStatus'],
    queryFn: () => api.getRegistrationStatus(),
    staleTime: 60 * 60 * 1000, // 1 hour
  });
}

/**
 * Register new user
 */
export function useRegister() {
  return useMutation({
    mutationFn: (data: UserCreate) => api.register(data),
  });
}

/**
 * Login mutation
 */
export function useLogin() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: UserLogin) => api.login(data),
    onSuccess: () => {
      // Refetch current user after login
      queryClient.invalidateQueries({ queryKey: ['currentUser'] });
    },
  });
}

/**
 * Logout mutation
 */
export function useLogout() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: () => api.logout(),
    onSuccess: () => {
      // Clear all cached data on logout
      queryClient.clear();
    },
  });
}

/**
 * Logout from all sessions
 */
export function useLogoutAll() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: () => api.logoutAll(),
    onSuccess: () => {
      queryClient.clear();
    },
  });
}

/**
 * Change password
 */
export function useChangePassword() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: PasswordChange) => api.changePassword(data),
    onSuccess: () => {
      // Clear all cached data after password change
      queryClient.clear();
    },
  });
}

/**
 * Update user email
 */
export function useUpdateEmail() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (email: string) => api.updateCurrentUser(email),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['currentUser'] });
    },
  });
}

/**
 * Get user sessions
 */
export function useSessions() {
  return useQuery({
    queryKey: ['sessions'],
    queryFn: () => api.getSessions(),
    enabled: api.isAuthenticated(),
    staleTime: 60 * 1000, // 1 minute
  });
}

/**
 * Get app settings
 */
export function useAppSettings() {
  return useQuery({
    queryKey: ['appSettings'],
    queryFn: () => api.getAppSettings(),
    enabled: api.isAuthenticated(),
    staleTime: 5 * 60 * 1000, // 5 minutes
  });
}

/**
 * Update app settings
 */
export function useUpdateAppSettings() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: AppSettingsUpdate) => api.updateAppSettings(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['appSettings'] });
    },
  });
}
