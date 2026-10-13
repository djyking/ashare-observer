import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import Portfolio from '../components/Portfolio.vue'
import { deferred, snapshot, response } from './fixtures'
const preview = {allowed:true,message:'预检查通过',board:'main',min_quantity:100,step:100,reference_price:30,estimated_notional:3000,fees:5,reserved_cash:3305,available_cash:100000,sellable_now:0,sellable_on_execution:100,execute_after:'2026-10-13'}
function setupFetch(previewValue=preview){return vi.stubGlobal('fetch',vi.fn(async (path:string)=>{if(path.includes('preview'))return response(previewValue);if(path.includes('kind=orders')){const page=path.includes('page=2')?2:1;return response({items:Array.from({length:page===1?30:1},(_,i)=>({id:`${page}-${i}`,code:'600036',side:'buy',quantity:100,status:'cancelled',created_date:'2026-10-12'})),total:31,page,pages:2,page_size:30})}return response({items:[],total:0,page:1,pages:1,page_size:30})}))}
afterEach(()=>{vi.unstubAllGlobals();vi.useRealTimers()})
describe('paper order UI',()=>{
  it('checks estimates before submitting, suppresses double clicks, and keeps retry id after ambiguous failure',async()=>{
    vi.useFakeTimers();setupFetch();const pending=deferred<boolean>();const mutate=vi.fn().mockReturnValueOnce(pending.promise).mockResolvedValueOnce(true)
    const wrapper=mount(Portfolio,{props:{snapshot:snapshot(),active:true,enabled:true,mutate}})
    await wrapper.get('#order-form').trigger('submit');expect(mutate).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(300);await flushPromises()
    expect(wrapper.text()).toContain('3,000.00');expect(wrapper.text()).toContain('2026-10-13')
    await wrapper.get('#order-form').trigger('submit');await wrapper.get('#order-form').trigger('submit');expect(mutate).toHaveBeenCalledTimes(1)
    const firstId=mutate.mock.calls[0][1].request_id;expect(mutate.mock.calls[0][0]).toBe('/api/brokers/paper/orders')
    pending.resolve(false);await flushPromises();await wrapper.get('#order-form').trigger('submit');expect(mutate).toHaveBeenCalledTimes(2);expect(mutate.mock.calls[1][1].request_id).toBe(firstId);wrapper.unmount()
  })
  it('loads only a server page and does not submit in real-data mode',async()=>{
    setupFetch();const data=snapshot();data.app.mode='eastmoney';const mutate=vi.fn();const wrapper=mount(Portfolio,{props:{snapshot:data,enabled:false,active:true,mutate}})
    await flushPromises();expect(wrapper.get('#order-form fieldset').attributes('disabled')).toBeDefined();await wrapper.get('#order-form').trigger('submit');expect(mutate).not.toHaveBeenCalled();expect(wrapper.findAll('table')[1].findAll('tbody tr')).toHaveLength(30)
    await wrapper.get('[aria-label="模拟委托分页"]').findAll('button')[1].trigger('click');await flushPromises();expect(wrapper.findAll('table')[1].findAll('tbody tr')).toHaveLength(1);expect(fetch).toHaveBeenCalledWith('/api/paper/records?kind=orders&page=2',expect.anything());wrapper.unmount()
  })
  it('explains the rule failure and blocks submission when preview rejects',async()=>{
    vi.useFakeTimers();setupFetch({...preview,allowed:false,message:'模拟资金不足：需冻结 3305 元'})
    const mutate=vi.fn();const wrapper=mount(Portfolio,{props:{snapshot:snapshot(),enabled:true,active:true,mutate}});await vi.advanceTimersByTimeAsync(300);await flushPromises()
    expect(wrapper.text()).toContain('模拟资金不足：需冻结 3305 元');expect(wrapper.get('#submit-order').attributes('disabled')).toBeDefined();await wrapper.get('#order-form').trigger('submit');expect(mutate).not.toHaveBeenCalled();wrapper.unmount()
  })
  it('invalidates a preview as soon as its quantity changes',async()=>{
    vi.useFakeTimers();setupFetch();const wrapper=mount(Portfolio,{props:{snapshot:snapshot(),enabled:true,active:true,mutate:vi.fn()}});await vi.advanceTimersByTimeAsync(300);await flushPromises();expect(wrapper.get('#submit-order').attributes('disabled')).toBeUndefined();await wrapper.get('#order-quantity').setValue(1000);expect(wrapper.get('#submit-order').attributes('disabled')).toBeDefined();wrapper.unmount()
  })
})
