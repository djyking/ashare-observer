export type Mode = 'demo' | 'eastmoney' | 'csv'
export type Numeric = number | string | null
export interface Candle { date: string; open: number; high: number; low: number; close: number; volume: number; amount: number }
export interface Stock {
  code: string; name: string; exchange: string; board: string; sector?: string;
  status: string; error?: string | null; data_date?: string; candles: Candle[];
  raw_candles?: Candle[]; adjustment: string; metadata_verified?: boolean;
}
export type AnalysisStatus = 'watch' | 'wait' | 'insufficient' | 'unavailable'
export interface Analysis {
  code: string; name?: string; score: number | null; status: AnalysisStatus; route?: string;
  reasons: string[]; indicators?: Record<string, number | null | Record<string, number>>;
  chart_series?: Record<string, (number | null)[]> | ChartPoint[];
  score_components?: {key:string;label:string;score:number;max_score:number;rule:string}[];
  strategy_results?: {id:string;name:string;enabled:boolean;matched:boolean;score:number;reasons:string[];checks:{label:string;passed:boolean}[]}[];
  strategy_version?: string;
  strategy_history?: {date:string;strategy_id:string;name:string;score:number;close:number}[];
  history?: {date: string; code: string; score: number; status: string; close: number; description: string; route?: string}[];
  plan?: { reference_price: number; stop_price: number; target_price: number; expected_gain_pct: number; risk_pct: number; note?: string } | null;
}
export interface Position { code: string; name?: string; quantity: Numeric; sellable: Numeric; avg_cost: Numeric; last_price: Numeric; market_value: Numeric; unrealized_pnl: Numeric }
export interface PaperOrder { id: string; side: string; code: string; quantity: Numeric; status: string; created_date: string; reason?: string }
export interface PaperTrade { id?: string; date: string; side: string; code: string; quantity: Numeric; price: Numeric; fee: Numeric; pnl: Numeric }
export interface Portfolio {
  initial_cash: Numeric; cash: Numeric; available_cash?: Numeric; frozen_cash?: Numeric;
  equity: Numeric; realized_pnl: Numeric; unrealized_pnl: Numeric; fees: Numeric;
  positions: Position[]; orders?: PaperOrder[]; trades?: PaperTrade[];
}
export interface Settings { mode: Mode; watchlist: string[]; refresh_seconds: number; auto_refresh: boolean; initial_cash?: number; watchlist_groups?: Record<string, string[]>; strategy_config?: Record<string, unknown> }
export interface Snapshot {
  app: { name: string; version: string; mode: Mode; as_of: string; source: string; fetched_at: string | null; refreshing: boolean; last_error: string | null; notice?: string; revision?: number; demo_date?: string };
  session: { label: string; is_open: boolean; calendar_known: boolean };
  stats: { stock_count: number; valid_count: number; watch_count: number; wait_count: number };
  stocks: Stock[]; analyses: Analysis[]; portfolio: Portfolio; settings: Settings; csrf_token: string;
  paper_experiment?: {id: number | string; name: string; created_at?: string; start_date?: string};
}
export interface HistoryEntry {
  id?: number; created_at: string; as_of: string; mode: Mode; source: string;
  top_name?: string; top_code?: string; top_score?: number; watch_count: number; wait_count: number;
  summary?: string | string[] | Record<string, unknown>; valid_count: number; stock_count: number;
}
export interface HistoryPage { items: HistoryEntry[]; total: number; page: number; page_size: number; pages: number }
export type MutationBody = Record<string, unknown>
export type Mutate = (path: string, body: MutationBody, message: string) => Promise<boolean>
export interface ChartPoint {date?: string; ema20: number | null; ema60?: number | null; macd?: number | null; macd_signal?: number | null; macd_hist?: number | null; rsi14?: number | null }
export interface Page<T> {items: T[]; total: number; page: number; pages: number; page_size: number}
export interface OrderPreview {allowed: boolean; message: string; error_code?: string; board: string; min_quantity: number; step: number; reference_price: Numeric; estimated_notional: Numeric; fees: Numeric | Record<string, Numeric>; reserved_cash: Numeric; available_cash: Numeric; sellable_now: Numeric; sellable_on_execution: Numeric; execute_after: string}
export interface StockSearch {code: string; name: string; board: string; exchange: string; demo_tradable?: boolean; source?: string; metadata_verified?: boolean}
export interface ImportResult {valid: boolean; code: string; fields: string[]; row_count: number; first_date: string; last_date: string; errors: {line?: number; field?: string; message: string}[]; warnings: string[]; adjustment?: string; saved?: boolean}
