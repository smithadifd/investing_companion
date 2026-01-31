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
