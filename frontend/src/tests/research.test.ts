import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import Research from '../components/Research.vue'
import History from '../components/History.vue'
import { snapshot, response } from './fixtures'
const catalog={version:'public-v2',strategies:[{id:'teaching',name:'教学综合评分',description:'透明规则',parameters:[{key:'min_score',label:'最低评分',default:70,min:0,max:100,step:5}],rules:['只读已收盘数据']}],defaults:{teaching:{enabled:true,min_score:70}}}
const metrics={initial_cash:100000,final_equity:101000,total_return_pct:1,max_drawdown_pct:2,trade_count:2,closed_trade_count:1,win_rate_pct:100,total_fees:15,benchmark_return_pct:2}
const report={quality:'assumption_based_research',version:'daily-replay-v1',strategy_version:'public-v2',data_fingerprint:'abc',config:{strategy_id:'teaching',start_date:'2026-08-01',end_date:'2026-10-12'},metrics,assumptions:['下一交易日开盘成交'],warnings:[],excluded:[],equity_curve:[{date:'2026-10-12',equity:101000,cash:101000,market_value:0,benchmark:102000,drawdown_pct:0}],trades:[],rejections:[],positions:[],signals:[]}
const run=(id='1')=>({id,name:`实验${id}`,kind:'research',status:'completed',created_at:'2026-10-13T01:00:00Z',archived:false,config:{mode:'demo',codes:['600036'],strategies:catalog.defaults},metrics,report})
afterEach(()=>{vi.unstubAllGlobals();vi.useRealTimers()})
describe('complete research workflow',()=>{
 it('starts an independent research job and shows a completed report without claiming unavailable win-rate',async()=>{
  vi.useFakeTimers();const saved=run();saved.report={...report,metrics:{...metrics,win_rate_pct:null as unknown as number}}
  const fetcher=vi.fn(async(path:string,init?:RequestInit)=>{if(path==='/api/strategies')return response(catalog);if(path==='/api/research'&&init?.method==='POST')return response({id:'1',status:'running'},202);if(path==='/api/research/1')return response(saved);return response({items:[],total:0,page:1,pages:1,page_size:30})});vi.stubGlobal('fetch',fetcher)
  const wrapper=mount(Research,{props:{snapshot:snapshot(),active:true}});await flushPromises();await wrapper.get('form').trigger('submit');await flushPromises()
  const call=fetcher.mock.calls.find(c=>c[0]==='/api/research');expect(call).toBeDefined();expect(JSON.parse(call![1]!.body as string)).toMatchObject({codes:['600036'],strategy_id:'teaching',mode:'demo',strategies:catalog.defaults})
  expect(wrapper.text()).toContain('期末净资产');expect(wrapper.text()).toContain('暂无平仓');expect(wrapper.text()).toContain('下一交易日开盘成交');expect(fetcher.mock.calls.some(c=>c[0].includes('/api/paper'))).toBe(false);wrapper.unmount()
 })
 it('highlights invalid corporate-action results and can compare saved reports',async()=>{
  vi.useFakeTimers();const first={...run(),quality:'invalid_corporate_actions',report:{...report,quality:'invalid_corporate_actions'}},second=run('2')
  vi.stubGlobal('fetch',vi.fn(async(path:string)=>{if(path==='/api/strategies')return response(catalog);if(path==='/api/research/1')return response(first);if(path==='/api/research/2')return response(second);return response({items:[first,second],total:2,page:1,pages:1,page_size:30})}))
  const wrapper=mount(Research,{props:{snapshot:snapshot(),active:true}});await flushPromises();expect(wrapper.text()).toContain('不可用于业绩评估');await wrapper.findAll('button').find(b=>b.text()==='报告')!.trigger('click');await flushPromises();expect(wrapper.text()).toContain('报告无效：区间存在公司行动')
  const checkboxes=wrapper.findAll('input[aria-label^="比较"]');await checkboxes[0].setValue(true);await checkboxes[1].setValue(true);await wrapper.findAll('button').find(b=>b.text().startsWith('比较所选'))!.trigger('click');await flushPromises();expect(wrapper.text()).toContain('实验对照');expect(wrapper.text()).toContain('不可作为有效业绩')
  await wrapper.findAll('button').find(b=>b.text()==='载入参数作对照')!.trigger('click');expect(wrapper.text()).toContain('已载入此实验参数');wrapper.unmount()
 })
 it('loads historical details only when expanded and identifies legacy summary-only scans',async()=>{
  const fetcher=vi.fn(async(path:string)=>path==='/api/history/1'?response({id:1,details:null}):response({items:[{id:1,created_at:'2026-10-13',as_of:'2026-10-12',mode:'demo',source:'合成',watch_count:1,wait_count:0,valid_count:1,stock_count:1}],total:1,page:1,pages:1,page_size:30}));vi.stubGlobal('fetch',fetcher)
  const wrapper=mount(History,{props:{active:true}});await flushPromises();expect(fetcher).toHaveBeenCalledTimes(1);const details=wrapper.get('details');(details.element as HTMLDetailsElement).open=true;await details.trigger('toggle');await flushPromises();expect(wrapper.text()).toContain('旧记录仅保存摘要');expect(fetcher).toHaveBeenCalledTimes(2);wrapper.unmount()
 })
})
