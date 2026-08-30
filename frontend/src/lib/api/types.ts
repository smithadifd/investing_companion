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
  /** Provider that produced the quote (e.g. "yahoo", "stooq"). */
  source?: string | null;
  /** True when served by a fallback because the primary was unavailable. */
  stale?: boolean;
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

// Tiered entry zones
export interface EntryZone {
  tier: string;
  low: number | string | null;
  high: number | string | null;
}

export type ZoneStatusValue =
  | 'in_zone'
  | 'approaching'
  | 'above'
  | 'below'
  | 'unknown';

export interface EntryZoneStatus extends EntryZone {
  status: ZoneStatusValue;
  distance_percent: number | string | null;
}

export interface WatchlistItem {
  id: number;
  watchlist_id: number;
  equity_id: number;
  notes: string | null;
  target_price: number | string | null;
  thesis: string | null;
  track_calendar: boolean;
  entry_zones: EntryZone[];
  zone_statuses: EntryZoneStatus[];
  catalyst_tags: string[];
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
  track_calendar?: boolean;
  entry_zones?: EntryZone[];
  catalyst_tags?: string[];
}

export interface WatchlistItemUpdate {
  notes?: string;
  target_price?: number;
  thesis?: string;
  track_calendar?: boolean;
  // Explicit null clears the zones; omitted leaves them unchanged
  entry_zones?: EntryZone[] | null;
  // Explicit null (or []) clears catalyst tags; omitted leaves them unchanged
  catalyst_tags?: string[] | null;
}

export interface WatchlistExportItem {
  symbol: string;
  name: string;
  notes: string | null;
  target_price: number | string | null;
  thesis: string | null;
  entry_zones: EntryZone[] | null;
  catalyst_tags?: string[] | null;
  track_calendar?: boolean;
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
  entry_zones?: EntryZone[] | null;
  catalyst_tags?: string[] | null;
  track_calendar?: boolean;
}

export interface WatchlistImport {
  name: string;
  description?: string;
  items: WatchlistImportItem[];
}

export interface MoverItem {
  symbol: string;
  name: string;
  price: number;
  change: number;
  change_percent: number;
  watchlist_id: number;
  watchlist_name: string;
}

export interface AllWatchlistMovers {
  gainers: MoverItem[];
  losers: MoverItem[];
  total_items: number;
  watchlist_count: number;
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

// Market overview types
export interface IndexQuote {
  symbol: string;
  name: string;
  price: number | string;
  change: number | string;
  change_percent: number | string;
  timestamp: string;
}

export interface SectorPerformance {
  sector: string;
  symbol: string;
  change_percent: number | string;
  price: number | string | null;
  volume: number | null;
}

export interface MarketMover {
  symbol: string;
  name: string;
  price: number | string;
  change: number | string;
  change_percent: number | string;
  volume: number | null;
}

export interface CurrencyCommodity {
  symbol: string;
  name: string;
  price: number | string;
  change: number | string;
  change_percent: number | string;
  category: 'currency' | 'commodity' | 'crypto';
}

export interface MarketOverview {
  indices: IndexQuote[];
  sectors: SectorPerformance[];
  gainers: MarketMover[];
  losers: MarketMover[];
  currencies_commodities: CurrencyCommodity[];
  timestamp: string;
}

// Ratio types
export interface Ratio {
  id: number;
  name: string;
  numerator_symbol: string;
  denominator_symbol: string;
  description: string | null;
  category: string;
  is_system: boolean;
  is_favorite: boolean;
  created_at: string;
  updated_at: string;
}

export interface RatioCreate {
  name: string;
  numerator_symbol: string;
  denominator_symbol: string;
  description?: string;
  category?: string;
  is_favorite?: boolean;
}

export interface RatioUpdate {
  name?: string;
  description?: string;
  is_favorite?: boolean;
}

export interface RatioDataPoint {
  timestamp: string;
  numerator_close: number | string;
  denominator_close: number | string;
  ratio_value: number | string;
}

export interface RatioHistory {
  ratio: Ratio;
  history: RatioDataPoint[];
  current_value: number | string | null;
  change_1d: number | string | null;
  change_1w: number | string | null;
  change_1m: number | string | null;
}

export interface RatioQuote {
  id: number;
  name: string;
  numerator_symbol: string;
  denominator_symbol: string;
  current_value: number | string;
  change_1d: number | string | null;
  change_percent_1d: number | string | null;
  timestamp: string;
}

// AI types
export type AnalysisType = 'equity' | 'ratio' | 'watchlist' | 'general';
// Current Claude lineup (kept in sync with backend AIModel enum). Sonnet 5 is
// the default; the backend resolves an omitted `model` to its configured default.
export type AIModel = 'claude-sonnet-5' | 'claude-opus-4-8' | 'claude-haiku-4-5-20251001';

export interface AIAnalysisRequest {
  analysis_type: AnalysisType;
  prompt: string;
  symbol?: string;
  ratio_id?: number;
  watchlist_id?: number;
  model?: AIModel;
  include_context?: boolean;
}

export interface AIAnalysisResponse {
  analysis_type: AnalysisType;
  prompt: string;
  response: string;
  model: string;
  context_summary: string | null;
  timestamp: string;
  cached?: boolean;
}

export interface AISettings {
  has_api_key: boolean;
  default_model: string;
  custom_instructions: string | null;
}

export interface AISettingsUpdate {
  api_key?: string;
  default_model?: string;
  custom_instructions?: string;
}

// Alert types
export type AlertConditionType =
  | 'above'
  | 'below'
  | 'crosses_above'
  | 'crosses_below'
  | 'percent_up'
  | 'percent_down'
  | 'percent_from_high'
  | 'entry_zone';

export type AlertTargetType = 'equity' | 'ratio';

export interface AlertTargetInfo {
  type: AlertTargetType;
  id: number;
  symbol: string;
  name: string;
}

export interface Alert {
  id: number;
  name: string;
  notes: string | null;
  equity_id: number | null;
  ratio_id: number | null;
  // entry_zone alerts: the linked watchlist item + per-tier dedup state
  watchlist_item_id?: number | null;
  zone_state?: Record<
    string,
    { armed: boolean; last_fired_at: string | null }
  > | null;
  condition_type: AlertConditionType;
  threshold_value: number | string;
  comparison_period: string | null;
  cooldown_minutes: number;
  is_active: boolean;
  last_triggered_at: string | null;
  last_checked_value: number | string | null;
  confirm_checks: number | null;
  consecutive_met_count: number;
  created_at: string;
  updated_at: string;
  target: AlertTargetInfo | null;
}

export interface AlertCreate {
  name: string;
  notes?: string;
  equity_symbol?: string;
  ratio_id?: number;
  // entry_zone alerts target a watchlist item; threshold is not used
  watchlist_item_id?: number;
  condition_type: AlertConditionType;
  threshold_value?: number;
  comparison_period?: string;
  cooldown_minutes?: number;
  confirm_checks?: number;
  is_active?: boolean;
}

export interface AlertUpdate {
  name?: string;
  notes?: string;
  condition_type?: AlertConditionType;
  threshold_value?: number;
  comparison_period?: string;
  cooldown_minutes?: number;
  confirm_checks?: number | null;
  is_active?: boolean;
}

export interface AlertHistory {
  id: number;
  alert_id: number;
  triggered_at: string;
  triggered_value: number | string;
  threshold_value: number | string;
  notification_sent: boolean;
  notification_channel: string | null;
  notification_error: string | null;
}

export interface AlertWithHistory extends Alert {
  recent_history: AlertHistory[];
}

export interface AlertStats {
  total_alerts: number;
  active_alerts: number;
  triggered_today: number;
  triggered_this_week: number;
}

/** Health of the alert-notification delivery outbox. Healthy counts mean a
 * quiet feed can be trusted: silence is "not triggered," not "a send was lost." */
export interface AlertDeliveryHealth {
  pending: number;
  delivered: number;
  failed: number;
  last_delivered_at: string | null;
  oldest_pending_at: string | null;
}

export interface AlertCheckResult {
  alert_id: number;
  is_triggered: boolean;
  current_value: number | string;
  threshold_value: number | string;
  condition_met: string;
  should_notify: boolean;
}

export interface NotificationStatus {
  discord: {
    configured: boolean;
  };
}

// Dashboard types
export type NeedsAttentionKind = 'alert_triggered' | 'alert_approaching' | 'target_near';

export interface NeedsAttentionItem {
  kind: NeedsAttentionKind;
  title: string;
  symbol: string | null;
  detail: string | null;
  distance_percent: number | string | null;
  last_checked_value: number | string | null;
  target_price: number | string | null;
  last_triggered_at: string | null;
}

export interface NeedsAttentionResponse {
  items: NeedsAttentionItem[];
}

// Trigger playbook types
export type TriggerStatus = 'active' | 'executed' | 'retired';

// 'disarmed' = linked alerts exist but every one is deactivated (nothing is
// watching). Distinct from 'unwatched', which means no alerts were ever linked.
export type TriggerSignal =
  | 'armed'
  | 'approaching'
  | 'hit'
  | 'unwatched'
  | 'disarmed';

export interface TriggerAlertSummary {
  id: number;
  name: string;
  is_active: boolean;
  distance_percent: number | string | null;
  last_triggered_at: string | null;
}

export interface Trigger {
  id: number;
  name: string;
  rule: string;
  action: string;
  tier: string | null;
  display_order: number;
  status: TriggerStatus;
  // Null on executed/retired triggers - closed history has no live signal
  signal: TriggerSignal | null;
  executed_at: string | null;
  execution_note: string | null;
  alerts: TriggerAlertSummary[];
  created_at: string;
}

export interface TriggerCreate {
  name: string;
  rule: string;
  action: string;
  tier?: string;
  display_order?: number;
  alert_ids?: number[];
}

export interface TriggerUpdate {
  name?: string;
  rule?: string;
  action?: string;
  tier?: string;
  display_order?: number;
  alert_ids?: number[];
}

// Trade-readiness card types (dashboard)
export interface ReadinessPosition {
  symbol: string;
  quantity: number | string;
  avg_cost_basis: number | string;
}

export interface ReadinessEvent {
  title: string;
  symbol: string | null;
  event_date: string;
  days_away: number;
}

export interface ReadinessLesson {
  id: number;
  symbol: string;
  thesis_outcome: string;
  lesson: string;
  tags: string[];
  recorded_at: string;
}

export interface ReadinessCorrelation {
  catalyst: string;
  held_symbols: string[];
}

// Catalyst-cluster exposure (held value grouped by single catalyst)
export interface CatalystCluster {
  catalyst: string;
  symbols: string[];
  value: number | string | null;
  percent_of_portfolio: number | string | null;
  position_count: number;
}

export interface ExposureResponse {
  catalysts: CatalystCluster[];
}

export interface TradeReadinessItem {
  trigger_id: number;
  name: string;
  tier: string | null;
  rule: string;
  action: string;
  signal: TriggerSignal;
  distance_percent: number | string | null;
  last_triggered_at: string | null;
  symbols: string[];
  positions: ReadinessPosition[];
  upcoming_events: ReadinessEvent[];
  inactive_alert_count: number;
  lessons: ReadinessLesson[];
  correlations: ReadinessCorrelation[];
}

export interface TradeReadinessResponse {
  items: TradeReadinessItem[];
}

// Auth types
export interface User {
  id: string;
  email: string;
  is_active: boolean;
  is_admin: boolean;
  created_at: string;
  last_login_at: string | null;
}

export interface UserCreate {
  email: string;
  password: string;
  password_confirm: string;
}

export interface UserLogin {
  email: string;
  password: string;
}

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

export interface TokenRefresh {
  refresh_token: string;
}

export interface PasswordChange {
  current_password: string;
  new_password: string;
  new_password_confirm: string;
}

export interface SessionInfo {
  id: string;
  user_agent: string | null;
  ip_address: string | null;
  created_at: string;
  expires_at: string;
  is_current: boolean;
}

export interface RegistrationStatus {
  enabled: boolean;
  message: string | null;
}

// Settings types
export interface AppSettings {
  claude_api_key: string | null;
  alpha_vantage_api_key: string | null;
  polygon_api_key: string | null;
  discord_webhook_url: string | null;
  default_watchlist_id: number | null;
  theme: string;
  morning_notification_time: string;
  eod_notification_time: string;
  // Tier-1 advisory agents (docs/issues/014) - default OFF; schema + rails
  // only until each agent's follow-up sub-PR lands.
  news_agent_enabled: boolean;
  trade_journal_agent_enabled: boolean;
  strategy_agent_enabled: boolean;
}

export interface AppSettingsUpdate {
  claude_api_key?: string;
  alpha_vantage_api_key?: string;
  polygon_api_key?: string;
  discord_webhook_url?: string;
  default_watchlist_id?: number;
  theme?: string;
  morning_notification_time?: string;
  eod_notification_time?: string;
  news_agent_enabled?: boolean;
  trade_journal_agent_enabled?: boolean;
  strategy_agent_enabled?: boolean;
}

// Schwab connection (opt-in brokerage transaction/position sync)
export interface SchwabStatus {
  configured: boolean;
  connected: boolean;
  needs_reconnect: boolean;
  token_age_days: number | null;
  expires_in_days: number | null;
  /**
   * Whether the server also opted Schwab into the extended-hours quote role
   * (SCHWAB_QUOTES_ENABLED, default off). Informational only — it decides
   * what the settings copy can honestly claim connecting does, not what the
   * connection is for.
   */
  quotes_enabled: boolean;
}

export interface SchwabConnectResponse {
  auth_url: string;
}

// Account types (multi-account positions)
export interface Account {
  id: number;
  name: string;
  broker: string | null;
  account_type: string | null;
  risk_profile: string | null;
  display_order: number;
  created_at: string;
  updated_at: string;
}

export interface AccountCreate {
  name: string;
  broker?: string | null;
  account_type?: string | null;
  risk_profile?: string | null;
  display_order?: number;
}

export interface AccountUpdate {
  name?: string;
  broker?: string | null;
  account_type?: string | null;
  risk_profile?: string | null;
  display_order?: number;
}

export interface AccountRef {
  id: number;
  name: string;
  account_type: string | null;
}

// Schwab account link (hash -> IC account mapping, §1/§4)
export interface AccountLink {
  id: number;
  account_hash: string;
  source: string;
  account_id: number | null;
  status: 'active' | 'orphaned';
  created_at: string;
  updated_at: string;
}

// Read-only §6 reconciliation view. Strictly a display of Schwab-vs-IC deltas
// — no adopt/mutation surface. Decimal fields arrive as strings from the API.
export interface ReconciliationPosition {
  symbol: string;
  asset_type: string | null;
  eligible: boolean;
  ineligible_reason: string | null;
  schwab_quantity: string | null;
  ic_quantity: string | null;
  quantity_delta: string; // never null
  schwab_basis: string | null;
  ic_basis: string | null;
  basis_delta: string | null;
  ledger_inconsistent: boolean;
}

export interface AccountReconciliation {
  last_import_at: string | null;
  never_imported: boolean;
  newer_failed_import_at: string | null;
  positions: ReconciliationPosition[];
}

// Per-row outcome of adopting a reconciliation delta into a synthetic trade.
export interface AdoptedTrade {
  symbol: string;
  equity_id: number;
  trade_type: TradeType;
  quantity: string;
  price: string | null;
  basis_is_estimated: boolean;
  status: 'created' | 'already_adopted';
  trade_id: number | null;
}

export interface SkippedPosition {
  symbol: string;
  quantity_delta: string;
  reason: string;
  detail: string | null;
}

export interface AdoptionResult {
  account_id: number;
  source_import_run_id: number;
  adopted: AdoptedTrade[];
  skipped: SkippedPosition[];
}

// One BrokerImportRun as returned by an import trigger or CSV upload.
// `notes` carries the clamped HISTORY GAP on a *complete* transactions run:
// the pull succeeded but its requested window predated Schwab's 60-day
// horizon, and the skipped span is only recoverable via a broker-CSV upload.
export interface ImportRunSummary {
  id: number;
  source: string;
  kind: 'positions' | 'transactions';
  status: 'complete' | 'failed';
  window_start: string | null;
  window_end: string | null;
  item_count: number | null;
  error_message: string | null;
  notes: string | null;
  created_at: string;
}

export interface ImportTriggerResult {
  account_id: number;
  runs: ImportRunSummary[];
}

export type ImportKindRequest = 'positions' | 'transactions' | 'both';

export interface CsvSkippedRow {
  row_number: number;
  reason: string;
  detail: string | null;
}

export interface CsvImportResult {
  account_id: number;
  run: ImportRunSummary;
  imported_count: number;
  skipped: CsvSkippedRow[];
  earliest_occurred_at: string | null;
  latest_occurred_at: string | null;
}

// Transactions activity reconciliation — which individual fills were never
// written down (`broker_only`), vs logged trades the broker doesn't report
// (`ic_only`). `non_trade` rows are cash movements: shown, never matched.
export type TransactionMatchStatus =
  | 'matched'
  | 'broker_only'
  | 'ic_only'
  | 'non_trade';

export interface TransactionMatch {
  status: TransactionMatchStatus;
  broker_transaction_id: number | null;
  external_transaction_id: string | null;
  broker_source: string | null;
  broker_type: string | null;
  broker_side: TradeType | null;
  broker_quantity: string | null;
  broker_price: string | null;
  broker_net_amount: string | null;
  broker_occurred_at: string | null;
  trade_id: number | null;
  ic_side: TradeType | null;
  ic_quantity: string | null;
  ic_price: string | null;
  ic_executed_at: string | null;
  symbol: string | null;
  note: string | null;
}

export interface TransactionReconciliation {
  window_start: string;
  window_end: string;
  last_import_at: string | null;
  never_imported: boolean;
  newer_failed_import_at: string | null;
  history_gap: boolean;
  history_gap_note: string | null;
  transaction_history_limit_days: number;
  matched_count: number;
  broker_only_count: number;
  ic_only_count: number;
  transactions: TransactionMatch[];
}

// Trade types
//
// The four FILLS plus the two equity-scoped rows that share the `trades`
// table. `deposit`/`withdrawal` are deliberately NOT here: they have no equity
// leg and live in the cash ledger — see `CashTransactionKind` below.
//
// NOTE for anyone widening this again: TypeScript will NOT flag the const
// arrays that enumerate it (a subset of a widened union still type-checks), so
// `CreateTradeModal`/`EditTradeModal`'s `TRADE_TYPES` and the `TradeTypeBadge`
// colour map need a manual pass every time.
export type TradeType = 'buy' | 'sell' | 'short' | 'cover' | 'dividend' | 'split';

/** The four fills — a real share transaction at a broker. */
export const FILL_TRADE_TYPES = ['buy', 'sell', 'short', 'cover'] as const;
export type FillTradeType = (typeof FILL_TRADE_TYPES)[number];

/** Account-scoped cash with no equity leg — the `cash_transactions` table. */
export type CashTransactionKind = 'deposit' | 'withdrawal';

export interface TradeEquity {
  id: number;
  symbol: string;
  name: string;
  exchange: string | null;
  sector: string | null;
}

export interface Trade {
  id: number;
  user_id: string;
  equity_id: number;
  trade_type: TradeType;
  quantity: number | string;
  price: number | string;
  fees: number | string;
  executed_at: string;
  notes: string | null;
  watchlist_item_id: number | null;
  account_id: number | null;
  account: AccountRef | null;
  equity: TradeEquity;
  total_value: number | string;
  total_cost: number | string;
  /** True when this trade zeroed out the position (set on create only) */
  position_closed: boolean;
  created_at: string;
  updated_at: string;
}

export interface TradeCreate {
  equity_id?: number;
  symbol?: string;
  trade_type: TradeType;
  quantity: number;
  price: number;
  fees?: number;
  executed_at: string;
  notes?: string;
  watchlist_item_id?: number;
  account_id?: number | null;
}

export interface TradeUpdate {
  trade_type?: TradeType;
  quantity?: number;
  price?: number;
  fees?: number;
  executed_at?: string;
  notes?: string;
  watchlist_item_id?: number;
  account_id?: number | null;
}

export interface TradePair {
  id: number;
  equity_id: number;
  open_trade_id: number;
  close_trade_id: number;
  quantity_matched: number | string;
  realized_pnl: number | string;
  holding_period_days: number;
  calculated_at: string;
  equity: TradeEquity;
}

// Learning loop (lessons) types
export type ThesisOutcome = 'played_out' | 'partial' | 'wrong' | 'unclear';

export interface Lesson {
  id: number;
  trade_id: number | null;
  equity_id: number;
  symbol: string;
  thesis_outcome: ThesisOutcome;
  lesson: string;
  tags: string[];
  created_at: string;
  updated_at: string;
}

export interface LessonCreate {
  trade_id?: number;
  equity_id?: number;
  symbol?: string;
  thesis_outcome: ThesisOutcome;
  lesson: string;
  tags?: string[];
}

export interface LessonUpdate {
  thesis_outcome?: ThesisOutcome;
  lesson?: string;
  tags?: string[];
  trade_id?: number | null;
}

export interface PositionSummary {
  equity_id: number;
  equity: TradeEquity;
  account_id: number | null;
  account: AccountRef | null;
  quantity: number | string;
  avg_cost_basis: number | string;
  total_cost: number | string;
  current_price: number | string | null;
  current_value: number | string | null;
  unrealized_pnl: number | string | null;
  unrealized_pnl_percent: number | string | null;
  realized_pnl: number | string;
  first_trade_at: string;
  last_trade_at: string;
}

export interface PortfolioSummary {
  total_invested: number | string;
  current_value: number | string | null;
  total_unrealized_pnl: number | string | null;
  total_realized_pnl: number | string;
  positions: PositionSummary[];
  position_count: number;
  total_trades: number;
}

export interface PerformanceMetrics {
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
  win_rate: number | string;
  total_realized_pnl: number | string;
  average_win: number | string | null;
  average_loss: number | string | null;
  largest_win: number | string | null;
  largest_loss: number | string | null;
  profit_factor: number | string | null;
  average_holding_days: number | string | null;
  current_streak: number;
  longest_winning_streak: number;
  longest_losing_streak: number;
}

export interface PerformanceByCategory {
  category: string;
  total_trades: number;
  realized_pnl: number | string;
  win_rate: number | string;
}

export interface PerformanceReport {
  metrics: PerformanceMetrics;
  by_sector: PerformanceByCategory[];
  by_equity: PerformanceByCategory[];
  period_start: string | null;
  period_end: string | null;
}

export interface PositionSizeRequest {
  account_size: number;
  risk_percent: number;
  entry_price: number;
  stop_loss: number;
  method?: string;
}

export interface PositionSizeResponse {
  shares: number;
  position_value: number | string;
  risk_amount: number | string;
  risk_per_share: number | string;
  method: string;
  notes: string | null;
}

export interface PaginatedMeta extends ResponseMeta {
  total: number;
  limit: number;
  offset: number;
}

// Event types
export type EventType =
  | 'earnings'
  | 'ex_dividend'
  | 'dividend_pay'
  | 'stock_split'
  | 'fomc'
  | 'cpi'
  | 'ppi'
  | 'nfp'
  | 'gdp'
  | 'pce'
  | 'retail_sales'
  | 'unemployment'
  | 'ism_manufacturing'
  | 'ism_services'
  | 'housing_starts'
  | 'consumer_confidence'
  | 'custom'
  | 'ipo';

export type EventImportance = 'low' | 'medium' | 'high';
export type EventSource = 'yahoo' | 'manual' | 'seed' | 'alpha_vantage';

export interface EventEquity {
  id: number;
  symbol: string;
  name: string;
}

export interface EconomicEvent {
  id: string;
  event_type: EventType;
  equity_id: number | null;
  user_id: string | null;
  event_date: string;
  event_time: string | null;
  all_day: boolean;
  title: string;
  description: string | null;
  actual_value: number | string | null;
  forecast_value: number | string | null;
  previous_value: number | string | null;
  importance: EventImportance;
  source: EventSource;
  is_confirmed: boolean;
  recurrence_key: string | null;
  created_at: string;
  updated_at: string;
  equity: EventEquity | null;
}

export interface EconomicEventCreate {
  event_type: EventType;
  event_date: string;
  event_time?: string;
  all_day?: boolean;
  title: string;
  description?: string;
  equity_symbol?: string;
  actual_value?: number;
  forecast_value?: number;
  previous_value?: number;
  importance?: EventImportance;
  is_confirmed?: boolean;
}

export interface EconomicEventUpdate {
  event_date?: string;
  event_time?: string;
  all_day?: boolean;
  title?: string;
  description?: string;
  actual_value?: number;
  forecast_value?: number;
  previous_value?: number;
  importance?: EventImportance;
  is_confirmed?: boolean;
}

export interface CalendarDay {
  date: string;
  events: EconomicEvent[];
  has_earnings: boolean;
  has_macro: boolean;
  event_count: number;
}

export interface CalendarMonth {
  year: number;
  month: number;
  days: CalendarDay[];
  total_events: number;
}

export interface UpcomingEventsResponse {
  events: EconomicEvent[];
  total: number;
  days_ahead: number;
}

export interface EventStats {
  total_events: number;
  earnings_this_week: number;
  macro_events_this_week: number;
  next_fomc_date: string | null;
  watchlist_earnings_upcoming: number;
}

// News types
export interface NewsItem {
  id: string;
  title: string;
  summary: string | null;
  url: string;
  source: string;
  image_url: string | null;
  published_at: string;
  sentiment: 'positive' | 'negative' | 'neutral' | null;
  symbols: string[];
}

export interface NewsResponse {
  symbol: string | null;
  items: NewsItem[];
  cached_at: string | null;
}

export interface EventFilters {
  start_date?: string;
  end_date?: string;
  event_types?: EventType[];
  equity_symbol?: string;
  watchlist_id?: number;
  watchlist_only?: boolean;
  importance?: EventImportance;
  include_past?: boolean;
}

// ==================== Advisor context pack outbox ====================

export interface OutboxStatus {
  configured: boolean;
  dir: string | null;
  last_published_at: string | null;
  last_file: string | null;
}

export interface OutboxPublishResult {
  latest_path: string;
  history_path: string;
  generated_at: string;
}
