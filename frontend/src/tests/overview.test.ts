import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import Overview from '../components/Overview.vue'
import { snapshot } from './fixtures'

describe('research accounting presentation', () => {
  it('does not invent losses when valuation is missing', () => {
    const data = snapshot(); data.portfolio.equity = null
    const wrapper = mount(Overview, { props: { snapshot: data } })
    expect(wrapper.text()).toContain('累计模拟收益 — 元')
    expect(wrapper.text()).not.toContain('-100,000')
  })
  it('treats a real zero balance as a number rather than missing data', () => {
    const data = snapshot(); data.portfolio.equity = 0
    const wrapper = mount(Overview, { props: { snapshot: data } })
    expect(wrapper.text()).toContain('累计模拟收益 -100,000.00 元')
  })
})
