/**
 * API client for the Investing Companion backend
 */

import type {
  ApiResponse,
  EquityDetail,
  EquitySearchResult,
  HistoryData,
  Quote,
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
}

export const api = new ApiClient();
export { ApiError };
