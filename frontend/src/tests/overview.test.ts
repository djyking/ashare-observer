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

  it('selects the highest score initially and removes detail when it is excluded by the filter', async () => {
    const data=snapshot();data.stocks.push({...data.stocks[0],code:'000333',name:'美的集团'});data.analyses[0].status='wait';data.analyses[0].score=30;data.analyses.push({code:'000333',score:80,status:'watch',reasons:['更高评分']})
    const wrapper=mount(Overview,{props:{snapshot:data}})
    expect(wrapper.get('.detail-heading h2').text()).toBe('美的集团')
    await wrapper.findAll('.watch-row')[1].trigger('click');expect(wrapper.get('.detail-heading h2').text()).toBe('招商银行')
    await wrapper.findAll('.filter')[1].trigger('click');expect(wrapper.get('.detail-heading h2').text()).toBe('美的集团')
    await wrapper.setProps({snapshot:{...data,analyses:data.analyses.map(a=>({...a,status:'wait' as const}))}});expect(wrapper.text()).toContain('当前筛选下没有股票');expect(wrapper.get('.detail-heading h2').text()).toBe('暂无观察股票')
  })

  it('pages long stock signal histories rather than rendering every event', async()=>{
    const data=snapshot();data.analyses[0].strategy_history=Array.from({length:31},(_,i)=>({date:`2026-10-${String(i+1).padStart(2,'0')}`,strategy_id:'teaching',name:'教学综合评分',score:70,close:30}))
    const wrapper=mount(Overview,{props:{snapshot:data}})
    expect(wrapper.get('.signal-history tbody').findAll('tr')).toHaveLength(10);expect(wrapper.text()).toContain('共 31 条 · 每页 10 条')
    const next=wrapper.get('[aria-label="股票历史信号分页"]').findAll('button')[1];await next.trigger('click');await next.trigger('click');await next.trigger('click')
    expect(wrapper.get('.signal-history tbody').findAll('tr')).toHaveLength(1)
  })
