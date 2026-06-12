'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import type { Account, AccountCreate, AccountUpdate } from '../api/types';

/**
 * Hook to fetch the user's accounts (ordered by display_order)
 */
export function useAccounts() {
  return useQuery<Account[]>({
    queryKey: ['accounts'],
    queryFn: () => api.getAccounts(),
    staleTime: 5 * 60 * 1000,
  });
}

/**
 * Hook to create an account
 */
export function useCreateAccount() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: AccountCreate) => api.createAccount(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['accounts'] });
    },
  });
}

/**
 * Hook to update an account
 */
export function useUpdateAccount() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: number; data: AccountUpdate }) =>
      api.updateAccount(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['accounts'] });
    },
  });
}

/**
 * Hook to delete an account (its trades become unassigned)
 */
export function useDeleteAccount() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.deleteAccount(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['accounts'] });
      queryClient.invalidateQueries({ queryKey: ['trades'] });
      queryClient.invalidateQueries({ queryKey: ['portfolio'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard', 'exposure'] });
    },
  });
}
