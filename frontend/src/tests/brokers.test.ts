import {afterEach, describe, expect, it, vi} from 'vitest'
import {flushPromises, mount} from '@vue/test-utils'
import BrokerAccess from '../components/BrokerAccess.vue'
import {deferred, response} from './fixtures'
import type {BrokerCatalog, BrokerConnection} from '../broker-types'

function configuration(): BrokerConnection {
  const fields = [{key: 'account_id', label: '账户', required: true, secret: false, masked: true, max_length: 128}, {key: 'password', label: '密码', required: true, secret: true, max_length: 4096}]
  return {drivers: [
    {id: 'demo', name: '离线券商示例', description: '使用公开虚构账号 demo / demo123', available: true, environment: 'paper', fields},
    {id: 'unconfigured', name: '真实券商预留', description: '需要安装券商适配器', available: false, environment: 'live', fields: [{key: 'broker_name', label: '券商名称', required: false, secret: false}, ...fields]},
  ], profile: {driver: 'demo', fields: {}, masked_fields: {}, saved_fields: [], secret_fields_ready: [], memory_only_fields: ['account_id', 'password']},
  state: {status: 'disconnected', provider_id: null, message: '尚未连接', last_checked_at: null}, secrets_persisted: false, read_only: true}
}
const catalog: BrokerCatalog = {providers: [{id: 'paper', name: '模拟账本', environment: 'paper', connected: true, capabilities: {account: true, positions: true, orders: true, trades: true, place_order: true, cancel_order: true}, message: '独立合成行情账本'}], live_enabled: false}
function setup() {
  let state = configuration()
  const fetch = vi.fn(async (path: string, options?: RequestInit) => {
    if (path === '/api/brokers') return response(catalog)
    if (path === '/api/broker/connection') return response(state)
    if (path.endsWith('/save')) {
      const payload = JSON.parse(String(options?.body))
      state = {...state, profile: {driver: payload.driver, fields: payload.fields.broker_name ? {broker_name: payload.fields.broker_name} : {}, masked_fields: {account_id: 'd***'}, saved_fields: ['account_id'], secret_fields_ready: ['password']}, state: {status: 'disconnected', provider_id: null, message: '配置已保存，未连接', last_checked_at: null}}
      return response(state)
    }
    if (path.endsWith('/connect')) {
      if (state.profile.driver === 'unconfigured') {state = {...state, state: {...state.state, status: 'error', message: '尚未安装具体适配器'}}; return response({error: '尚未安装具体适配器'}, 409)}
      state = {...state, state: {status: 'connected', provider_id: 'broker_demo', message: '虚构只读示例已连接', last_checked_at: '2026-10-14T06:00:00Z'}}
      return response(state)
    }
    if (path.endsWith('/disconnect')) {state = configuration(); return response(state)}
    if (path.endsWith('/account')) return response({provider: 'broker_demo', environment: 'paper', account: {equity: 123456.78, cash: 100000, available_cash: 99000, frozen_cash: 1000}})
    if (path.endsWith('/positions')) return response({positions: [{code: '600036', name: '示例股票', quantity: 100, sellable: 100, avg_cost: 10, last_price: 11, market_value: 1100, unrealized_pnl: 100}]})
    if (path.endsWith('/orders')) return response({orders: [{id: 'EXAMPLE-ORDER-1', code: '600036', side: 'buy', quantity: 100, status: 'filled', created_date: '2026-10-13', filled_price: 10}]})
    if (path.endsWith('/trades')) return response({trades: [{id: 'EXAMPLE-TRADE-1', code: '600036', side: 'buy', quantity: 100, price: 10, notional: 1000, fee: 5, date: '2026-10-13'}]})
    throw new Error(`unexpected request: ${path}`)
  })
  vi.stubGlobal('fetch', fetch)
  return {fetch, setState: (next: BrokerConnection) => {state = next}}
}
async function filled() {
  const wrapper = mount(BrokerAccess, {props: {active: true, csrf: 'token'}})
  await flushPromises(); await wrapper.get('#broker-fill-demo').trigger('click')
  return wrapper
}
afterEach(() => {vi.unstubAllGlobals(); vi.restoreAllMocks()})

describe('broker account connection workspace', () => {
  it('separates save and connect, clears passwords, and labels all demo query data', async () => {
    const {fetch} = setup(), storage = vi.spyOn(Storage.prototype, 'setItem')
    const wrapper = await filled()
    expect(wrapper.get('#broker-password').attributes('type')).toBe('password')
    expect(wrapper.get('#broker-password').attributes('maxlength')).toBe('4096')
    expect(wrapper.get('#broker-connect').attributes('disabled')).toBeDefined()
    await wrapper.get('#broker-connection-form').trigger('submit'); await flushPromises()
    expect(wrapper.get('#broker-connection-status').text()).toBe('未连接')
    expect((wrapper.get('#broker-password').element as HTMLInputElement).value).toBe('')
    expect((wrapper.get('#broker-account_id').element as HTMLInputElement).value).toBe('')
    expect(wrapper.text()).toContain('尚未验证连接')
    expect(fetch.mock.calls.some(([path]) => path.endsWith('/account'))).toBe(false)
    const saved = fetch.mock.calls.find(([path]) => path.endsWith('/save'))!
    expect(JSON.parse(String(saved[1]?.body))).toEqual({driver: 'demo', fields: {account_id: 'demo'}, secrets: {password: 'demo123'}})
    expect((saved[1]?.headers as Record<string, string>)['X-CSRF-Token']).toBe('token')
    await wrapper.get('#broker-connect').trigger('click'); await flushPromises()
    expect(wrapper.get('#broker-connection-status').text()).toBe('已连接 · 只读')
    expect(wrapper.text()).toContain('全部为虚构数据'); expect(wrapper.text()).toContain('123,456.78')
    expect(wrapper.text()).toContain('示例股票')
    await wrapper.get('[aria-label="账户记录类型"]').findAll('button')[1].trigger('click')
    expect(wrapper.text()).toContain('EXAMPLE-ORDER-1')
    await wrapper.get('[aria-label="账户记录类型"]').findAll('button')[2].trigger('click')
    expect(wrapper.text()).toContain('EXAMPLE-TRADE-1')
    expect(wrapper.get('a[href="#portfolio"]').text()).toContain('模拟账本')
    expect(storage).not.toHaveBeenCalled()
    await wrapper.get('#broker-disconnect').trigger('click'); await flushPromises()
    expect(wrapper.find('[aria-label="账户查询结果"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('会话账号与密码已清除')
    expect(wrapper.get('#broker-password').attributes('required')).toBeDefined()
    wrapper.unmount()
  })

  it('preserves a masked account by omission and lets the user replace it deliberately', async () => {
    const {fetch} = setup(), wrapper = await filled()
    await wrapper.get('#broker-connection-form').trigger('submit'); await flushPromises()
    expect(wrapper.get('#broker-account_id').attributes('placeholder')).toContain('d***')
    await wrapper.get('#broker-connection-form').trigger('submit'); await flushPromises()
    let saves = fetch.mock.calls.filter(([path]) => path.endsWith('/save'))
    expect(JSON.parse(String(saves[1][1]?.body))).toEqual({driver: 'demo', fields: {}, secrets: {}})
    await wrapper.get('#broker-account_id').setValue('replacement')
    await wrapper.get('#broker-connection-form').trigger('submit'); await flushPromises()
    saves = fetch.mock.calls.filter(([path]) => path.endsWith('/save'))
    expect(JSON.parse(String(saves[2][1]?.body)).fields).toEqual({account_id: 'replacement'})
    wrapper.unmount()
  })

  it('shows an unavailable real adapter honestly and does not render fake account data', async () => {
    setup(); const wrapper = await filled()
    await wrapper.get('#broker-driver').setValue('unconfigured')
    expect(wrapper.find('#broker-fill-demo').exists()).toBe(false)
    expect((wrapper.get('#broker-password').element as HTMLInputElement).value).toBe('')
    expect(wrapper.text()).toContain('当前未安装具体 SDK')
    await wrapper.get('#broker-broker_name').setValue('未来券商')
    await wrapper.get('#broker-account_id').setValue('sample-account')
    await wrapper.get('#broker-password').setValue('sample-secret')
    await wrapper.get('#broker-connection-form').trigger('submit'); await flushPromises()
    await wrapper.get('#broker-connect').trigger('click'); await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('尚未安装具体适配器')
    expect(wrapper.get('#broker-connection-status').text()).toBe('连接未通过')
    expect(wrapper.find('[aria-label="账户查询结果"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('sample-secret'); wrapper.unmount()
  })

  it('clears credentials immediately on submission failure and prevents duplicate sends', async () => {
    const {fetch} = setup(), wrapper = await filled(), pending = deferred<Response>()
    fetch.mockImplementationOnce(() => pending.promise)
    await wrapper.get('#broker-connection-form').trigger('submit')
    expect((wrapper.get('#broker-password').element as HTMLInputElement).value).toBe('')
    await wrapper.get('#broker-connection-form').trigger('submit')
    expect(fetch.mock.calls.filter(([path]) => path.endsWith('/save'))).toHaveLength(1)
    pending.resolve(response({error: '字段验证未通过'}, 400)); await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('字段验证未通过')
    expect((wrapper.get('#broker-password').element as HTMLInputElement).value).toBe('')
    expect(wrapper.find('[aria-label="账户查询结果"]').exists()).toBe(false); wrapper.unmount()
  })

  it('clears unsent secrets on navigation and requires re-entry after service restart', async () => {
    const {setState} = setup(), wrapper = await filled()
    await wrapper.setProps({active: false})
    expect((wrapper.get('#broker-password').element as HTMLInputElement).value).toBe('')
    expect((wrapper.get('#broker-account_id').element as HTMLInputElement).value).toBe('')
    await wrapper.setProps({active: true}); await flushPromises()
    await wrapper.get('#broker-fill-demo').trigger('click')
    await wrapper.get('#broker-connection-form').trigger('submit'); await flushPromises()
    setState(configuration())
    await wrapper.findAll('button').find(button => button.text() === '刷新接入状态')!.trigger('click'); await flushPromises()
    expect(wrapper.get('#broker-password').attributes('required')).toBeDefined()
    expect(wrapper.get('#broker-account_id').attributes('required')).toBeDefined()
    expect(wrapper.text()).toContain('断开或重启后需重填'); wrapper.unmount()
  })

  it('blocks configuration before the app provides a session token', async () => {
    const {fetch} = setup(), wrapper = mount(BrokerAccess, {props: {active: true}})
    await flushPromises(); await wrapper.get('#broker-connection-form').trigger('submit')
    expect(wrapper.get('fieldset').attributes('disabled')).toBeDefined()
    expect(fetch.mock.calls.some(([, options]) => options?.method === 'POST')).toBe(false)
    wrapper.unmount()
  })
})
