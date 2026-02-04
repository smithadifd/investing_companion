'use client';

import { useState } from 'react';
import { CheckCircle2, XCircle, Loader2, Send, ExternalLink } from 'lucide-react';
import { useNotificationStatus, useTestDiscordNotification } from '@/lib/hooks/useAlert';

export function NotificationSettings() {
  const { data: status, isLoading } = useNotificationStatus();
  const testNotification = useTestDiscordNotification();
  const [testResult, setTestResult] = useState<{ success: boolean; error: string | null } | null>(null);

  const handleTestNotification = async () => {
    setTestResult(null);
    try {
      const result = await testNotification.mutateAsync();
      setTestResult(result);
    } catch (error) {
      setTestResult({ success: false, error: 'Failed to send test notification' });
    }
  };

  if (isLoading) {
    return (
      <div className="bg-white dark:bg-neutral-800 rounded-lg border border-neutral-200 dark:border-neutral-700 p-6">
        <div className="animate-pulse space-y-4">
          <div className="h-6 w-48 bg-neutral-200 dark:bg-neutral-700 rounded"></div>
          <div className="h-20 bg-neutral-200 dark:bg-neutral-700 rounded"></div>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Discord Settings */}
      <div className="bg-white dark:bg-neutral-800 rounded-lg border border-neutral-200 dark:border-neutral-700 p-6">
        <div className="flex items-start justify-between mb-4">
          <div>
            <h3 className="text-lg font-semibold text-neutral-900 dark:text-neutral-50 flex items-center gap-2">
              <svg className="h-5 w-5" viewBox="0 0 24 24" fill="currentColor">
                <path d="M20.317 4.492c-1.53-.69-3.17-1.2-4.885-1.49a.075.075 0 0 0-.079.036c-.21.369-.444.85-.608 1.23a18.566 18.566 0 0 0-5.487 0 12.36 12.36 0 0 0-.617-1.23A.077.077 0 0 0 8.562 3c-1.714.29-3.354.8-4.885 1.491a.07.07 0 0 0-.032.027C.533 9.093-.32 13.555.099 17.961a.08.08 0 0 0 .031.055 20.03 20.03 0 0 0 5.993 2.98.078.078 0 0 0 .084-.026c.462-.62.874-1.275 1.226-1.963.021-.04.001-.088-.041-.104a13.201 13.201 0 0 1-1.872-.878.075.075 0 0 1-.008-.125c.126-.093.252-.19.372-.287a.075.075 0 0 1 .078-.01c3.927 1.764 8.18 1.764 12.061 0a.075.075 0 0 1 .079.009c.12.098.245.195.372.288a.075.075 0 0 1-.006.125c-.598.344-1.22.635-1.873.877a.075.075 0 0 0-.041.105c.36.687.772 1.341 1.225 1.962a.077.077 0 0 0 .084.028 19.963 19.963 0 0 0 6.002-2.981.076.076 0 0 0 .032-.054c.5-5.094-.838-9.52-3.549-13.442a.06.06 0 0 0-.031-.028zM8.02 15.278c-1.182 0-2.157-1.069-2.157-2.38 0-1.312.956-2.38 2.157-2.38 1.21 0 2.176 1.077 2.157 2.38 0 1.312-.956 2.38-2.157 2.38zm7.975 0c-1.183 0-2.157-1.069-2.157-2.38 0-1.312.955-2.38 2.157-2.38 1.21 0 2.176 1.077 2.157 2.38 0 1.312-.946 2.38-2.157 2.38z"/>
              </svg>
              Discord
            </h3>
            <p className="text-sm text-neutral-500 mt-1">
              Receive alert notifications via Discord webhook
            </p>
          </div>
          <div className="flex items-center gap-2">
            {status?.discord.configured ? (
              <span className="flex items-center gap-1.5 text-sm text-emerald-600 dark:text-emerald-400 bg-emerald-100 dark:bg-emerald-900/30 px-3 py-1 rounded-full">
                <CheckCircle2 className="h-4 w-4" />
                Configured
              </span>
            ) : (
              <span className="flex items-center gap-1.5 text-sm text-red-600 dark:text-red-400 bg-red-100 dark:bg-red-900/30 px-3 py-1 rounded-full">
                <XCircle className="h-4 w-4" />
                Not Configured
              </span>
            )}
          </div>
        </div>

        {status?.discord.configured ? (
          <div className="space-y-4">
            <p className="text-sm text-neutral-600 dark:text-neutral-400">
              Your Discord webhook is configured. You can test the connection below.
            </p>

            <div className="flex items-center gap-3">
              <button
                onClick={handleTestNotification}
                disabled={testNotification.isPending}
                className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors disabled:opacity-50"
              >
                {testNotification.isPending ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Send className="h-4 w-4" />
                )}
                Send Test Notification
              </button>

              {testResult && (
                <span
                  className={`text-sm ${
                    testResult.success
                      ? 'text-emerald-600 dark:text-emerald-400'
                      : 'text-red-600 dark:text-red-400'
                  }`}
                >
                  {testResult.success
                    ? 'Test notification sent!'
                    : testResult.error || 'Failed to send'}
                </span>
              )}
            </div>
          </div>
        ) : (
          <div className="space-y-4">
            <div className="bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-lg p-4">
              <h4 className="text-sm font-medium text-amber-800 dark:text-amber-200 mb-2">
                Setup Required
              </h4>
              <p className="text-sm text-amber-700 dark:text-amber-300 mb-3">
                To receive Discord notifications, you need to configure a webhook URL in the backend environment.
              </p>
              <ol className="text-sm text-amber-700 dark:text-amber-300 space-y-2 list-decimal list-inside">
                <li>Open your Discord server settings</li>
                <li>Go to Integrations &rarr; Webhooks</li>
                <li>Create a new webhook or copy an existing URL</li>
                <li>
                  Set <code className="bg-amber-100 dark:bg-amber-900 px-1 rounded">DISCORD_WEBHOOK_URL</code> in your <code className="bg-amber-100 dark:bg-amber-900 px-1 rounded">.env</code> file
                </li>
                <li>Restart the backend service</li>
              </ol>
            </div>

            <a
              href="https://support.discord.com/hc/en-us/articles/228383668-Intro-to-Webhooks"
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-2 text-sm text-blue-600 dark:text-blue-400 hover:underline"
            >
              <ExternalLink className="h-4 w-4" />
              Learn more about Discord webhooks
            </a>
          </div>
        )}
      </div>

      {/* Alert Check Schedule */}
      <div className="bg-white dark:bg-neutral-800 rounded-lg border border-neutral-200 dark:border-neutral-700 p-6">
        <h3 className="text-lg font-semibold text-neutral-900 dark:text-neutral-50 mb-2">
          Alert Check Schedule
        </h3>
        <p className="text-sm text-neutral-500 mb-4">
          Alerts are automatically checked by the background worker.
        </p>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div className="bg-neutral-50 dark:bg-neutral-700/50 rounded-lg p-4">
            <p className="text-sm font-medium text-neutral-700 dark:text-neutral-300">
              Alert Check Interval
            </p>
            <p className="text-2xl font-bold text-neutral-900 dark:text-neutral-50">
              5 minutes
            </p>
            <p className="text-xs text-neutral-500 mt-1">
              All active alerts are checked every 5 minutes
            </p>
          </div>

          <div className="bg-neutral-50 dark:bg-neutral-700/50 rounded-lg p-4">
            <p className="text-sm font-medium text-neutral-700 dark:text-neutral-300">
              Daily Summary
            </p>
            <p className="text-2xl font-bold text-neutral-900 dark:text-neutral-50">
              6:00 PM UTC
            </p>
            <p className="text-xs text-neutral-500 mt-1">
              Daily summary sent to Discord
            </p>
          </div>
        </div>
      </div>

      {/* Tips */}
      <div className="bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-lg p-6">
        <h3 className="text-lg font-semibold text-blue-800 dark:text-blue-200 mb-3">
          Tips for Effective Alerts
        </h3>
        <ul className="text-sm text-blue-700 dark:text-blue-300 space-y-2">
          <li className="flex items-start gap-2">
            <span className="text-blue-500 mt-0.5">•</span>
            Use &quot;crosses above/below&quot; for breakout alerts to avoid repeated triggers
          </li>
          <li className="flex items-start gap-2">
            <span className="text-blue-500 mt-0.5">•</span>
            Set appropriate cooldown times to avoid notification spam
          </li>
          <li className="flex items-start gap-2">
            <span className="text-blue-500 mt-0.5">•</span>
            Add notes to remember why you set each alert
          </li>
          <li className="flex items-start gap-2">
            <span className="text-blue-500 mt-0.5">•</span>
            Use percent change alerts for volatility monitoring
          </li>
        </ul>
      </div>
    </div>
  );
}
