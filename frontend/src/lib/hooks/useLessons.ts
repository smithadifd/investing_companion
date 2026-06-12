'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import type { Lesson, LessonCreate, LessonUpdate } from '../api/types';

/**
 * Hook to fetch lessons (newest first), optionally filtered by symbol or tag
 */
export function useLessons(params?: { symbol?: string; tag?: string }) {
  return useQuery<Lesson[]>({
    queryKey: ['lessons', params],
    queryFn: () => api.getLessons(params),
  });
}

/**
 * Hook to capture a lesson
 */
export function useCreateLesson() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: LessonCreate) => api.createLesson(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['lessons'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard', 'trade-readiness'] });
    },
  });
}

/**
 * Hook to update a lesson
 */
export function useUpdateLesson() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id, data }: { id: number; data: LessonUpdate }) =>
      api.updateLesson(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['lessons'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard', 'trade-readiness'] });
    },
  });
}

/**
 * Hook to delete a lesson
 */
export function useDeleteLesson() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: number) => api.deleteLesson(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['lessons'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard', 'trade-readiness'] });
    },
  });
}
