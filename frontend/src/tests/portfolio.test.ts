import { describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import Portfolio from '../components/Portfolio.vue'
import { deferred, snapshot } from './fixtures'

describe('paper order UI', () => {
  it('uses broker gateway, suppresses double clicks, and reuses intent id after ambiguous failure', async () => {
    const pending = deferred<boolean>()
    const mutate = vi.fn().mockReturnValueOnce(pending.promise).mockResolvedValueOnce(true)
    const wrapper = mount(Portfolio, { props: { snapshot: snapshot(), enabled: true, mutate } })
    await wrapper.get('form').trigger('submit'); await wrapper.get('form').trigger('submit')
    expect(mutate).toHaveBeenCalledTimes(1)
    const firstId = mutate.mock.calls[0][1].request_id
    expect(mutate.mock.calls[0][0]).toBe('/api/brokers/paper/orders')
    pending.resolve(false); await flushPromises(); await wrapper.get('form').trigger('submit')
    expect(mutate).toHaveBeenCalledTimes(2)
    expect(mutate.mock.calls[1][1].request_id).toBe(firstId)
  })
  it('does not submit in real-data mode and limits order pages to 30 rows', async () => {
    const data = snapshot(); data.app.mode = 'eastmoney'
    data.portfolio.orders = Array.from({ length: 31 }, (_, i) => ({ id: String(i), code: '600036', side: 'buy', quantity: 100, status: 'cancelled', created_date: '2026-10-12' }))
    const mutate = vi.fn()
    const wrapper = mount(Portfolio, { props: { snapshot: data, enabled: false, mutate } })
    expect(wrapper.get('fieldset').attributes('disabled')).toBeDefined()
    await wrapper.get('form').trigger('submit'); expect(mutate).not.toHaveBeenCalled()
    expect(wrapper.findAll('table')[1].findAll('tbody tr')).toHaveLength(30)
    const pager = wrapper.get('[aria-label="模拟委托分页"]')
    await pager.findAll('button')[1].trigger('click')
    expect(wrapper.findAll('table')[1].findAll('tbody tr')).toHaveLength(1)
  })
})
