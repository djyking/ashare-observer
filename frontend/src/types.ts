export type Mode = 'demo' | 'eastmoney' | 'csv'
export type Numeric = number | string | null
export interface Candle { date: string; open: number; high: number; low: number; close: number; volume: number; amount: number }
export interface Stock {
  code: string; name: string; exchange: string; board: string; sector?: string;
  status: string; error?: string | null; data_date?: string; candles: Candle[];
  raw_candles: Candle[]; adjustment: string; metadata_verified?: boolean;
}
export type AnalysisStatus = 'watch' | 'wait' | 'insufficient' | 'unavailable'
export interface Analysis {
  code: string; name?: string; score: number | null; status: AnalysisStatus; route?: string;
  reasons: string[]; indicators?: Record<string, number | null>;
  plan?: { reference_price: number; stop_price: number; target_price: number; expected_gain_pct: number; risk_pct: number; note?: string } | null;
}
export interface Position { code: string; name?: string; quantity: Numeric; sellable: Numeric; avg_cost: Numeric; last_price: Numeric; market_value: Numeric; unrealized_pnl: Numeric }
export interface PaperOrder { id: string; side: string; code: string; quantity: Numeric; status: string; created_date: string; reason?: string }
export interface PaperTrade { id?: string; date: string; side: string; code: string; quantity: Numeric; price: Numeric; fee: Numeric; pnl: Numeric }
export interface Portfolio {
  initial_cash: Numeric; cash: Numeric; available_cash?: Numeric; frozen_cash?: Numeric;
  equity: Numeric; realized_pnl: Numeric; unrealized_pnl: Numeric; fees: Numeric;
  positions: Position[]; orders: PaperOrder[]; trades: PaperTrade[];
}
export interface Settings { mode: Mode; watchlist: string[]; refresh_seconds: number; auto_refresh: boolean; initial_cash?: number }
export interface Snapshot {
  app: { name: string; version: string; mode: Mode; as_of: string; source: string; fetched_at: string | null; refreshing: boolean; last_error: string | null; notice?: string; revision?: number; demo_date?: string };
  session: { label: string; is_open: boolean; calendar_known: boolean };
  stats: { stock_count: number; valid_count: number; watch_count: number; wait_count: number };
  stocks: Stock[]; analyses: Analysis[]; portfolio: Portfolio; settings: Settings; csrf_token: string;
}
export interface HistoryEntry {
  id?: number; created_at: string; as_of: string; mode: Mode; source: string;
  top_name?: string; top_code?: string; top_score?: number; watch_count: number; wait_count: number;
  summary?: string | string[] | Record<string, unknown>; valid_count: number; stock_count: number;
}
export interface HistoryPage { items: HistoryEntry[]; total: number; page: number; page_size: number; pages: number }
export type MutationBody = Record<string, unknown>
export type Mutate = (path: string, body: MutationBody, message: string) => Promise<boolean>
