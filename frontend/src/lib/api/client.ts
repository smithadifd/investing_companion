/**
 * API client for the Investing Companion backend
 */

import type {
  AIAnalysisRequest,
  NewsResponse,
  AIAnalysisResponse,
  AISettings,
  AISettingsUpdate,
  Alert,
  AlertCheckResult,
  AlertCreate,
  AlertDeliveryHealth,
  AlertHistory,
  AlertStats,
  AlertUpdate,
  AlertWithHistory,
  ApiResponse,
  AppSettings,
  AppSettingsUpdate,
  CalendarMonth,
  EconomicEvent,
  EconomicEventCreate,
  EconomicEventUpdate,
  EventFilters,
  EventImportance,
  EventStats,
  EventType,
  EquityDetail,
  EquitySearchResult,
  HistoryData,
  Lesson,
  LessonCreate,
  LessonUpdate,
  MarketOverview,
  Account,
  AccountCreate,
  AccountReconciliation,
  AccountUpdate,
  AdoptionResult,
  ImportKindRequest,
  ImportTriggerResult,
  TransactionReconciliation,
  ExposureResponse,
  NeedsAttentionResponse,
  TradeReadinessResponse,
  NotificationStatus,
  OutboxPublishResult,
  OutboxStatus,
  PaginatedMeta,
  PasswordChange,
  PerformanceReport,
  PortfolioSummary,
  PositionSizeRequest,
  PositionSizeResponse,
  PositionSummary,
  Quote,
  Ratio,
  RatioCreate,
  RatioHistory,
  RatioQuote,
  RatioUpdate,
  RegistrationStatus,
  SchwabConnectResponse,
  SchwabStatus,
  SessionInfo,
  TechnicalIndicators,
  TechnicalSummary,
  TokenRefresh,
  TokenResponse,
  Trade,
  TradeCreate,
  TradePair,
  TradeType,
  TradeUpdate,
  Trigger,
  TriggerCreate,
  TriggerUpdate,
  UpcomingEventsResponse,
  User,
  UserCreate,
  UserLogin,
  AllWatchlistMovers,
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
        // eslint-disable-next-line no-restricted-syntax -- refresh primitive: routing through this.fetch() would recurse
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

    // eslint-disable-next-line no-restricted-syntax -- this IS the shared auth wrapper primitive
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
        // eslint-disable-next-line no-restricted-syntax -- auth wrapper retry after token refresh
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
        // eslint-disable-next-line no-restricted-syntax -- fire-and-forget logout: deliberately swallows errors, no 401-retry
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

  // ==================== Schwab Connection Methods ====================

  /**
   * Get Schwab connection status
   */
  async getSchwabStatus(): Promise<SchwabStatus> {
    return this.fetch<SchwabStatus>('/schwab/status');
  }

  /**
   * Start the Schwab OAuth flow; redirect the browser to the returned auth_url
   */
  async connectSchwab(): Promise<SchwabConnectResponse> {
    return this.fetch<SchwabConnectResponse>('/schwab/connect', { method: 'POST' });
  }

  /**
   * Disconnect Schwab (forgets the stored token)
   */
  async disconnectSchwab(): Promise<SchwabStatus> {
    return this.fetch<SchwabStatus>('/schwab/disconnect', { method: 'DELETE' });
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
   * Get top movers across all watchlists
   */
  async getAllWatchlistMovers(limit = 10): Promise<AllWatchlistMovers> {
    return this.fetch<AllWatchlistMovers>(`/watchlists/movers?limit=${limit}`);
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
    await this.fetch<void>(`/watchlists/${id}`, {
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
    await this.fetch<void>(`/watchlists/${watchlistId}/items/${itemId}`, {
      method: 'DELETE',
    });
  }

  /**
   * Export a watchlist to JSON
   */
  async exportWatchlist(id: number): Promise<WatchlistExport> {
    // Raw un-enveloped JSON download, so it can't use this.fetch()'s data
    // unwrap — but it still carries the bearer and mirrors the 401 -> refresh
    // -> retry path (see getContextPackMarkdown).
    const doFetch = () => {
      const headers: Record<string, string> = {};
      if (this.accessToken) {
        headers['Authorization'] = `Bearer ${this.accessToken}`;
      }
      // eslint-disable-next-line no-restricted-syntax -- raw un-enveloped JSON body; carries bearer + 401-refresh inline
      return fetch(`${API_BASE}/watchlists/${id}/export`, { headers });
    };

    let response = await doFetch();
    if (response.status === 401 && this.refreshToken) {
      const refreshed = await this.refreshAccessToken();
      if (refreshed) {
        response = await doFetch();
      }
    }
    if (!response.ok) {
      throw new ApiError('Failed to export watchlist', 'EXPORT_ERROR', response.status);
    }
    return response.json();
  }

  // ==================== Advisor context pack ====================

  /**
   * Fetch the advisor context pack as markdown, for copy/download.
   * Returns text (not JSON), so it bypasses the JSON envelope wrapper.
   */
  async getContextPackMarkdown(): Promise<string> {
    const doFetch = () => {
      const headers: Record<string, string> = {};
      if (this.accessToken) {
        headers['Authorization'] = `Bearer ${this.accessToken}`;
      }
      // eslint-disable-next-line no-restricted-syntax -- returns text/markdown (not the JSON envelope); mirrors the 401->refresh path below
      return fetch(`${API_BASE}/export/context-pack?format=markdown`, {
        headers,
      });
    };

    let response = await doFetch();
    // Mirror this.fetch()'s 401 -> refresh -> retry so an expired access token
    // doesn't fail a button click on a long-open Settings page.
    if (response.status === 401 && this.refreshToken) {
      const refreshed = await this.refreshAccessToken();
      if (refreshed) {
        response = await doFetch();
      }
    }
    if (!response.ok) {
      throw new ApiError(
        'Failed to fetch context pack',
        'EXPORT_ERROR',
        response.status
      );
    }
    return response.text();
  }

  /**
   * Publish the context pack to the server-side outbox (advisor Drive folder).
   */
  async publishContextPack(): Promise<OutboxPublishResult> {
    return this.fetch<OutboxPublishResult>('/export/context-pack/publish', {
      method: 'POST',
    });
  }

  /**
   * Whether the server has an outbox configured, and the last publish time.
   */
  async getOutboxStatus(): Promise<OutboxStatus> {
    return this.fetch<OutboxStatus>('/export/outbox-status');
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

  // News methods

  /**
   * Get news for a specific symbol
   */
  async getSymbolNews(symbol: string, limit = 10): Promise<NewsResponse> {
    return this.fetch<NewsResponse>(`/news/${encodeURIComponent(symbol)}?limit=${limit}`);
  }

  /**
   * Get general market news
   */
  async getMarketNews(limit = 20): Promise<NewsResponse> {
    return this.fetch<NewsResponse>(`/news/market?limit=${limit}`);
  }

  /**
   * Get aggregated news for all watchlist symbols
   */
  async getWatchlistNews(limit = 20): Promise<NewsResponse> {
    return this.fetch<NewsResponse>(`/news/watchlist?limit=${limit}`);
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
    await this.fetch<void>(`/ratios/${id}`, {
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
    await this.fetch<void>('/ratios/initialize', {
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
    // SSE stream: needs the raw ReadableStream body (not the JSON envelope),
    // but still carries the bearer and mirrors the 401 -> refresh -> retry path.
    // R8 scopes the AI endpoints to the user, so the bearer is required.
    const doFetch = () => {
      const headers: Record<string, string> = {
        'Content-Type': 'application/json',
      };
      if (this.accessToken) {
        headers['Authorization'] = `Bearer ${this.accessToken}`;
      }
      // eslint-disable-next-line no-restricted-syntax -- SSE stream needs the raw ReadableStream body; carries bearer + 401-refresh inline
      return fetch(`${API_BASE}/ai/analyze/stream`, {
        method: 'POST',
        headers,
        body: JSON.stringify(request),
      });
    };

    let response = await doFetch();
    if (response.status === 401 && this.refreshToken) {
      const refreshed = await this.refreshAccessToken();
      if (refreshed) {
        response = await doFetch();
      }
    }

    if (!response.ok) {
      throw new ApiError('AI analysis failed', 'AI_ERROR', response.status);
    }

    const reader = response.body?.getReader();
    if (!reader) {
      throw new ApiError('No response body', 'AI_ERROR', 500);
    }

    const decoder = new TextDecoder();
    let buffer = '';
    // An SSE event may carry multiple `data:` lines; they must be re-joined with
    // '\n' (per spec) and dispatched on the blank-line boundary. This mirrors the
    // backend `format_sse` framing so multi-line streamed text is preserved.
    let dataLines: string[] = [];

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        if (line.startsWith('data:')) {
          // Strip 'data:' and at most one leading space (SSE spec).
          dataLines.push(line.replace(/^data: ?/, ''));
        } else if (line === '') {
          // Blank line: event boundary — assemble and dispatch.
          if (dataLines.length === 0) continue;
          const data = dataLines.join('\n');
          dataLines = [];
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
    await this.fetch<void>(`/alerts/${id}`, {
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
   * Get alert-delivery outbox health (pending/delivered/failed counts)
   */
  async getAlertDeliveryHealth(): Promise<AlertDeliveryHealth> {
    return this.fetch<AlertDeliveryHealth>('/alerts/delivery-health');
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

  // Dashboard methods

  /**
   * Get the needs-attention list (the morning pulse's ⚡ section)
   */
  async getNeedsAttention(): Promise<NeedsAttentionResponse> {
    return this.fetch<NeedsAttentionResponse>('/dashboard/needs-attention');
  }

  /**
   * Get actionable triggers (hit/approaching) with position and event context
   */
  async getTradeReadiness(): Promise<TradeReadinessResponse> {
    return this.fetch<TradeReadinessResponse>('/dashboard/trade-readiness');
  }

  // Trigger playbook methods

  /**
   * Get all triggers (standing orders), ordered by display_order
   */
  async getTriggers(includeRetired = false): Promise<Trigger[]> {
    const url = includeRetired ? '/triggers?include_retired=true' : '/triggers';
    return this.fetch<Trigger[]>(url);
  }

  /**
   * Get a single trigger
   */
  async getTrigger(id: number): Promise<Trigger> {
    return this.fetch<Trigger>(`/triggers/${id}`);
  }

  /**
   * Create a new trigger
   */
  async createTrigger(data: TriggerCreate): Promise<Trigger> {
    return this.fetch<Trigger>('/triggers', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  /**
   * Update a trigger (including its linked alerts)
   */
  async updateTrigger(id: number, data: TriggerUpdate): Promise<Trigger> {
    return this.fetch<Trigger>(`/triggers/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    });
  }

  /**
   * Delete a trigger
   */
  async deleteTrigger(id: number): Promise<void> {
    await this.fetch<void>(`/triggers/${id}`, {
      method: 'DELETE',
    });
  }

  /**
   * Mark a trigger as executed with an optional note (feeds the learning loop)
   */
  async executeTrigger(id: number, note?: string): Promise<Trigger> {
    return this.fetch<Trigger>(`/triggers/${id}/execute`, {
      method: 'POST',
      body: JSON.stringify({ note: note ?? null }),
    });
  }

  /**
   * Re-arm an executed trigger back to active
   */
  async rearmTrigger(id: number): Promise<Trigger> {
    return this.fetch<Trigger>(`/triggers/${id}/rearm`, {
      method: 'POST',
    });
  }

  // Trade methods

  /**
   * Get all trades
   */
  async getTrades(params?: {
    equity_id?: number;
    trade_type?: TradeType;
    start_date?: string;
    end_date?: string;
    account_id?: number;
    unassigned?: boolean;
    limit?: number;
    offset?: number;
  }): Promise<{ trades: Trade[]; total: number }> {
    const queryParams = new URLSearchParams();
    if (params?.equity_id) queryParams.append('equity_id', params.equity_id.toString());
    if (params?.trade_type) queryParams.append('trade_type', params.trade_type);
    if (params?.start_date) queryParams.append('start_date', params.start_date);
    if (params?.end_date) queryParams.append('end_date', params.end_date);
    if (params?.account_id) queryParams.append('account_id', params.account_id.toString());
    if (params?.unassigned) queryParams.append('unassigned', 'true');
    if (params?.limit) queryParams.append('limit', params.limit.toString());
    if (params?.offset) queryParams.append('offset', params.offset.toString());

    const queryString = queryParams.toString();
    const url = queryString ? `/trades?${queryString}` : '/trades';

    // This endpoint returns the paginated meta envelope, so it bypasses
    // this.fetch()'s data-only unwrap — but still carries the bearer and
    // mirrors the 401 -> refresh -> retry path.
    const doFetch = () => {
      const headers: Record<string, string> = {};
      if (this.accessToken) {
        headers['Authorization'] = `Bearer ${this.accessToken}`;
      }
      // eslint-disable-next-line no-restricted-syntax -- needs the paginated meta envelope, not this.fetch()'s data-only unwrap; carries bearer + 401-refresh inline
      return fetch(`${API_BASE}${url}`, { headers });
    };

    let response = await doFetch();
    if (response.status === 401 && this.refreshToken) {
      const refreshed = await this.refreshAccessToken();
      if (refreshed) {
        response = await doFetch();
      }
    }

    if (!response.ok) {
      throw new ApiError('Failed to fetch trades', 'FETCH_ERROR', response.status);
    }

    const result = await response.json();
    return {
      trades: result.data,
      total: result.meta?.total || result.data.length,
    };
  }

  /**
   * Get a single trade
   */
  async getTrade(id: number): Promise<Trade> {
    return this.fetch<Trade>(`/trades/${id}`);
  }

  /**
   * Create a new trade
   */
  async createTrade(data: TradeCreate): Promise<Trade> {
    return this.fetch<Trade>('/trades', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  /**
   * Update a trade
   */
  async updateTrade(id: number, data: TradeUpdate): Promise<Trade> {
    return this.fetch<Trade>(`/trades/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    });
  }

  /**
   * Delete a trade
   */
  async deleteTrade(id: number): Promise<void> {
    await this.fetch(`/trades/${id}`, { method: 'DELETE' });
  }

  // Lesson (learning loop) methods

  /**
   * Get lessons, newest first
   */
  async getLessons(params?: {
    symbol?: string;
    tag?: string;
    limit?: number;
    offset?: number;
  }): Promise<Lesson[]> {
    const queryParams = new URLSearchParams();
    if (params?.symbol) queryParams.append('symbol', params.symbol);
    if (params?.tag) queryParams.append('tag', params.tag);
    if (params?.limit) queryParams.append('limit', params.limit.toString());
    if (params?.offset) queryParams.append('offset', params.offset.toString());

    const queryString = queryParams.toString();
    return this.fetch<Lesson[]>(queryString ? `/lessons?${queryString}` : '/lessons');
  }

  /**
   * Capture a lesson (from a closing trade, or standalone by symbol)
   */
  async createLesson(data: LessonCreate): Promise<Lesson> {
    return this.fetch<Lesson>('/lessons', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  /**
   * Update a lesson
   */
  async updateLesson(id: number, data: LessonUpdate): Promise<Lesson> {
    return this.fetch<Lesson>(`/lessons/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    });
  }

  /**
   * Delete a lesson
   */
  async deleteLesson(id: number): Promise<void> {
    await this.fetch(`/lessons/${id}`, { method: 'DELETE' });
  }

  /**
   * Get portfolio summary
   */
  async getPortfolio(byAccount = false): Promise<PortfolioSummary> {
    const url = byAccount
      ? '/trades/portfolio?by_account=true'
      : '/trades/portfolio';
    return this.fetch<PortfolioSummary>(url);
  }

  // Account methods (multi-account positions)

  async getAccounts(): Promise<Account[]> {
    return this.fetch<Account[]>('/accounts');
  }

  async createAccount(data: AccountCreate): Promise<Account> {
    return this.fetch<Account>('/accounts', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async updateAccount(id: number, data: AccountUpdate): Promise<Account> {
    return this.fetch<Account>(`/accounts/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    });
  }

  async deleteAccount(id: number): Promise<void> {
    await this.fetch(`/accounts/${id}`, { method: 'DELETE' });
  }

  /**
   * Read-only §6 reconciliation view for one account (Schwab-vs-IC deltas).
   * 409 when the account has no active Schwab link.
   */
  async getAccountReconciliation(
    accountId: number
  ): Promise<AccountReconciliation> {
    return this.fetch<AccountReconciliation>(
      `/accounts/${accountId}/reconciliation`
    );
  }

  /**
   * Transactions activity reconciliation — broker fills vs logged IC trades.
   * 409 when the account has no active Schwab link.
   */
  async getAccountTransactionReconciliation(
    accountId: number,
    days = 90
  ): Promise<TransactionReconciliation> {
    return this.fetch<TransactionReconciliation>(
      `/accounts/${accountId}/reconciliation/transactions?days=${days}`
    );
  }

  /**
   * Pull positions and/or transactions from Schwab for a linked account.
   * 409 = not linked or Schwab needs (re)connecting; 502 = Schwab said no.
   */
  async triggerBrokerImport(
    accountId: number,
    kind: ImportKindRequest = 'both'
  ): Promise<ImportTriggerResult> {
    return this.fetch<ImportTriggerResult>(`/accounts/${accountId}/import`, {
      method: 'POST',
      body: JSON.stringify({ kind }),
    });
  }

  /**
   * Adopt the reconciliation delta into synthetic, provenance-stamped trades.
   * Replay-safe: re-adopting against the same import run creates no duplicate.
   */
  async adoptAccountReconciliation(
    accountId: number
  ): Promise<AdoptionResult> {
    return this.fetch<AdoptionResult>(
      `/accounts/${accountId}/reconciliation/adopt`,
      { method: 'POST' }
    );
  }

  /**
   * Held exposure grouped by single-catalyst cluster
   */
  async getExposure(): Promise<ExposureResponse> {
    return this.fetch<ExposureResponse>('/dashboard/exposure');
  }

  /**
   * Get performance report
   */
  async getPerformance(startDate?: string, endDate?: string): Promise<PerformanceReport> {
    const params = new URLSearchParams();
    if (startDate) params.append('start_date', startDate);
    if (endDate) params.append('end_date', endDate);
    const queryString = params.toString();
    const url = queryString ? `/trades/performance?${queryString}` : '/trades/performance';
    return this.fetch<PerformanceReport>(url);
  }

  /**
   * Get trade pairs (matched trades for P&L)
   */
  async getTradePairs(equityId?: number, limit = 100): Promise<TradePair[]> {
    const params = new URLSearchParams();
    if (equityId) params.append('equity_id', equityId.toString());
    params.append('limit', limit.toString());
    return this.fetch<TradePair[]>(`/trades/pairs?${params.toString()}`);
  }

  /**
   * Get position for a specific equity
   */
  async getPosition(equityId: number): Promise<PositionSummary> {
    return this.fetch<PositionSummary>(`/trades/positions/${equityId}`);
  }

  /**
   * Calculate position size
   */
  async calculatePositionSize(data: PositionSizeRequest): Promise<PositionSizeResponse> {
    return this.fetch<PositionSizeResponse>('/trades/position-size', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  // =========================================================================
  // Economic Events API
  // =========================================================================

  /**
   * Get events with optional filtering
   */
  async getEvents(filters?: EventFilters & { limit?: number; offset?: number }): Promise<EconomicEvent[]> {
    const params = new URLSearchParams();
    if (filters) {
      if (filters.start_date) params.append('start_date', filters.start_date);
      if (filters.end_date) params.append('end_date', filters.end_date);
      if (filters.event_types) {
        filters.event_types.forEach(t => params.append('event_types', t));
      }
      if (filters.equity_symbol) params.append('equity_symbol', filters.equity_symbol);
      if (filters.watchlist_id) params.append('watchlist_id', filters.watchlist_id.toString());
      if (filters.watchlist_only) params.append('watchlist_only', 'true');
      if (filters.importance) params.append('importance', filters.importance);
      if (filters.include_past) params.append('include_past', 'true');
      if (filters.limit) params.append('limit', filters.limit.toString());
      if (filters.offset) params.append('offset', filters.offset.toString());
    }
    const queryString = params.toString();
    const url = queryString ? `/events?${queryString}` : '/events';
    return this.fetch<EconomicEvent[]>(url);
  }

  /**
   * Get upcoming events
   */
  async getUpcomingEvents(
    days = 7,
    filters?: { event_types?: EventType[]; watchlist_only?: boolean; limit?: number }
  ): Promise<UpcomingEventsResponse> {
    const params = new URLSearchParams();
    params.append('days', days.toString());
    if (filters?.event_types) {
      filters.event_types.forEach(t => params.append('event_types', t));
    }
    if (filters?.watchlist_only) params.append('watchlist_only', 'true');
    if (filters?.limit) params.append('limit', filters.limit.toString());
    return this.fetch<UpcomingEventsResponse>(`/events/upcoming?${params.toString()}`);
  }

  /**
   * Get calendar month data
   */
  async getCalendarMonth(
    year: number,
    month: number,
    filters?: { event_types?: EventType[]; watchlist_only?: boolean }
  ): Promise<CalendarMonth> {
    const params = new URLSearchParams();
    if (filters?.event_types) {
      filters.event_types.forEach(t => params.append('event_types', t));
    }
    if (filters?.watchlist_only) params.append('watchlist_only', 'true');
    const queryString = params.toString();
    const url = queryString
      ? `/events/calendar/${year}/${month}?${queryString}`
      : `/events/calendar/${year}/${month}`;
    return this.fetch<CalendarMonth>(url);
  }

  /**
   * Get events for watchlist equities
   */
  async getWatchlistEvents(watchlistId?: number, days = 14): Promise<EconomicEvent[]> {
    const params = new URLSearchParams();
    if (watchlistId) params.append('watchlist_id', watchlistId.toString());
    params.append('days', days.toString());
    return this.fetch<EconomicEvent[]>(`/events/watchlist?${params.toString()}`);
  }

  /**
   * Get event statistics
   */
  async getEventStats(): Promise<EventStats> {
    return this.fetch<EventStats>('/events/stats');
  }

  /**
   * Get a single event
   */
  async getEvent(eventId: string): Promise<EconomicEvent> {
    return this.fetch<EconomicEvent>(`/events/${eventId}`);
  }

  /**
   * Create a custom event
   */
  async createEvent(data: EconomicEventCreate): Promise<EconomicEvent> {
    return this.fetch<EconomicEvent>('/events', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  /**
   * Update an event
   */
  async updateEvent(eventId: string, data: EconomicEventUpdate): Promise<EconomicEvent> {
    return this.fetch<EconomicEvent>(`/events/${eventId}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    });
  }

  /**
   * Delete a custom event
   */
  async deleteEvent(eventId: string): Promise<void> {
    await this.fetch<void>(`/events/${eventId}`, {
      method: 'DELETE',
    });
  }

  /**
   * Refresh events for a specific equity from Yahoo Finance
   */
  async refreshEquityEvents(symbol: string): Promise<EconomicEvent[]> {
    return this.fetch<EconomicEvent[]>(`/events/refresh/${symbol}`, {
      method: 'POST',
    });
  }

  /**
   * Refresh events for all watchlist equities
   */
  async refreshWatchlistEvents(watchlistId?: number): Promise<{ events_updated: number }> {
    const params = new URLSearchParams();
    if (watchlistId) params.append('watchlist_id', watchlistId.toString());
    const queryString = params.toString();
    const url = queryString ? `/events/refresh/watchlist?${queryString}` : '/events/refresh/watchlist';
    return this.fetch<{ events_updated: number }>(url, {
      method: 'POST',
    });
  }

  /**
   * Get events for a specific equity
   */
  async getEquityEvents(symbol: string, includePast = false, limit = 10): Promise<EconomicEvent[]> {
    const params = new URLSearchParams();
    if (includePast) params.append('include_past', 'true');
    params.append('limit', limit.toString());
    return this.fetch<EconomicEvent[]>(`/equity/${symbol}/events?${params.toString()}`);
  }

  /**
   * Delete all auto-fetched events for an equity (untrack)
   */
  async deleteEquityEvents(symbol: string): Promise<{ symbol: string; events_deleted: number }> {
    return this.fetch<{ symbol: string; events_deleted: number }>(`/events/equity/${symbol}`, {
      method: 'DELETE',
    });
  }
}

export const api = new ApiClient();
export { ApiError };
