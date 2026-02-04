'use client';

import { useState, useRef, useEffect } from 'react';
import { Bot, Send, Settings, Loader2, AlertCircle, Sparkles } from 'lucide-react';
import { useAISettings, useAIAnalysisStream } from '@/lib/hooks/useAI';
import type { AnalysisType, AIModel } from '@/lib/api/types';
import { AISettingsModal } from './AISettingsModal';

interface Message {
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
}

interface AIAnalysisPanelProps {
  analysisType: AnalysisType;
  symbol?: string;
  ratioId?: number;
  watchlistId?: number;
  contextLabel?: string;
}

const SUGGESTED_PROMPTS: Record<AnalysisType, string[]> = {
  equity: [
    "What's the bull and bear case?",
    "Analyze the valuation metrics",
    "What are the key risks?",
    "Compare to sector peers",
  ],
  ratio: [
    "What does this ratio indicate?",
    "What's the historical context?",
    "What drives changes in this ratio?",
  ],
  watchlist: [
    "Summarize my holdings",
    "Flag any concerns",
    "Suggest rebalancing ideas",
  ],
  general: [
    "Explain this concept",
    "What should I consider?",
  ],
};

export function AIAnalysisPanel({
  analysisType,
  symbol,
  ratioId,
  watchlistId,
  contextLabel,
}: AIAnalysisPanelProps) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [showSettings, setShowSettings] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const { data: settings, isLoading: settingsLoading } = useAISettings();
  const { startStream, isStreaming, streamedText, error, reset } = useAIAnalysisStream();

  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, streamedText]);

  // Add streamed response to messages when complete
  useEffect(() => {
    if (!isStreaming && streamedText && messages.length > 0) {
      const lastMessage = messages[messages.length - 1];
      if (lastMessage.role === 'user') {
        setMessages((prev) => [
          ...prev,
          {
            role: 'assistant',
            content: streamedText,
            timestamp: new Date(),
          },
        ]);
        reset();
      }
    }
  }, [isStreaming, streamedText, messages, reset]);

  const handleSubmit = async (prompt: string) => {
    if (!prompt.trim() || isStreaming) return;

    // Add user message
    setMessages((prev) => [
      ...prev,
      {
        role: 'user',
        content: prompt,
        timestamp: new Date(),
      },
    ]);
    setInput('');

    // Start streaming analysis
    await startStream({
      analysis_type: analysisType,
      prompt,
      symbol,
      ratio_id: ratioId,
      watchlist_id: watchlistId,
      model: (settings?.default_model as AIModel) || 'claude-3-5-sonnet-20241022',
      include_context: true,
    });
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(input);
    }
  };

  if (settingsLoading) {
    return (
      <div className="bg-white dark:bg-neutral-800 rounded-lg border border-neutral-200 dark:border-neutral-700 p-6">
        <div className="flex items-center justify-center h-40">
          <Loader2 className="h-6 w-6 animate-spin text-blue-500" />
        </div>
      </div>
    );
  }

  if (!settings?.has_api_key) {
    return (
      <div className="bg-white dark:bg-neutral-800 rounded-lg border border-neutral-200 dark:border-neutral-700 p-6">
        <div className="text-center py-8">
          <Bot className="h-12 w-12 text-neutral-400 mx-auto mb-4" />
          <h3 className="text-lg font-semibold text-neutral-900 dark:text-neutral-50 mb-2">
            AI Analysis
          </h3>
          <p className="text-neutral-500 mb-4">
            Configure your Claude API key to enable AI-powered analysis
          </p>
          <button
            onClick={() => setShowSettings(true)}
            className="inline-flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
          >
            <Settings className="h-4 w-4" />
            Configure API Key
          </button>
        </div>
        <AISettingsModal
          isOpen={showSettings}
          onClose={() => setShowSettings(false)}
        />
      </div>
    );
  }

  return (
    <div className="bg-white dark:bg-neutral-800 rounded-lg border border-neutral-200 dark:border-neutral-700 flex flex-col h-[60vh] min-h-[300px] max-h-[500px] sm:h-[500px]">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-neutral-200 dark:border-neutral-700">
        <div className="flex items-center gap-2">
          <Sparkles className="h-5 w-5 text-blue-500" />
          <h2 className="font-semibold text-neutral-900 dark:text-neutral-50">
            AI Analysis
          </h2>
          {contextLabel && (
            <span className="text-sm text-neutral-500">
              - {contextLabel}
            </span>
          )}
        </div>
        <button
          onClick={() => setShowSettings(true)}
          className="p-2 text-neutral-500 hover:text-neutral-700 dark:hover:text-neutral-300 hover:bg-neutral-100 dark:hover:bg-neutral-700 rounded-lg transition-colors"
        >
          <Settings className="h-4 w-4" />
        </button>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.length === 0 && !isStreaming && (
          <div className="text-center py-8">
            <Bot className="h-10 w-10 text-neutral-300 dark:text-neutral-600 mx-auto mb-3" />
            <p className="text-sm text-neutral-500 mb-4">
              Ask me anything about {contextLabel || 'this topic'}
            </p>
            <div className="flex flex-wrap gap-2 justify-center">
              {SUGGESTED_PROMPTS[analysisType].map((prompt) => (
                <button
                  key={prompt}
                  onClick={() => handleSubmit(prompt)}
                  className="px-3 py-1.5 text-sm bg-neutral-100 dark:bg-neutral-700 text-neutral-700 dark:text-neutral-300 rounded-full hover:bg-neutral-200 dark:hover:bg-neutral-600 transition-colors"
                >
                  {prompt}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((message, i) => (
          <div
            key={i}
            className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}
          >
            <div
              className={`max-w-[85%] rounded-lg px-4 py-2 ${
                message.role === 'user'
                  ? 'bg-blue-600 text-white'
                  : 'bg-neutral-100 dark:bg-neutral-700 text-neutral-900 dark:text-neutral-50'
              }`}
            >
              <p className="whitespace-pre-wrap">{message.content}</p>
            </div>
          </div>
        ))}

        {/* Streaming response */}
        {isStreaming && streamedText && (
          <div className="flex justify-start">
            <div className="max-w-[85%] rounded-lg px-4 py-2 bg-neutral-100 dark:bg-neutral-700 text-neutral-900 dark:text-neutral-50">
              <p className="whitespace-pre-wrap">{streamedText}</p>
              <span className="inline-block w-2 h-4 bg-blue-500 animate-pulse ml-1"></span>
            </div>
          </div>
        )}

        {/* Loading indicator */}
        {isStreaming && !streamedText && (
          <div className="flex justify-start">
            <div className="rounded-lg px-4 py-2 bg-neutral-100 dark:bg-neutral-700">
              <Loader2 className="h-5 w-5 animate-spin text-blue-500" />
            </div>
          </div>
        )}

        {/* Error */}
        {error && (
          <div className="flex items-center gap-2 p-3 bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400 rounded-lg">
            <AlertCircle className="h-5 w-5 flex-shrink-0" />
            <p className="text-sm">{error}</p>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div className="p-4 border-t border-neutral-200 dark:border-neutral-700">
        <div className="flex gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask a question..."
            rows={1}
            className="flex-1 px-4 py-2 border border-neutral-300 dark:border-neutral-600 rounded-lg bg-white dark:bg-neutral-700 text-neutral-900 dark:text-neutral-50 placeholder-neutral-400 focus:ring-2 focus:ring-blue-500 focus:border-transparent resize-none"
            disabled={isStreaming}
          />
          <button
            onClick={() => handleSubmit(input)}
            disabled={!input.trim() || isStreaming}
            className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {isStreaming ? (
              <Loader2 className="h-5 w-5 animate-spin" />
            ) : (
              <Send className="h-5 w-5" />
            )}
          </button>
        </div>
        <p className="text-xs text-neutral-400 mt-2">
          Press Enter to send. AI analysis is for informational purposes only.
        </p>
      </div>

      <AISettingsModal
        isOpen={showSettings}
        onClose={() => setShowSettings(false)}
      />
    </div>
  );
}
