import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import History from '../components/History.vue'
import BrokerAccess from '../components/BrokerAccess.vue'
import { deferred, response } from './fixtures'

afterEach(() => vi.unstubAllGlobals())
describe('read-only resource views', () => {
  it('loads history lazily, retains data while refreshing and rejects older results', async () => {
    const older = deferred<Response>(), newer = deferred<Response>()
    const fetch = vi.fn().mockReturnValueOnce(older.promise).mockReturnValueOnce(newer.promise)
    vi.stubGlobal('fetch', fetch)
    const wrapper = mount(History, { props: { active: false, revision: 1 } })
    expect(fetch).not.toHaveBeenCalled()
    await wrapper.setProps({ active: true }); await wrapper.setProps({ revision: 2 })
    newer.resolve(response({ items: [], total: 99, page: 1, pages: 4, page_size: 30 })); await flushPromises()
    older.resolve(response({ items: [], total: 3, page: 1, pages: 1, page_size: 30 })); await flushPromises()
    expect(wrapper.text()).toContain('共 99 条')
    expect(fetch.mock.calls[0][0]).toBe('/api/history?page=1&page_size=30')
  })
  it('shows unconnected live adapter, exposes no credential input or live order action', async () => {
    const capabilities = { account: false, positions: false, orders: false, trades: false, place_order: false, cancel_order: false }
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({ live_enabled: false, providers: [{ id: 'live', name: '券商实盘', environment: 'live', connected: false, capabilities, message: '尚未配置' }] })))
    const wrapper = mount(BrokerAccess, { props: { active: true } }); await flushPromises()
    expect(wrapper.text()).toContain('券商实盘未连接')
    expect(wrapper.findAll('input')).toHaveLength(0)
    expect(wrapper.findAll('button')).toHaveLength(1)
  })
})
