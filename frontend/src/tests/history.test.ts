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
  it('loads connection state lazily without automatically connecting or ordering', async () => {
    const capabilities = { account: false, positions: false, orders: false, trades: false, place_order: false, cancel_order: false }
    const fetch = vi.fn(async (path: string) => response(path === '/api/brokers' ? {live_enabled: false, providers: [{id: 'live', name: '券商实盘', environment: 'live', connected: false, capabilities, message: '尚未配置'}]} : {drivers: [], profile: {driver: 'unconfigured', fields: {}, masked_fields: {}, saved_fields: [], secret_fields_ready: []}, state: {status: 'disconnected', provider_id: null, message: '尚未安装具体适配器', last_checked_at: null}, read_only: true, secrets_persisted: false}))
    vi.stubGlobal('fetch', fetch)
    const wrapper = mount(BrokerAccess, {props: {active: false, csrf: 'token'}})
    expect(fetch).not.toHaveBeenCalled()
    await wrapper.setProps({active: true}); await flushPromises()
    expect(wrapper.get('#broker-connection-status').text()).toBe('未连接')
    expect(wrapper.text()).toContain('真实买卖尚未启用')
    expect(fetch.mock.calls.map(([path]) => path)).toEqual(['/api/broker/connection', '/api/brokers'])
    expect(wrapper.find('[aria-label="账户查询结果"]').exists()).toBe(false)
    wrapper.unmount()
  })
})
