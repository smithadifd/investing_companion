'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState, useCallback } from 'react';
import { api } from '../api/client';
import type { AIAnalysisRequest, AISettings, AISettingsUpdate } from '../api/types';

/**
 * Hook to fetch AI settings
 */
export function useAISettings() {
  return useQuery<AISettings>({
    queryKey: ['ai', 'settings'],
    queryFn: () => api.getAISettings(),
  });
}

/**
 * Hook to update AI settings
 */
export function useUpdateAISettings() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: AISettingsUpdate) => api.updateAISettings(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['ai', 'settings'] });
    },
  });
}

/**
 * Hook to perform AI analysis (non-streaming)
 */
export function useAIAnalysis() {
  return useMutation({
    mutationFn: (request: AIAnalysisRequest) => api.analyzeAI(request),
  });
}

/**
 * Hook to perform AI analysis with streaming
 */
export function useAIAnalysisStream() {
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamedText, setStreamedText] = useState('');
  const [error, setError] = useState<string | null>(null);

  const startStream = useCallback(async (request: AIAnalysisRequest) => {
    setIsStreaming(true);
    setStreamedText('');
    setError(null);

    try {
      for await (const chunk of api.analyzeAIStream(request)) {
        setStreamedText((prev) => prev + chunk);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Analysis failed');
    } finally {
      setIsStreaming(false);
    }
  }, []);

  const reset = useCallback(() => {
    setStreamedText('');
    setError(null);
  }, []);

  return {
    startStream,
    isStreaming,
    streamedText,
    error,
    reset,
  };
}
