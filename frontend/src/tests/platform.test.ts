import { afterEach, describe, expect, it, vi } from 'vitest'
import { usePlatform } from '../composables/usePlatform'
import { deferred, response, snapshot } from './fixtures'

afterEach(() => { vi.unstubAllGlobals() })
describe('snapshot coordination and mutation boundary', () => {
  it('prevents actions before first successful snapshot', async () => {
    const fetch = vi.fn(); vi.stubGlobal('fetch', fetch)
    const state = usePlatform()
    expect(state.ready.value).toBe(false)
    expect(await state.mutate('/api/settings', {}, 'saved')).toBe(false)
    expect(fetch).not.toHaveBeenCalled()
  })
  it('discards late snapshots instead of overwriting newer market state', async () => {
    const older = deferred<Response>(), newer = deferred<Response>()
    vi.stubGlobal('fetch', vi.fn().mockReturnValueOnce(older.promise).mockReturnValueOnce(newer.promise))
    const state = usePlatform()
    const a = state.load(), b = state.load(true)
    newer.resolve(response(snapshot({ app: { ...snapshot().app, revision: 2 } }))); await b
    older.resolve(response(snapshot())); await a
    expect(state.snapshot.value?.app.revision).toBe(2)
    expect(state.loading.value).toBe(false)
  })
  it('keeps last valid data when polling loses the network', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(response(snapshot())).mockRejectedValueOnce(new TypeError('offline')))
    const state = usePlatform(); await state.load(); await state.load()
    expect(state.snapshot.value?.stocks[0].code).toBe('600036')
    expect(state.connectionError.value).toContain('保留')
  })
  it('shares concurrent polls and rejects duplicate actions while one is in flight', async () => {
    const initial = deferred<Response>(), mutation = deferred<Response>()
    const fetch = vi.fn().mockReturnValueOnce(initial.promise).mockReturnValueOnce(mutation.promise).mockResolvedValueOnce(response(snapshot()))
    vi.stubGlobal('fetch', fetch)
    const state = usePlatform(); const first = state.load(); const second = state.load()
    expect(fetch).toHaveBeenCalledTimes(1); initial.resolve(response(snapshot())); await Promise.all([first, second])
    const order = state.mutate('/api/brokers/paper/orders', { quantity: 100 }, '记录完成')
    expect(await state.mutate('/api/brokers/paper/orders', { quantity: 100 }, '重复')).toBe(false)
    expect(fetch).toHaveBeenCalledTimes(2)
    mutation.resolve(response({ ok: true })); expect(await order).toBe(true)
    expect(fetch.mock.calls[1][1].headers['X-CSRF-Token']).toBe('test-token')
    expect(state.busy.value).toBe(false)
  })
  it('blocks paper controls in real research mode and during scan', async () => {
    const data = snapshot(); data.app.mode = 'eastmoney'
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response(data)))
    const state = usePlatform(); await state.load()
    expect(state.demoReady.value).toBe(false)
    state.snapshot.value = snapshot({ app: { ...snapshot().app, refreshing: true } })
    expect(await state.mutate('/api/refresh', {}, 'scan')).toBe(false)
  })
  it('invalidates pending snapshots and blocks further requests after disposal', async () => {
    const delayed = deferred<Response>()
    const fetch = vi.fn().mockResolvedValueOnce(response(snapshot())).mockReturnValueOnce(delayed.promise)
    vi.stubGlobal('fetch', fetch)
    const state = usePlatform(); await state.load()
    const pending = state.load(); state.dispose()
    delayed.resolve(response(snapshot({ app: { ...snapshot().app, revision: 2 } }))); await pending
    expect(state.snapshot.value?.app.revision).toBe(1)
    expect(state.loading.value).toBe(false)
    await state.load()
    expect(await state.mutate('/api/settings', {}, 'saved')).toBe(false)
    expect(fetch).toHaveBeenCalledTimes(2)
  })
  it('does not publish a mutation result or reload after disposal', async () => {
    const delayed = deferred<Response>()
    const fetch = vi.fn().mockResolvedValueOnce(response(snapshot())).mockReturnValueOnce(delayed.promise)
    vi.stubGlobal('fetch', fetch)
    const state = usePlatform(); await state.load()
    const pending = state.mutate('/api/refresh', {}, 'updated'); state.dispose()
    delayed.resolve(response({ ok: true })); expect(await pending).toBe(false)
    expect(state.feedback.value).toBe('')
    expect(fetch).toHaveBeenCalledTimes(2)
  })
})
