import type { Numeric } from './types'
export const numeric = (value: unknown): number | null => value === null || value === undefined || value === '' || !Number.isFinite(Number(value)) ? null : Number(value)
export const fmt = (value: unknown, digits = 2) => numeric(value) === null ? '—' : Number(value).toLocaleString('zh-CN', { minimumFractionDigits: digits, maximumFractionDigits: digits })
export const signed = (value: unknown, digits = 2) => numeric(value) === null ? '—' : `${Number(value) > 0 ? '+' : ''}${fmt(value, digits)}`
export const pct = (value: unknown) => numeric(value) === null ? '—' : `${signed(value)}%`
export const money = (value: Numeric | undefined) => numeric(value) === null ? '—' : `¥ ${fmt(value)}`
export const color = (value: unknown) => (numeric(value) ?? 0) > 0 ? 'up' : (numeric(value) ?? 0) < 0 ? 'down' : ''
export const timeText = (value: string | null | undefined) => {
  if (!value) return '—'
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return value
  const date = new Date(value)
  return Number.isFinite(date.getTime()) ? new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }).format(date) : value
}
export const statusNames = { watch: '值得观察', wait: '等待条件', insufficient: '数据不足', unavailable: '数据不可用' }
export const modeNames = { demo: '离线演示', eastmoney: '真实日线', csv: '本地 CSV' }
export const routeNames: Record<string, string> = { trend: '趋势观察', trend_pullback: '趋势回调', pullback: '回调观察', breakout: '突破观察', momentum: '动量观察', wait: '等待条件', insufficient: '数据不足', unavailable: '数据不可用' }
export const orderStatuses: Record<string, string> = { pending: '待成交', filled: '已成交', cancelled: '已取消', canceled: '已取消', rejected: '已拒绝', expired: '已失效', partially_filled: '部分成交' }
export const exchangeName = (exchange: string) => ({ SH: '沪市', SZ: '深市', BJ: '北交所', SSE: '沪市', SZSE: '深市', BSE: '北交所', sh: '沪市', sz: '深市', bj: '北交所' })[exchange] || exchange || 'A 股'
