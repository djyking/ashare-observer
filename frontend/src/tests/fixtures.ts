import type { Snapshot } from '../types'
export function snapshot(overrides: Partial<Snapshot> = {}): Snapshot {
  return {
    app: { name: 'A 股量化交易研究平台', version: '1.1.0', mode: 'demo', as_of: '2026-10-12', source: '合成演示', fetched_at: '2026-10-13T01:00:00Z', refreshing: false, last_error: null, revision: 1 },
    session: { label: '盘后', is_open: false, calendar_known: true },
    stats: { stock_count: 1, valid_count: 1, watch_count: 1, wait_count: 0 },
    stocks: [{ code: '600036', name: '招商银行', exchange: 'SH', board: 'main', status: 'ok', candles: [{ date: '2026-10-12', open: 30, high: 31, low: 29, close: 30.5, volume: 1000, amount: 30000 }], raw_candles: [], adjustment: 'none' }],
    analyses: [{ code: '600036', score: 70, status: 'watch', reasons: ['趋势示例'] }],
    portfolio: { initial_cash: 100000, cash: 100000, equity: 100000, realized_pnl: 0, unrealized_pnl: 0, fees: 0, positions: [], orders: [], trades: [] },
    settings: { mode: 'demo', watchlist: ['600036'], refresh_seconds: 300, auto_refresh: true }, csrf_token: 'test-token',
    ...overrides,
  }
}
export function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (error: Error) => void
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej })
  return { promise, resolve, reject }
}
export const response = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } })
