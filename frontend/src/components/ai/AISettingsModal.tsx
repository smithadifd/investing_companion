'use client';

import { useState, useEffect } from 'react';
import { X, Key, Bot, Loader2, Check, AlertCircle } from 'lucide-react';
import { useAISettings, useUpdateAISettings } from '@/lib/hooks/useAI';
import { Modal } from '@/components/ui/Modal';

interface AISettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export function AISettingsModal({ isOpen, onClose }: AISettingsModalProps) {
  const { data: settings, isLoading } = useAISettings();
  const updateSettings = useUpdateAISettings();

  const [apiKey, setApiKey] = useState('');
  const [defaultModel, setDefaultModel] = useState('claude-3-5-sonnet-20241022');
  const [customInstructions, setCustomInstructions] = useState('');
  const [showSuccess, setShowSuccess] = useState(false);

  // Initialize form with current settings
  useEffect(() => {
    if (settings) {
      setDefaultModel(settings.default_model || 'claude-3-5-sonnet-20241022');
      setCustomInstructions(settings.custom_instructions || '');
    }
  }, [settings]);

  const handleSave = async () => {
    await updateSettings.mutateAsync({
      api_key: apiKey || undefined,
      default_model: defaultModel,
      custom_instructions: customInstructions || undefined,
    });

    setApiKey(''); // Clear API key input after saving
    setShowSuccess(true);
    setTimeout(() => setShowSuccess(false), 3000);
  };

  if (!isOpen) return null;

  const headerContent = (
    <div className="flex items-center justify-between p-4 border-b border-neutral-200 dark:border-neutral-700">
      <div className="flex items-center gap-2">
        <Bot className="h-5 w-5 text-blue-500" />
        <h2 className="text-lg font-semibold text-neutral-900 dark:text-neutral-50">
          AI Settings
        </h2>
      </div>
      <button
        onClick={onClose}
        className="p-1 text-neutral-500 hover:text-neutral-900 dark:hover:text-neutral-50 rounded-lg transition-colors"
      >
        <X className="h-5 w-5" />
      </button>
    </div>
  );

  return (
    <Modal onClose={onClose} header={headerContent}>
        <div className="p-4 space-y-4">
          {isLoading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="h-6 w-6 animate-spin text-blue-500" />
            </div>
          ) : (
            <>
              {/* API Key */}
              <div>
                <label className="flex items-center gap-2 text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
                  <Key className="h-4 w-4" />
                  Claude API Key
                </label>
                <div className="relative">
                  <input
                    type="password"
                    value={apiKey}
                    onChange={(e) => setApiKey(e.target.value)}
                    placeholder={settings?.has_api_key ? '••••••••••••••••' : 'sk-ant-...'}
                    className="w-full px-3 py-2 border border-neutral-300 dark:border-neutral-600 rounded-lg bg-white dark:bg-neutral-700 text-neutral-900 dark:text-neutral-50 focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  />
                  {settings?.has_api_key && (
                    <span className="absolute right-3 top-1/2 -translate-y-1/2">
                      <Check className="h-4 w-4 text-emerald-500" />
                    </span>
                  )}
                </div>
                <p className="text-xs text-neutral-500 mt-1">
                  Get your API key from{' '}
                  <a
                    href="https://console.anthropic.com/settings/keys"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-blue-500 hover:underline"
                  >
                    console.anthropic.com
                  </a>
                </p>
              </div>

              {/* Model Selection */}
              <div>
                <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
                  Default Model
                </label>
                <select
                  value={defaultModel}
                  onChange={(e) => setDefaultModel(e.target.value)}
                  className="w-full px-3 py-2 border border-neutral-300 dark:border-neutral-600 rounded-lg bg-white dark:bg-neutral-700 text-neutral-900 dark:text-neutral-50 focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                >
                  <option value="claude-3-5-sonnet-20241022">
                    Claude 3.5 Sonnet (Recommended)
                  </option>
                  <option value="claude-3-5-haiku-20241022">
                    Claude 3.5 Haiku (Faster, cheaper)
                  </option>
                </select>
              </div>

              {/* Custom Instructions */}
              <div>
                <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
                  Custom Instructions (Optional)
                </label>
                <textarea
                  value={customInstructions}
                  onChange={(e) => setCustomInstructions(e.target.value)}
                  placeholder="e.g., Focus on value investing principles, always mention dividend safety..."
                  rows={3}
                  className="w-full px-3 py-2 border border-neutral-300 dark:border-neutral-600 rounded-lg bg-white dark:bg-neutral-700 text-neutral-900 dark:text-neutral-50 focus:ring-2 focus:ring-blue-500 focus:border-transparent resize-none"
                />
                <p className="text-xs text-neutral-500 mt-1">
                  These instructions will be included in every analysis
                </p>
              </div>

              {/* Success message */}
              {showSuccess && (
                <div className="flex items-center gap-2 p-3 bg-emerald-50 dark:bg-emerald-900/20 text-emerald-600 dark:text-emerald-400 rounded-lg">
                  <Check className="h-5 w-5" />
                  <p className="text-sm">Settings saved successfully</p>
                </div>
              )}

              {/* Error message */}
              {updateSettings.isError && (
                <div className="flex items-center gap-2 p-3 bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400 rounded-lg">
                  <AlertCircle className="h-5 w-5" />
                  <p className="text-sm">Failed to save settings</p>
                </div>
              )}
            </>
          )}
        </div>

        {/* Footer */}
        <div className="flex justify-end gap-3 p-4 border-t border-neutral-200 dark:border-neutral-700">
          <button
            onClick={onClose}
            className="px-4 py-2 text-neutral-600 dark:text-neutral-400 hover:bg-neutral-100 dark:hover:bg-neutral-700 rounded-lg transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={updateSettings.isPending}
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 transition-colors"
          >
            {updateSettings.isPending && (
              <Loader2 className="h-4 w-4 animate-spin" />
            )}
            Save Settings
          </button>
        </div>
    </Modal>
  );
}
