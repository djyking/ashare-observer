import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import StockChart from '../components/StockChart.vue'
import StockLibrary from '../components/StockLibrary.vue'
import PaperExperiments from '../components/PaperExperiments.vue'
import { snapshot, response } from './fixtures'
afterEach(()=>vi.unstubAllGlobals())
describe('research inputs and indicator consistency',()=>{
  it('uses server EMA series and exposes 50/120/all without recomputing the EMA seed',async()=>{
    const candles=Array.from({length:130},(_,i)=>({date:`2026-${String(Math.floor(i/28)+1).padStart(2,'0')}-${String(i%28+1).padStart(2,'0')}`,open:10,high:11,low:9,close:10,volume:100,amount:1000}))
    const series=candles.map(c=>({date:c.date,ema20:100,ema60:80,macd:1,macd_signal:.5,macd_hist:.5,rsi14:60}))
    const wrapper=mount(StockChart,{props:{candles,series}})
    const bodies=()=>wrapper.findAll('svg>g').filter(g=>g.attributes('fill'))
    expect(bodies()).toHaveLength(50);expect(Number(wrapper.get('path[stroke="#c1a168"]').attributes('d')?.match(/^M[\d.]+,([\d.]+)/)?.[1])).toBeLessThan(100)
    await wrapper.get('select').setValue('120');expect(bodies()).toHaveLength(120)
    await wrapper.get('select').setValue('all');expect(bodies()).toHaveLength(130)
    await wrapper.setProps({series:undefined});expect(wrapper.text()).toContain('仅显示价格与成交量')
  })
  it('never allows importing a changed document under a previously valid result',async()=>{
    vi.stubGlobal('fetch',vi.fn(async()=>response({valid:true,code:'600036',row_count:65,first_date:'2026-01-05',last_date:'2026-04-10',fields:['date'],errors:[],warnings:[]})))
    const wrapper=mount(StockLibrary,{props:{csrf:'token',busy:false}})
    await wrapper.get('input[maxlength="6"]').setValue('600036');await wrapper.get('textarea').setValue('date,open,high,low,close,volume\n2026-01-05,10,11,9,10,100')
    await wrapper.get('form').trigger('submit');await flushPromises();expect(wrapper.get('button.primary').attributes('disabled')).toBeUndefined()
    await wrapper.get('textarea').setValue('changed');expect(wrapper.get('button.primary').attributes('disabled')).toBeDefined();wrapper.unmount()
  })
  it('requires explicit acknowledgement to archive the existing experiment',async()=>{
    const mutate=vi.fn().mockResolvedValue(true);const wrapper=mount(PaperExperiments,{props:{snapshot:snapshot(),active:false,enabled:true,mutate}})
    await wrapper.get('input[maxlength="60"]').setValue('新的实验');await wrapper.get('form').trigger('submit');expect(mutate).not.toHaveBeenCalled()
    await wrapper.get('input[type="checkbox"]').setValue(true);await wrapper.get('form').trigger('submit');expect(mutate).toHaveBeenCalledWith('/api/demo/experiments',expect.objectContaining({name:'新的实验',initial_cash:100000}),expect.any(String))
  })
})
