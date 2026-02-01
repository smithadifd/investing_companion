/**
 * API type definitions
 * Note: Decimal fields from Python API are serialized as strings
 */

export interface EquitySearchResult {
  symbol: string;
  name: string;
  exchange: string | null;
  asset_type: string;
}

export interface Quote {
  symbol: string;
  price: number | string;
  change: number | string;
  change_percent: number | string;
  open: number | string;
  high: number | string;
  low: number | string;
  previous_close: number | string | null;
  volume: number;
  market_cap: number | null;
  timestamp: string;
}

export interface OHLCVData {
  timestamp: string;
  open: number | string;
  high: number | string;
  low: number | string;
  close: number | string;
  volume: number | null;
}

export interface HistoryData {
  symbol: string;
  interval: string;
  history: OHLCVData[];
}

export interface Fundamentals {
  market_cap: number | null;
  enterprise_value: number | null;
  pe_ratio: number | string | null;
  forward_pe: number | string | null;
  peg_ratio: number | string | null;
  price_to_book: number | string | null;
  price_to_sales: number | string | null;
  eps_ttm: number | string | null;
  dividend_yield: number | string | null;
  beta: number | string | null;
  week_52_high: number | string | null;
  week_52_low: number | string | null;
  avg_volume: number | null;
  profit_margin: number | string | null;
}

export interface EquityDetail {
  symbol: string;
  name: string;
  exchange: string | null;
  asset_type: string;
  sector: string | null;
  industry: string | null;
  country: string;
  currency: string;
  quote: Quote | null;
  fundamentals: Fundamentals | null;
}

export interface ResponseMeta {
  timestamp: string;
  request_id?: string;
}

export interface ApiResponse<T> {
  data: T;
  meta: ResponseMeta;
}

export interface ApiError {
  error: {
    code: string;
    message: string;
    details?: Record<string, unknown>;
  };
}

// Watchlist types
export interface WatchlistItemEquity {
  id: number;
  symbol: string;
  name: string;
  exchange: string | null;
  sector: string | null;
}

export interface WatchlistItem {
  id: number;
  watchlist_id: number;
  equity_id: number;
  notes: string | null;
  target_price: number | string | null;
  thesis: string | null;
  added_at: string;
  equity: WatchlistItemEquity;
  quote: Quote | null;
}

export interface WatchlistSummary {
  id: number;
  name: string;
  description: string | null;
  is_default: boolean;
  item_count: number;
  created_at: string;
  updated_at: string;
}

export interface Watchlist {
  id: number;
  name: string;
  description: string | null;
  is_default: boolean;
  items: WatchlistItem[];
  created_at: string;
  updated_at: string;
}

export interface WatchlistCreate {
  name: string;
  description?: string;
  is_default?: boolean;
}

export interface WatchlistUpdate {
  name?: string;
  description?: string;
  is_default?: boolean;
}

export interface WatchlistItemCreate {
  equity_id?: number;
  symbol?: string;
  notes?: string;
  target_price?: number;
  thesis?: string;
}

export interface WatchlistItemUpdate {
  notes?: string;
  target_price?: number;
  thesis?: string;
}

export interface WatchlistExportItem {
  symbol: string;
  name: string;
  notes: string | null;
  target_price: number | string | null;
  thesis: string | null;
  added_at: string;
}

export interface WatchlistExport {
  name: string;
  description: string | null;
  exported_at: string;
  items: WatchlistExportItem[];
}

export interface WatchlistImportItem {
  symbol: string;
  notes?: string;
  target_price?: number;
  thesis?: string;
}

export interface WatchlistImport {
  name: string;
  description?: string;
  items: WatchlistImportItem[];
}

// Technical indicators types
export interface TechnicalIndicators {
  timestamps: string[];
  closes: number[];
  sma_20: (number | null)[];
  sma_50: (number | null)[];
  sma_200: (number | null)[];
  ema_12: (number | null)[];
  ema_26: (number | null)[];
  rsi: (number | null)[];
  macd: (number | null)[];
  macd_signal: (number | null)[];
  macd_histogram: (number | null)[];
  bb_upper: (number | null)[];
  bb_middle: (number | null)[];
  bb_lower: (number | null)[];
}

export interface TechnicalSummary {
  price: number;
  sma_20: number | null;
  sma_50: number | null;
  sma_200: number | null;
  rsi: number | null;
  macd: number | null;
  macd_signal: number | null;
  above_sma_20: boolean | null;
  above_sma_50: boolean | null;
  above_sma_200: boolean | null;
  rsi_signal: 'overbought' | 'oversold' | 'neutral' | null;
}
