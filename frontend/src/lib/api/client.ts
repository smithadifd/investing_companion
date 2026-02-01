/**
 * API client for the Investing Companion backend
 */

import type {
  AIAnalysisRequest,
  AIAnalysisResponse,
  AISettings,
  AISettingsUpdate,
  ApiResponse,
  EquityDetail,
  EquitySearchResult,
  HistoryData,
  MarketOverview,
  Quote,
  Ratio,
  RatioCreate,
  RatioHistory,
  RatioQuote,
  RatioUpdate,
  TechnicalIndicators,
  TechnicalSummary,
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
  private async fetch<T>(path: string, options?: RequestInit): Promise<T> {
    const response = await fetch(`${API_BASE}${path}`, {
      headers: {
        'Content-Type': 'application/json',
        ...options?.headers,
      },
      ...options,
    });

    if (!response.ok) {
      let errorMessage = 'API request failed';
      let errorCode = 'UNKNOWN_ERROR';

      try {
        const errorData = await response.json();
        errorMessage = errorData.error?.message || errorMessage;
        errorCode = errorData.error?.code || errorCode;
      } catch {
        // Response wasn't JSON
      }

      throw new ApiError(errorMessage, errorCode, response.status);
    }

    const result: ApiResponse<T> = await response.json();
    return result.data;
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
}

export const api = new ApiClient();
export { ApiError };
