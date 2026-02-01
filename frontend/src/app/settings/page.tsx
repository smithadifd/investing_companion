'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { useTheme } from 'next-themes';
import {
  Settings,
  Key,
  Bell,
  User,
  LogOut,
  Shield,
  Loader2,
  Check,
  AlertCircle,
  Eye,
  EyeOff,
  Palette,
  Sun,
  Moon,
  Monitor,
} from 'lucide-react';
import { useAuth } from '@/lib/contexts/AuthContext';
import {
  useAppSettings,
  useUpdateAppSettings,
  useChangePassword,
  useSessions,
  useLogoutAll,
} from '@/lib/hooks/useAuth';

export default function SettingsPage() {
  const router = useRouter();
  const { user, isAuthenticated, isLoading, logout } = useAuth();
  const { data: appSettings, isLoading: settingsLoading } = useAppSettings();
  const updateSettings = useUpdateAppSettings();
  const changePasswordMutation = useChangePassword();
  const { data: sessions } = useSessions();
  const logoutAllMutation = useLogoutAll();
  const { theme, setTheme } = useTheme();

  const [activeTab, setActiveTab] = useState<'api-keys' | 'notifications' | 'appearance' | 'account' | 'sessions'>('api-keys');

  // API keys state
  const [claudeKey, setClaudeKey] = useState('');
  const [alphaVantageKey, setAlphaVantageKey] = useState('');
  const [polygonKey, setPolygonKey] = useState('');
  const [discordWebhook, setDiscordWebhook] = useState('');

  // Password change state
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [showPasswords, setShowPasswords] = useState(false);
  const [passwordError, setPasswordError] = useState<string | null>(null);
  const [passwordSuccess, setPasswordSuccess] = useState(false);

  // Redirect if not authenticated
  if (!isLoading && !isAuthenticated) {
    router.push('/login');
    return null;
  }

  if (isLoading || settingsLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-neutral-50 dark:bg-neutral-900">
        <Loader2 className="h-8 w-8 animate-spin text-blue-500" />
      </div>
    );
  }

  const handleSaveApiKeys = async () => {
    const updates: Record<string, string> = {};
    if (claudeKey) updates.claude_api_key = claudeKey;
    if (alphaVantageKey) updates.alpha_vantage_api_key = alphaVantageKey;
    if (polygonKey) updates.polygon_api_key = polygonKey;
    if (discordWebhook) updates.discord_webhook_url = discordWebhook;

    if (Object.keys(updates).length > 0) {
      await updateSettings.mutateAsync(updates);
      // Clear form fields after save
      setClaudeKey('');
      setAlphaVantageKey('');
      setPolygonKey('');
      setDiscordWebhook('');
    }
  };

  const handleClearKey = async (key: string) => {
    await updateSettings.mutateAsync({ [key]: '' });
  };

  const handleChangePassword = async (e: React.FormEvent) => {
    e.preventDefault();
    setPasswordError(null);
    setPasswordSuccess(false);

    if (newPassword !== confirmPassword) {
      setPasswordError('New passwords do not match');
      return;
    }

    try {
      await changePasswordMutation.mutateAsync({
        current_password: currentPassword,
        new_password: newPassword,
        new_password_confirm: confirmPassword,
      });
      setPasswordSuccess(true);
      // Redirect to login after password change
      setTimeout(() => router.push('/login'), 2000);
    } catch (err) {
      if (err instanceof Error) {
        setPasswordError(err.message);
      } else {
        setPasswordError('Failed to change password');
      }
    }
  };

  const handleLogoutAll = async () => {
    await logoutAllMutation.mutateAsync();
    router.push('/login');
  };

  const handleLogout = async () => {
    await logout();
    router.push('/login');
  };

  const tabs = [
    { id: 'api-keys', label: 'API Keys', icon: Key },
    { id: 'notifications', label: 'Notifications', icon: Bell },
    { id: 'appearance', label: 'Appearance', icon: Palette },
    { id: 'account', label: 'Account', icon: User },
    { id: 'sessions', label: 'Sessions', icon: Shield },
  ] as const;

  return (
    <div className="min-h-[calc(100vh-4rem)] bg-neutral-50 dark:bg-neutral-900">
      <div className="max-w-4xl mx-auto px-4 sm:px-6 py-6 sm:py-8">
        <div className="flex items-center gap-3 mb-8">
          <Settings className="h-8 w-8 text-blue-500" />
          <h1 className="text-2xl font-bold text-neutral-900 dark:text-neutral-50">
            Settings
          </h1>
        </div>

        <div className="flex flex-col md:flex-row gap-6">
          {/* Sidebar tabs */}
          <div className="md:w-48 flex md:flex-col gap-2">
            {tabs.map((tab) => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                  activeTab === tab.id
                    ? 'bg-blue-500 text-white'
                    : 'text-neutral-600 dark:text-neutral-400 hover:bg-neutral-100 dark:hover:bg-neutral-800'
                }`}
              >
                <tab.icon className="h-4 w-4" />
                {tab.label}
              </button>
            ))}
          </div>

          {/* Content */}
          <div className="flex-1 bg-white dark:bg-neutral-800 rounded-xl border border-neutral-200 dark:border-neutral-700 p-6">
            {activeTab === 'api-keys' && (
              <div className="space-y-6">
                <div>
                  <h2 className="text-lg font-semibold text-neutral-900 dark:text-neutral-50 mb-1">
                    API Keys
                  </h2>
                  <p className="text-sm text-neutral-500 dark:text-neutral-400">
                    Configure API keys for AI analysis and data providers.
                  </p>
                </div>

                {/* Claude API Key */}
                <div className="space-y-2">
                  <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300">
                    Claude API Key
                  </label>
                  <div className="flex gap-2">
                    <input
                      type="password"
                      value={claudeKey}
                      onChange={(e) => setClaudeKey(e.target.value)}
                      placeholder={appSettings?.claude_api_key || 'Not configured'}
                      className="flex-1 px-3 py-2 rounded-lg border border-neutral-300 dark:border-neutral-600 bg-white dark:bg-neutral-700 text-neutral-900 dark:text-neutral-100"
                    />
                    {appSettings?.claude_api_key && (
                      <button
                        onClick={() => handleClearKey('claude_api_key')}
                        className="px-3 py-2 text-sm text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20 rounded-lg"
                      >
                        Clear
                      </button>
                    )}
                  </div>
                  <p className="text-xs text-neutral-500">
                    Required for AI analysis features.{' '}
                    <a
                      href="https://console.anthropic.com/"
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-blue-500 hover:underline"
                    >
                      Get an API key
                    </a>
                  </p>
                </div>

                {/* Alpha Vantage Key */}
                <div className="space-y-2">
                  <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300">
                    Alpha Vantage API Key
                  </label>
                  <div className="flex gap-2">
                    <input
                      type="password"
                      value={alphaVantageKey}
                      onChange={(e) => setAlphaVantageKey(e.target.value)}
                      placeholder={appSettings?.alpha_vantage_api_key || 'Not configured'}
                      className="flex-1 px-3 py-2 rounded-lg border border-neutral-300 dark:border-neutral-600 bg-white dark:bg-neutral-700 text-neutral-900 dark:text-neutral-100"
                    />
                    {appSettings?.alpha_vantage_api_key && (
                      <button
                        onClick={() => handleClearKey('alpha_vantage_api_key')}
                        className="px-3 py-2 text-sm text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20 rounded-lg"
                      >
                        Clear
                      </button>
                    )}
                  </div>
                  <p className="text-xs text-neutral-500">
                    Optional, for additional market data.
                  </p>
                </div>

                {/* Polygon Key */}
                <div className="space-y-2">
                  <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300">
                    Polygon.io API Key
                  </label>
                  <div className="flex gap-2">
                    <input
                      type="password"
                      value={polygonKey}
                      onChange={(e) => setPolygonKey(e.target.value)}
                      placeholder={appSettings?.polygon_api_key || 'Not configured'}
                      className="flex-1 px-3 py-2 rounded-lg border border-neutral-300 dark:border-neutral-600 bg-white dark:bg-neutral-700 text-neutral-900 dark:text-neutral-100"
                    />
                    {appSettings?.polygon_api_key && (
                      <button
                        onClick={() => handleClearKey('polygon_api_key')}
                        className="px-3 py-2 text-sm text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20 rounded-lg"
                      >
                        Clear
                      </button>
                    )}
                  </div>
                  <p className="text-xs text-neutral-500">
                    Optional, for real-time data (paid tier).
                  </p>
                </div>

                <button
                  onClick={handleSaveApiKeys}
                  disabled={updateSettings.isPending || (!claudeKey && !alphaVantageKey && !polygonKey)}
                  className="px-4 py-2 bg-blue-500 hover:bg-blue-600 disabled:bg-blue-400 text-white font-medium rounded-lg transition-colors flex items-center gap-2"
                >
                  {updateSettings.isPending ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Check className="h-4 w-4" />
                  )}
                  Save API Keys
                </button>
              </div>
            )}

            {activeTab === 'notifications' && (
              <div className="space-y-6">
                <div>
                  <h2 className="text-lg font-semibold text-neutral-900 dark:text-neutral-50 mb-1">
                    Notifications
                  </h2>
                  <p className="text-sm text-neutral-500 dark:text-neutral-400">
                    Configure notification settings for alerts.
                  </p>
                </div>

                {/* Discord Webhook */}
                <div className="space-y-2">
                  <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300">
                    Discord Webhook URL
                  </label>
                  <div className="flex gap-2">
                    <input
                      type="text"
                      value={discordWebhook}
                      onChange={(e) => setDiscordWebhook(e.target.value)}
                      placeholder={appSettings?.discord_webhook_url || 'Not configured'}
                      className="flex-1 px-3 py-2 rounded-lg border border-neutral-300 dark:border-neutral-600 bg-white dark:bg-neutral-700 text-neutral-900 dark:text-neutral-100"
                    />
                    {appSettings?.discord_webhook_url && (
                      <button
                        onClick={() => handleClearKey('discord_webhook_url')}
                        className="px-3 py-2 text-sm text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20 rounded-lg"
                      >
                        Clear
                      </button>
                    )}
                  </div>
                  <p className="text-xs text-neutral-500">
                    Used for alert notifications. Create a webhook in your Discord server settings.
                  </p>
                </div>

                <button
                  onClick={handleSaveApiKeys}
                  disabled={updateSettings.isPending || !discordWebhook}
                  className="px-4 py-2 bg-blue-500 hover:bg-blue-600 disabled:bg-blue-400 text-white font-medium rounded-lg transition-colors flex items-center gap-2"
                >
                  {updateSettings.isPending ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Check className="h-4 w-4" />
                  )}
                  Save Notification Settings
                </button>
              </div>
            )}

            {activeTab === 'appearance' && (
              <div className="space-y-6">
                <div>
                  <h2 className="text-lg font-semibold text-neutral-900 dark:text-neutral-50 mb-1">
                    Appearance
                  </h2>
                  <p className="text-sm text-neutral-500 dark:text-neutral-400">
                    Customize how the app looks and feels.
                  </p>
                </div>

                {/* Theme Selection */}
                <div className="space-y-3">
                  <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300">
                    Theme
                  </label>
                  <div className="grid grid-cols-3 gap-3">
                    <button
                      onClick={() => setTheme('light')}
                      className={`flex flex-col items-center gap-2 p-4 rounded-lg border-2 transition-all ${
                        theme === 'light'
                          ? 'border-blue-500 bg-blue-50 dark:bg-blue-900/20'
                          : 'border-neutral-200 dark:border-neutral-700 hover:border-neutral-300 dark:hover:border-neutral-600'
                      }`}
                    >
                      <Sun className={`h-6 w-6 ${theme === 'light' ? 'text-blue-500' : 'text-neutral-500 dark:text-neutral-400'}`} />
                      <span className={`text-sm font-medium ${theme === 'light' ? 'text-blue-600 dark:text-blue-400' : 'text-neutral-700 dark:text-neutral-300'}`}>
                        Light
                      </span>
                    </button>
                    <button
                      onClick={() => setTheme('dark')}
                      className={`flex flex-col items-center gap-2 p-4 rounded-lg border-2 transition-all ${
                        theme === 'dark'
                          ? 'border-blue-500 bg-blue-50 dark:bg-blue-900/20'
                          : 'border-neutral-200 dark:border-neutral-700 hover:border-neutral-300 dark:hover:border-neutral-600'
                      }`}
                    >
                      <Moon className={`h-6 w-6 ${theme === 'dark' ? 'text-blue-500' : 'text-neutral-500 dark:text-neutral-400'}`} />
                      <span className={`text-sm font-medium ${theme === 'dark' ? 'text-blue-600 dark:text-blue-400' : 'text-neutral-700 dark:text-neutral-300'}`}>
                        Dark
                      </span>
                    </button>
                    <button
                      onClick={() => setTheme('system')}
                      className={`flex flex-col items-center gap-2 p-4 rounded-lg border-2 transition-all ${
                        theme === 'system'
                          ? 'border-blue-500 bg-blue-50 dark:bg-blue-900/20'
                          : 'border-neutral-200 dark:border-neutral-700 hover:border-neutral-300 dark:hover:border-neutral-600'
                      }`}
                    >
                      <Monitor className={`h-6 w-6 ${theme === 'system' ? 'text-blue-500' : 'text-neutral-500 dark:text-neutral-400'}`} />
                      <span className={`text-sm font-medium ${theme === 'system' ? 'text-blue-600 dark:text-blue-400' : 'text-neutral-700 dark:text-neutral-300'}`}>
                        System
                      </span>
                    </button>
                  </div>
                  <p className="text-xs text-neutral-500 dark:text-neutral-400">
                    Choose your preferred color scheme. &quot;System&quot; will follow your device&apos;s settings.
                  </p>
                </div>
              </div>
            )}

            {activeTab === 'account' && (
              <div className="space-y-6">
                <div>
                  <h2 className="text-lg font-semibold text-neutral-900 dark:text-neutral-50 mb-1">
                    Account
                  </h2>
                  <p className="text-sm text-neutral-500 dark:text-neutral-400">
                    Manage your account settings.
                  </p>
                </div>

                {/* User info */}
                <div className="p-4 bg-neutral-50 dark:bg-neutral-700/50 rounded-lg">
                  <div className="text-sm text-neutral-500 dark:text-neutral-400">
                    Signed in as
                  </div>
                  <div className="font-medium text-neutral-900 dark:text-neutral-50">
                    {user?.email}
                  </div>
                </div>

                {/* Change password */}
                <form onSubmit={handleChangePassword} className="space-y-4">
                  <h3 className="font-medium text-neutral-900 dark:text-neutral-50">
                    Change Password
                  </h3>

                  {passwordError && (
                    <div className="p-3 rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 text-red-700 dark:text-red-400 text-sm flex items-center gap-2">
                      <AlertCircle className="h-4 w-4" />
                      {passwordError}
                    </div>
                  )}

                  {passwordSuccess && (
                    <div className="p-3 rounded-lg bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 text-green-700 dark:text-green-400 text-sm flex items-center gap-2">
                      <Check className="h-4 w-4" />
                      Password changed successfully. Redirecting to login...
                    </div>
                  )}

                  <div className="space-y-3">
                    <input
                      type={showPasswords ? 'text' : 'password'}
                      value={currentPassword}
                      onChange={(e) => setCurrentPassword(e.target.value)}
                      placeholder="Current password"
                      className="w-full px-3 py-2 rounded-lg border border-neutral-300 dark:border-neutral-600 bg-white dark:bg-neutral-700 text-neutral-900 dark:text-neutral-100"
                    />
                    <input
                      type={showPasswords ? 'text' : 'password'}
                      value={newPassword}
                      onChange={(e) => setNewPassword(e.target.value)}
                      placeholder="New password (min 8 characters)"
                      minLength={8}
                      className="w-full px-3 py-2 rounded-lg border border-neutral-300 dark:border-neutral-600 bg-white dark:bg-neutral-700 text-neutral-900 dark:text-neutral-100"
                    />
                    <input
                      type={showPasswords ? 'text' : 'password'}
                      value={confirmPassword}
                      onChange={(e) => setConfirmPassword(e.target.value)}
                      placeholder="Confirm new password"
                      minLength={8}
                      className="w-full px-3 py-2 rounded-lg border border-neutral-300 dark:border-neutral-600 bg-white dark:bg-neutral-700 text-neutral-900 dark:text-neutral-100"
                    />
                  </div>

                  <div className="flex items-center gap-4">
                    <button
                      type="submit"
                      disabled={changePasswordMutation.isPending || !currentPassword || !newPassword || !confirmPassword}
                      className="px-4 py-2 bg-blue-500 hover:bg-blue-600 disabled:bg-blue-400 text-white font-medium rounded-lg transition-colors"
                    >
                      {changePasswordMutation.isPending ? 'Changing...' : 'Change Password'}
                    </button>
                    <button
                      type="button"
                      onClick={() => setShowPasswords(!showPasswords)}
                      className="text-sm text-neutral-500 hover:text-neutral-700 dark:hover:text-neutral-300 flex items-center gap-1"
                    >
                      {showPasswords ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                      {showPasswords ? 'Hide' : 'Show'}
                    </button>
                  </div>
                </form>

                {/* Logout */}
                <div className="pt-6 border-t border-neutral-200 dark:border-neutral-700">
                  <button
                    onClick={handleLogout}
                    className="px-4 py-2 text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20 font-medium rounded-lg transition-colors flex items-center gap-2"
                  >
                    <LogOut className="h-4 w-4" />
                    Sign out
                  </button>
                </div>
              </div>
            )}

            {activeTab === 'sessions' && (
              <div className="space-y-6">
                <div>
                  <h2 className="text-lg font-semibold text-neutral-900 dark:text-neutral-50 mb-1">
                    Active Sessions
                  </h2>
                  <p className="text-sm text-neutral-500 dark:text-neutral-400">
                    Manage your active login sessions.
                  </p>
                </div>

                {/* Sessions list */}
                <div className="space-y-3">
                  {sessions?.map((session) => (
                    <div
                      key={session.id}
                      className={`p-4 rounded-lg border ${
                        session.is_current
                          ? 'border-blue-200 dark:border-blue-800 bg-blue-50 dark:bg-blue-900/20'
                          : 'border-neutral-200 dark:border-neutral-700 bg-neutral-50 dark:bg-neutral-700/50'
                      }`}
                    >
                      <div className="flex items-center justify-between">
                        <div>
                          <div className="flex items-center gap-2">
                            <span className="font-medium text-neutral-900 dark:text-neutral-50">
                              {session.user_agent?.split(' ')[0] || 'Unknown device'}
                            </span>
                            {session.is_current && (
                              <span className="px-2 py-0.5 text-xs bg-blue-500 text-white rounded-full">
                                Current
                              </span>
                            )}
                          </div>
                          <div className="text-sm text-neutral-500 dark:text-neutral-400">
                            {session.ip_address || 'Unknown IP'} &middot;{' '}
                            {new Date(session.created_at).toLocaleDateString()}
                          </div>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>

                {/* Logout all */}
                <div className="pt-4">
                  <button
                    onClick={handleLogoutAll}
                    disabled={logoutAllMutation.isPending}
                    className="px-4 py-2 text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20 font-medium rounded-lg transition-colors flex items-center gap-2"
                  >
                    <Shield className="h-4 w-4" />
                    Sign out all sessions
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
