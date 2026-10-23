import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import FinanceStatementSourceDialog from './FinanceStatementSourceDialog.vue'
import { fetchFinanceSourceTasks } from '@/api/financeStatements'
import type { FinanceSourceTask, FinanceSourceTaskPage } from '@/types/financeStatements'

vi.mock('@/api/financeStatements', () => ({ fetchFinanceSourceTasks: vi.fn() }))
const task: FinanceSourceTask = { id: 'task', task_number: 'TASK', status: 'READY', source_order_date: '2026-10-23', salesperson: { id: 'sales', code: 'SALES', name: '合成业务员' } }
const response = (data = [task], page = 1): FinanceSourceTaskPage => ({ data, meta: { page, page_size: 20, total: 21, total_pages: 2 } })
const setup = () => mount(FinanceStatementSourceDialog, { props: { modelValue: false }, global: { plugins: [ElementPlus], stubs: { AppWindowDialog: { props: ['modelValue'], template: '<div v-if="modelValue"><slot/><slot name="footer"/></div>' } } } })
const confirm = (wrapper: ReturnType<typeof setup>) => wrapper.findAll('button').find(button => button.text() === '确认选择')!

describe('仅保留生产任务选择弹窗', () => {
  beforeEach(() => { vi.resetAllMocks(); vi.mocked(fetchFinanceSourceTasks).mockResolvedValue(response()) })
  it('读取任务并确认单选，不再包含产品分支', async () => {
    const wrapper = setup()
    try {
      await wrapper.setProps({ modelValue: true }); await flushPromises()
      expect(fetchFinanceSourceTasks).toHaveBeenCalledWith({ q: '', page: 1, page_size: 20 }, expect.any(AbortSignal))
      expect(confirm(wrapper).attributes('disabled')).toBeDefined()
      await wrapper.get('[aria-label="选择任务TASK"] input').setValue(true)
      await confirm(wrapper).trigger('click')
      expect(wrapper.emitted('task')?.[0]).toEqual([task]); expect(wrapper.emitted('update:modelValue')?.[0]).toEqual([false])
      expect(wrapper.find('input[type="checkbox"]').exists()).toBe(false)
    } finally { wrapper.unmount() }
  })
  it('搜索和分页继续读取真实接口契约', async () => {
    const wrapper = setup()
    try {
      await wrapper.setProps({ modelValue: true }); await flushPromises()
      await wrapper.get('input[aria-label="搜索生产任务"]').setValue('TASK'); await wrapper.get('input[aria-label="搜索生产任务"]').trigger('keyup.enter'); await flushPromises()
      expect(fetchFinanceSourceTasks).toHaveBeenLastCalledWith({ q: 'TASK', page: 1, page_size: 20 }, expect.any(AbortSignal))
      vi.mocked(fetchFinanceSourceTasks).mockResolvedValueOnce(response([task], 2))
      await wrapper.get('.btn-next').trigger('click'); await flushPromises()
      expect(fetchFinanceSourceTasks).toHaveBeenLastCalledWith({ q: 'TASK', page: 2, page_size: 20 }, expect.any(AbortSignal))
    } finally { wrapper.unmount() }
  })
  it('读取失败不伪装空态，关闭后的迟到结果不回填', async () => {
    let resolve!: (value: FinanceSourceTaskPage) => void
    vi.mocked(fetchFinanceSourceTasks).mockRejectedValueOnce(new Error('offline'))
    const wrapper = setup()
    try {
      await wrapper.setProps({ modelValue: true }); await flushPromises()
      expect(wrapper.text()).toContain('加载失败，请重试'); expect(wrapper.text()).not.toContain('暂无可对账生产任务')
      expect(confirm(wrapper).attributes('disabled')).toBeDefined()
      vi.mocked(fetchFinanceSourceTasks).mockImplementationOnce(() => new Promise(done => { resolve = done }))
      await wrapper.findAll('button').find(button => button.text() === '重试')!.trigger('click'); await flushPromises()
      await wrapper.setProps({ modelValue: false }); resolve(response([{ ...task, task_number: '迟到任务' }])); await flushPromises()
      await wrapper.setProps({ modelValue: true }); await flushPromises(); expect(wrapper.text()).not.toContain('迟到任务')
    } finally { wrapper.unmount() }
  })
})
