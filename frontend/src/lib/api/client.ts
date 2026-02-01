/**
 * API client for the Investing Companion backend
 */

import type {
  ApiResponse,
  EquityDetail,
  EquitySearchResult,
  HistoryData,
  Quote,
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
}

export const api = new ApiClient();
export { ApiError };
