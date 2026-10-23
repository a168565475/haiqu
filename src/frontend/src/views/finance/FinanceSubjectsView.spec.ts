import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { AxiosError } from 'axios'
import FinanceSubjectsView from './FinanceSubjectsView.vue'
import { fetchFinanceSubjects, fetchFinanceSubject, fetchSubjectTree, createFinanceSubject } from '@/api/financeSubjects'
import type { FinanceSubject, FinanceSubjectPage } from '@/types/financeSubjects'

const state=vi.hoisted(()=>({allowed:true}))
vi.mock('vue-router',()=>({onBeforeRouteLeave:vi.fn()}))
vi.mock('@/stores/auth',()=>({useAuthStore:()=>({user:{is_superuser:false},hasPermission:()=>state.allowed})}))
vi.mock('@/api/financeSubjects',()=>({fetchFinanceSubjects:vi.fn(),fetchFinanceSubject:vi.fn(),fetchSubjectTree:vi.fn(),createFinanceSubject:vi.fn(),updateFinanceSubject:vi.fn(),deleteFinanceSubject:vi.fn()}))
const subject:FinanceSubject={id:'subject',parent_id:'parent',level:3,name:'合成科目',status:'ACTIVE',full_path:'费用 / 一级 / 合成科目',path_names:['费用','一级','合成科目'],effective_status:'ACTIVE',blocked_by_ancestor:null,child_count:0,affected_path_count:1,can_delete:true,delete_block_reason:null,etag:'"v1"',created_at:'',updated_at:''}
const result=(data=[subject]):FinanceSubjectPage=>({data,meta:{page:1,page_size:20,total:data.length,total_pages:1}})
const setup=()=>mount(FinanceSubjectsView,{global:{plugins:[ElementPlus],stubs:{AppWindowDialog:{props:['modelValue'],template:'<div v-if="modelValue" class="dialog-test"><slot/><slot name="footer"/></div>'}}}})
const button=(wrapper:ReturnType<typeof setup>,text:string)=>wrapper.findAll('button').find(item=>item.text()===text)!
describe('三级科目请求状态管理（隔离组件测试）',()=>{
  beforeEach(()=>{vi.clearAllMocks();state.allowed=true;vi.mocked(fetchFinanceSubjects).mockResolvedValue(result());vi.mocked(fetchFinanceSubject).mockResolvedValue(subject);vi.mocked(fetchSubjectTree).mockResolvedValue(result([]))})
  it('默认末级完整路径服务端分页与搜索',async()=>{
    const wrapper=setup()
    try {await flushPromises();expect(wrapper.text()).toContain(subject.full_path);expect(fetchFinanceSubjects).toHaveBeenCalledWith({page:1,page_size:20,q:'',level:3},expect.any(AbortSignal));await wrapper.find('.erp-list-filters input').setValue('路径');await button(wrapper,'应用筛选').trigger('click');await flushPromises();expect(fetchFinanceSubjects).toHaveBeenLastCalledWith({page:1,page_size:20,q:'路径',level:3},expect.any(AbortSignal))}finally{wrapper.unmount()}
  })
  it('忽略迟到列表并保留刷新失败前的数据',async()=>{
    let finish!:(value:FinanceSubjectPage)=>void
    vi.mocked(fetchFinanceSubjects).mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve}))
    const wrapper=setup()
    try {await button(wrapper,'应用筛选').trigger('click');await flushPromises();finish(result([{...subject,name:'过期',full_path:'过期'}]));await flushPromises();expect(wrapper.text()).not.toContain('过期');vi.mocked(fetchFinanceSubjects).mockRejectedValueOnce(new Error('网络失败'));await button(wrapper,'刷新').trigger('click');await flushPromises();expect(wrapper.text()).toContain('刷新失败，保留上次结果');expect(wrapper.text()).toContain(subject.full_path)}finally{wrapper.unmount()}
  })
  it('没有查看权限不请求接口',async()=>{state.allowed=false;const wrapper=setup();try{await flushPromises();expect(fetchFinanceSubjects).not.toHaveBeenCalled();expect(wrapper.text()).toContain('没有会计科目查看权限')}finally{wrapper.unmount()}})
  it('新增防重复并在超时后重放同键同体',async()=>{
    const wrapper=setup()
    try {
      await flushPromises();await button(wrapper,'新增科目').trigger('click');await flushPromises()
      const selects=wrapper.findAllComponents({name:'ElSelect'});selects[2]!.vm.$emit('update:modelValue',1);selects[2]!.vm.$emit('change',1);await flushPromises()
      await wrapper.find('.dialog-test .el-input input').setValue('新根科目')
      let reject!:(error:AxiosError)=>void
      vi.mocked(createFinanceSubject).mockImplementationOnce(()=>new Promise((_,fail)=>{reject=fail}))
      await Promise.all([button(wrapper,'保存科目').trigger('click'),button(wrapper,'保存科目').trigger('click')]);await flushPromises()
      expect(createFinanceSubject).toHaveBeenCalledTimes(1)
      reject(new AxiosError('timeout'));await flushPromises();expect(wrapper.text()).toContain('提交结果尚未确认')
      vi.mocked(createFinanceSubject).mockResolvedValue(subject);await button(wrapper,'重试原提交').trigger('click');await flushPromises()
      expect(vi.mocked(createFinanceSubject).mock.calls[0]).toEqual(vi.mocked(createFinanceSubject).mock.calls[1])
    }finally{wrapper.unmount()}
  })
})
