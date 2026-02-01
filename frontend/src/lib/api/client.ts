/**
 * API client for the Investing Companion backend
 */

import type {
  AIAnalysisRequest,
  AIAnalysisResponse,
  AISettings,
  AISettingsUpdate,
  Alert,
  AlertCheckResult,
  AlertCreate,
  AlertHistory,
  AlertStats,
  AlertUpdate,
  AlertWithHistory,
  ApiResponse,
  AppSettings,
  AppSettingsUpdate,
  EquityDetail,
  EquitySearchResult,
  HistoryData,
  MarketOverview,
  NotificationStatus,
  PasswordChange,
  Quote,
  Ratio,
  RatioCreate,
  RatioHistory,
  RatioQuote,
  RatioUpdate,
  RegistrationStatus,
  SessionInfo,
  TechnicalIndicators,
  TechnicalSummary,
  TokenRefresh,
  TokenResponse,
  User,
  UserCreate,
  UserLogin,
  Watchlist,
  WatchlistCreate,
  WatchlistExport,
  WatchlistImport,
  WatchlistItem,
  WatchlistItemCreate,
  WatchlistItemUpdate,
  WatchlistSummary,
  WatchlistUpdate,
} from './types';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1';

// Token storage keys
const ACCESS_TOKEN_KEY = 'investing_companion_access_token';
const REFRESH_TOKEN_KEY = 'investing_companion_refresh_token';

class ApiError extends Error {
  constructor(
    message: string,
    public code: string,
    public status: number
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

class ApiClient {
  private accessToken: string | null = null;
  private refreshToken: string | null = null;
  private refreshPromise: Promise<boolean> | null = null;

  constructor() {
    // Load tokens from localStorage if available (client-side only)
    if (typeof window !== 'undefined') {
      this.accessToken = localStorage.getItem(ACCESS_TOKEN_KEY);
      this.refreshToken = localStorage.getItem(REFRESH_TOKEN_KEY);
    }
  }

  /**
   * Store tokens after login/refresh
   */
  private storeTokens(tokens: TokenResponse): void {
    this.accessToken = tokens.access_token;
    this.refreshToken = tokens.refresh_token;
    if (typeof window !== 'undefined') {
      localStorage.setItem(ACCESS_TOKEN_KEY, tokens.access_token);
      localStorage.setItem(REFRESH_TOKEN_KEY, tokens.refresh_token);
    }
  }

  /**
   * Clear stored tokens on logout
   */
  private clearTokens(): void {
    this.accessToken = null;
    this.refreshToken = null;
    if (typeof window !== 'undefined') {
      localStorage.removeItem(ACCESS_TOKEN_KEY);
      localStorage.removeItem(REFRESH_TOKEN_KEY);
    }
  }

  /**
   * Check if user is authenticated
   */
  isAuthenticated(): boolean {
    return !!this.accessToken;
  }

  /**
   * Get current access token
   */
  getAccessToken(): string | null {
    return this.accessToken;
  }

  /**
   * Attempt to refresh the access token
   */
  private async refreshAccessToken(): Promise<boolean> {
    if (!this.refreshToken) {
      return false;
    }

    // Prevent multiple simultaneous refresh attempts
    if (this.refreshPromise) {
      return this.refreshPromise;
    }

    this.refreshPromise = (async () => {
      try {
        const response = await fetch(`${API_BASE}/auth/refresh`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ refresh_token: this.refreshToken }),
        });

        if (!response.ok) {
          this.clearTokens();
          return false;
        }

        const result: ApiResponse<TokenResponse> = await response.json();
        this.storeTokens(result.data);
        return true;
      } catch {
        this.clearTokens();
        return false;
      } finally {
        this.refreshPromise = null;
      }
    })();

    return this.refreshPromise;
  }

  private async fetch<T>(path: string, options?: RequestInit & { requiresAuth?: boolean }): Promise<T> {
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      ...(options?.headers as Record<string, string>),
    };

    // Add auth header if we have a token
    if (this.accessToken) {
      headers['Authorization'] = `Bearer ${this.accessToken}`;
    }

    let response = await fetch(`${API_BASE}${path}`, {
      ...options,
      headers,
    });

    // If 401 and we have a refresh token, try to refresh
    if (response.status === 401 && this.refreshToken) {
      const refreshed = await this.refreshAccessToken();
      if (refreshed) {
        // Retry the request with new token
        headers['Authorization'] = `Bearer ${this.accessToken}`;
        response = await fetch(`${API_BASE}${path}`, {
          ...options,
          headers,
        });
      }
    }

    if (!response.ok) {
      let errorMessage = 'API request failed';
      let errorCode = 'UNKNOWN_ERROR';

      try {
        const errorData = await response.json();
        errorMessage = errorData.detail || errorData.error?.message || errorMessage;
        errorCode = errorData.error?.code || errorCode;
      } catch {
        // Response wasn't JSON
      }

      throw new ApiError(errorMessage, errorCode, response.status);
    }

    // Handle 204 No Content
    if (response.status === 204) {
      return undefined as T;
    }

    const result: ApiResponse<T> = await response.json();
    return result.data;
  }

  // ==================== Auth Methods ====================

  /**
   * Check if registration is enabled
   */
  async getRegistrationStatus(): Promise<RegistrationStatus> {
    return this.fetch<RegistrationStatus>('/auth/registration-status');
  }

  /**
   * Register a new user
   */
  async register(data: UserCreate): Promise<User> {
    return this.fetch<User>('/auth/register', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  /**
   * Login with email and password
   */
  async login(data: UserLogin): Promise<TokenResponse> {
    const tokens = await this.fetch<TokenResponse>('/auth/login', {
      method: 'POST',
      body: JSON.stringify(data),
    });
    this.storeTokens(tokens);
    return tokens;
  }

  /**
   * Logout and revoke refresh token
   */
  async logout(): Promise<void> {
    if (this.refreshToken) {
      try {
        await fetch(`${API_BASE}/auth/logout`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ refresh_token: this.refreshToken }),
        });
      } catch {
        // Ignore errors during logout
      }
    }
    this.clearTokens();
  }

  /**
   * Logout from all sessions
   */
  async logoutAll(): Promise<void> {
    await this.fetch('/auth/logout-all', { method: 'POST' });
    this.clearTokens();
  }

  /**
   * Get current user profile
   */
  async getCurrentUser(): Promise<User> {
    return this.fetch<User>('/auth/me');
  }

  /**
   * Update current user email
   */
  async updateCurrentUser(email: string): Promise<User> {
    return this.fetch<User>('/auth/me', {
      method: 'PATCH',
      body: JSON.stringify({ email }),
    });
  }

  /**
   * Change password
   */
  async changePassword(data: PasswordChange): Promise<void> {
    await this.fetch('/auth/me/change-password', {
      method: 'POST',
      body: JSON.stringify(data),
    });
    // Password change revokes all sessions, clear tokens
    this.clearTokens();
  }

  /**
   * Get all active sessions
   */
  async getSessions(): Promise<SessionInfo[]> {
    return this.fetch<SessionInfo[]>('/auth/me/sessions');
  }

  // ==================== Settings Methods ====================

  /**
   * Get app settings
   */
  async getAppSettings(): Promise<AppSettings> {
    return this.fetch<AppSettings>('/settings');
  }

  /**
   * Update app settings
   */
  async updateAppSettings(data: AppSettingsUpdate): Promise<AppSettings> {
    return this.fetch<AppSettings>('/settings', {
      method: 'PATCH',
      body: JSON.stringify(data),
    });
  }

  /**
   * Search for equities by symbol or name
   */
  async searchEquities(query: string, limit = 20): Promise<EquitySearchResult[]> {
    return this.fetch<EquitySearchResult[]>(
      `/equity/search?q=${encodeURIComponent(query)}&limit=${limit}`
    );
  }

  /**
   * Get equity details including quote and fundamentals
   */
  async getEquity(symbol: string): Promise<EquityDetail> {
    return this.fetch<EquityDetail>(`/equity/${encodeURIComponent(symbol)}`);
  }

  /**
   * Get current quote for an equity
   */
  async getQuote(symbol: string): Promise<Quote> {
    return this.fetch<Quote>(`/equity/${encodeURIComponent(symbol)}/quote`);
  }

  /**
   * Get historical price data
   */
  async getHistory(
    symbol: string,
    period = '1y',
    interval = '1d'
  ): Promise<HistoryData> {
    return this.fetch<HistoryData>(
      `/equity/${encodeURIComponent(symbol)}/history?period=${period}&interval=${interval}`
    );
  }

  /**
   * Get technical indicators
   */
  async getTechnicals(symbol: string, period = '1y'): Promise<TechnicalIndicators> {
    return this.fetch<TechnicalIndicators>(
      `/equity/${encodeURIComponent(symbol)}/technicals?period=${period}`
    );
  }

  /**
   * Get technical indicators summary
   */
  async getTechnicalsSummary(symbol: string): Promise<TechnicalSummary> {
    return this.fetch<TechnicalSummary>(
      `/equity/${encodeURIComponent(symbol)}/technicals/summary`
    );
  }

  /**
   * Get peer companies for comparison
   */
  async getPeers(symbol: string, limit = 5): Promise<EquityDetail[]> {
    return this.fetch<EquityDetail[]>(
      `/equity/${encodeURIComponent(symbol)}/peers?limit=${limit}`
    );
  }

  // Watchlist methods

  /**
   * Get all watchlists
   */
  async getWatchlists(): Promise<WatchlistSummary[]> {
    return this.fetch<WatchlistSummary[]>('/watchlists');
  }

  /**
   * Get a single watchlist with items
   */
  async getWatchlist(id: number, includeQuotes = true): Promise<Watchlist> {
    return this.fetch<Watchlist>(
      `/watchlists/${id}?include_quotes=${includeQuotes}`
    );
  }

  /**
   * Create a new watchlist
   */
  async createWatchlist(data: WatchlistCreate): Promise<Watchlist> {
    return this.fetch<Watchlist>('/watchlists', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  /**
   * Update a watchlist
   */
  async updateWatchlist(id: number, data: WatchlistUpdate): Promise<Watchlist> {
    return this.fetch<Watchlist>(`/watchlists/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    });
  }

  /**
   * Delete a watchlist
   */
  async deleteWatchlist(id: number): Promise<void> {
    await fetch(`${API_BASE}/watchlists/${id}`, {
      method: 'DELETE',
    });
  }

  /**
   * Add an item to a watchlist
   */
  async addWatchlistItem(
    watchlistId: number,
    data: WatchlistItemCreate
  ): Promise<WatchlistItem> {
    return this.fetch<WatchlistItem>(`/watchlists/${watchlistId}/items`, {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  /**
   * Update a watchlist item
   */
  async updateWatchlistItem(
    watchlistId: number,
    itemId: number,
    data: WatchlistItemUpdate
  ): Promise<WatchlistItem> {
    return this.fetch<WatchlistItem>(
      `/watchlists/${watchlistId}/items/${itemId}`,
      {
        method: 'PUT',
        body: JSON.stringify(data),
      }
    );
  }

  /**
   * Remove an item from a watchlist
   */
  async removeWatchlistItem(watchlistId: number, itemId: number): Promise<void> {
    await fetch(`${API_BASE}/watchlists/${watchlistId}/items/${itemId}`, {
      method: 'DELETE',
    });
  }

  /**
   * Export a watchlist to JSON
   */
  async exportWatchlist(id: number): Promise<WatchlistExport> {
    const response = await fetch(`${API_BASE}/watchlists/${id}/export`);
    if (!response.ok) {
      throw new ApiError('Failed to export watchlist', 'EXPORT_ERROR', response.status);
    }
    return response.json();
  }

  /**
   * Import a watchlist from JSON
   */
  async importWatchlist(data: WatchlistImport): Promise<Watchlist> {
    return this.fetch<Watchlist>('/watchlists/import', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  // Market overview methods

  /**
   * Get market overview data (indices, sectors, movers, currencies/commodities)
   */
  async getMarketOverview(): Promise<MarketOverview> {
    return this.fetch<MarketOverview>('/market/overview');
  }

  // Ratio methods

  /**
   * Get all ratios
   */
  async getRatios(favoritesOnly = false, category?: string): Promise<Ratio[]> {
    let url = '/ratios';
    const params = new URLSearchParams();
    if (favoritesOnly) params.append('favorites_only', 'true');
    if (category) params.append('category', category);
    const queryString = params.toString();
    if (queryString) url += `?${queryString}`;
    return this.fetch<Ratio[]>(url);
  }

  /**
   * Get a single ratio
   */
  async getRatio(id: number): Promise<Ratio> {
    return this.fetch<Ratio>(`/ratios/${id}`);
  }

  /**
   * Create a new ratio
   */
  async createRatio(data: RatioCreate): Promise<Ratio> {
    return this.fetch<Ratio>('/ratios', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  /**
   * Update a ratio
   */
  async updateRatio(id: number, data: RatioUpdate): Promise<Ratio> {
    return this.fetch<Ratio>(`/ratios/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    });
  }

  /**
   * Delete a ratio
   */
  async deleteRatio(id: number): Promise<void> {
    await fetch(`${API_BASE}/ratios/${id}`, {
      method: 'DELETE',
    });
  }

  /**
   * Get all ratio quotes
   */
  async getRatioQuotes(): Promise<RatioQuote[]> {
    return this.fetch<RatioQuote[]>('/ratios/quotes');
  }

  /**
   * Get a single ratio quote
   */
  async getRatioQuote(id: number): Promise<RatioQuote> {
    return this.fetch<RatioQuote>(`/ratios/${id}/quote`);
  }

  /**
   * Get ratio history
   */
  async getRatioHistory(id: number, period = '1y'): Promise<RatioHistory> {
    return this.fetch<RatioHistory>(`/ratios/${id}/history?period=${period}`);
  }

  /**
   * Initialize system ratios
   */
  async initializeRatios(): Promise<void> {
    await fetch(`${API_BASE}/ratios/initialize`, {
      method: 'POST',
    });
  }

  // AI methods

  /**
   * Get AI settings
   */
  async getAISettings(): Promise<AISettings> {
    return this.fetch<AISettings>('/ai/settings');
  }

  /**
   * Update AI settings
   */
  async updateAISettings(data: AISettingsUpdate): Promise<AISettings> {
    return this.fetch<AISettings>('/ai/settings', {
      method: 'PUT',
      body: JSON.stringify(data),
    });
  }

  /**
   * Perform AI analysis (non-streaming)
   */
  async analyzeAI(request: AIAnalysisRequest): Promise<AIAnalysisResponse> {
    return this.fetch<AIAnalysisResponse>('/ai/analyze', {
      method: 'POST',
      body: JSON.stringify(request),
    });
  }

  /**
   * Perform AI analysis with streaming response
   * Returns an async generator that yields text chunks
   */
  async *analyzeAIStream(
    request: AIAnalysisRequest
  ): AsyncGenerator<string, void, unknown> {
    const response = await fetch(`${API_BASE}/ai/analyze/stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(request),
    });

    if (!response.ok) {
      throw new ApiError('AI analysis failed', 'AI_ERROR', response.status);
    }

    const reader = response.body?.getReader();
    if (!reader) {
      throw new ApiError('No response body', 'AI_ERROR', 500);
    }

    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          const data = line.slice(6);
          if (data === '[DONE]') {
            return;
          }
          if (data.startsWith('ERROR:')) {
            throw new ApiError(data.slice(7), 'AI_ERROR', 500);
          }
          yield data;
        }
      }
    }
  }

  // Alert methods

  /**
   * Get all alerts
   */
  async getAlerts(activeOnly = false, equityId?: number, ratioId?: number): Promise<Alert[]> {
    const params = new URLSearchParams();
    if (activeOnly) params.append('active_only', 'true');
    if (equityId) params.append('equity_id', equityId.toString());
    if (ratioId) params.append('ratio_id', ratioId.toString());
    const queryString = params.toString();
    const url = queryString ? `/alerts?${queryString}` : '/alerts';
    return this.fetch<Alert[]>(url);
  }

  /**
   * Get a single alert with history
   */
  async getAlert(id: number): Promise<AlertWithHistory> {
    return this.fetch<AlertWithHistory>(`/alerts/${id}`);
  }

  /**
   * Create a new alert
   */
  async createAlert(data: AlertCreate): Promise<Alert> {
    return this.fetch<Alert>('/alerts', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  /**
   * Update an alert
   */
  async updateAlert(id: number, data: AlertUpdate): Promise<Alert> {
    return this.fetch<Alert>(`/alerts/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    });
  }

  /**
   * Delete an alert
   */
  async deleteAlert(id: number): Promise<void> {
    await fetch(`${API_BASE}/alerts/${id}`, {
      method: 'DELETE',
    });
  }

  /**
   * Toggle an alert's active state
   */
  async toggleAlert(id: number): Promise<Alert> {
    return this.fetch<Alert>(`/alerts/${id}/toggle`, {
      method: 'POST',
    });
  }

  /**
   * Get alert statistics
   */
  async getAlertStats(): Promise<AlertStats> {
    return this.fetch<AlertStats>('/alerts/stats');
  }

  /**
   * Get all alert history
   */
  async getAllAlertHistory(limit = 100, offset = 0): Promise<AlertHistory[]> {
    return this.fetch<AlertHistory[]>(`/alerts/history?limit=${limit}&offset=${offset}`);
  }

  /**
   * Get history for a specific alert
   */
  async getAlertHistory(alertId: number, limit = 50): Promise<AlertHistory[]> {
    return this.fetch<AlertHistory[]>(`/alerts/${alertId}/history?limit=${limit}`);
  }

  /**
   * Manually check an alert's condition
   * @param notify - If true and condition is met, sends a real notification
   */
  async checkAlert(alertId: number, notify = false): Promise<AlertCheckResult & { notification?: { sent: boolean; error: string | null } }> {
    const url = notify ? `/alerts/${alertId}/check?notify=true` : `/alerts/${alertId}/check`;
    return this.fetch<AlertCheckResult & { notification?: { sent: boolean; error: string | null } }>(url, {
      method: 'POST',
    });
  }

  /**
   * Send a test Discord notification
   */
  async testDiscordNotification(): Promise<{ success: boolean; error: string | null }> {
    return this.fetch<{ success: boolean; error: string | null }>('/alerts/notifications/test', {
      method: 'POST',
    });
  }

  /**
   * Get notification service status
   */
  async getNotificationStatus(): Promise<NotificationStatus> {
    return this.fetch<NotificationStatus>('/alerts/notifications/status');
  }
}

export const api = new ApiClient();
export { ApiError };
