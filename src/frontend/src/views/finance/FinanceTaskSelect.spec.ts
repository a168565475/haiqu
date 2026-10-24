import { DOMWrapper, flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElOption, ElSelect } from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import FinanceTaskSelect from './FinanceTaskSelect.vue'
import { fetchFinanceSourceTasks } from '@/api/financeStatements'
import type { FinanceSourceTask, FinanceSourceTaskPage } from '@/types/financeStatements'

vi.mock('@/api/financeStatements', () => ({ fetchFinanceSourceTasks: vi.fn() }))
const task: FinanceSourceTask = { id: 'task', task_number: 'TASK', status: 'READY', source_order_date: '2026-10-23', task_order_date: '2026-10-24', task_delivery_date: '2026-11-15', salesperson: { id: 'sales', code: 'SALES', name: '合成业务员' } }
const response = (data = [task], page = 1): FinanceSourceTaskPage => ({ data, meta: { page, page_size: 20, total: 21, total_pages: 2 } })
const setup = (modelValue?: FinanceSourceTask) => mount(FinanceTaskSelect, { attachTo: document.body, props: { modelValue }, global: { plugins: [ElementPlus] } })
const open = async (wrapper: ReturnType<typeof setup>) => { await wrapper.get('.el-select__wrapper').trigger('click'); await flushPromises() }

describe('可搜索任务下拉（合成组件测试）', () => {
  beforeEach(() => { vi.resetAllMocks(); vi.mocked(fetchFinanceSourceTasks).mockResolvedValue(response()) })
  it('分页加载更多，保留当前编辑任务即便候选不包含它', async () => {
    const current = { ...task, id: 'current', task_number: 'CURRENT' }, second = { ...task, id: 'second', task_number: 'SECOND' }
    const wrapper = setup(current)
    try {
      await open(wrapper)
      expect(wrapper.findComponent(ElSelect).props('remoteShowSuffix')).toBe(true)
      expect(fetchFinanceSourceTasks).toHaveBeenCalledWith({ q: '', page: 1, page_size: 20 }, expect.any(AbortSignal))
      vi.mocked(fetchFinanceSourceTasks).mockResolvedValueOnce(response([second], 2))
      const more = new DOMWrapper(document.body).findAll('button').find(button => button.text() === '加载更多')!
      await more.trigger('click'); await flushPromises()
      expect(wrapper.findAllComponents(ElOption).map(option => option.props('value'))).toEqual(['current', 'task', 'second'])
    } finally { wrapper.unmount() }
  })
  it('选择仅交给父组件确认，父组件取消时下拉保持原任务', async () => {
    const current = { ...task, id: 'current', task_number: 'CURRENT' }
    const wrapper = setup(current)
    try {
      await open(wrapper)
      wrapper.findComponent(ElSelect).vm.$emit('update:modelValue', task.id)
      wrapper.findComponent(ElSelect).vm.$emit('change', task.id); await flushPromises()
      expect(wrapper.emitted('task')?.[0]).toEqual([task])
      expect(wrapper.findComponent(ElSelect).props('modelValue')).toBe(current.id)
      await wrapper.setProps({ modelValue: task }); expect(wrapper.findComponent(ElSelect).props('modelValue')).toBe(task.id)
    } finally { wrapper.unmount() }
  })
  it('搜索失败可重试，旧查询响应不能覆盖新查询', async () => {
    let resolve!: (value: FinanceSourceTaskPage) => void
    const wrapper = setup()
    try {
      await open(wrapper)
      vi.mocked(fetchFinanceSourceTasks).mockImplementationOnce(() => new Promise(done => { resolve = done }))
      wrapper.findComponent(ElSelect).props('remoteMethod')!('OLD'); await flushPromises()
      vi.mocked(fetchFinanceSourceTasks).mockResolvedValueOnce(response([{ ...task, id: 'new', task_number: 'NEW' }]))
      wrapper.findComponent(ElSelect).props('remoteMethod')!('NEW'); await flushPromises()
      resolve(response([{ ...task, task_number: 'OLD' }])); await flushPromises()
      expect(wrapper.findAllComponents(ElOption).map(option => option.props('label'))).toEqual(['NEW'])
      vi.mocked(fetchFinanceSourceTasks).mockRejectedValueOnce(new Error('offline'))
      wrapper.findComponent(ElSelect).props('remoteMethod')!('FAIL'); await flushPromises()
      expect(document.body.textContent).toContain('任务加载失败，请重试')
      vi.mocked(fetchFinanceSourceTasks).mockResolvedValueOnce(response([task]))
      await new DOMWrapper(document.body).findAll('button').find(button => button.text() === '重试')!.trigger('click'); await flushPromises()
      expect(fetchFinanceSourceTasks).toHaveBeenLastCalledWith({ q: 'FAIL', page: 1, page_size: 20 }, expect.any(AbortSignal))
      expect(wrapper.findAllComponents(ElOption).map(option => option.props('label'))).toEqual(['TASK'])
    } finally { wrapper.unmount() }
  })
  it('加载更多失败重试当前未完成页，不重复旧页或丢失选择', async () => {
    const wrapper = setup(task)
    try {
      await open(wrapper)
      vi.mocked(fetchFinanceSourceTasks).mockRejectedValueOnce(new Error('offline'))
      await new DOMWrapper(document.body).findAll('button').find(button => button.text() === '加载更多')!.trigger('click'); await flushPromises()
      expect(wrapper.findComponent(ElSelect).props('modelValue')).toBe(task.id)
      vi.mocked(fetchFinanceSourceTasks).mockResolvedValueOnce(response([{ ...task, id: 'second', task_number: 'SECOND' }], 2))
      await new DOMWrapper(document.body).findAll('button').find(button => button.text() === '重试')!.trigger('click'); await flushPromises()
      expect(fetchFinanceSourceTasks).toHaveBeenLastCalledWith({ q: '', page: 2, page_size: 20 }, expect.any(AbortSignal))
      expect(wrapper.findAllComponents(ElOption).map(option => option.props('value'))).toEqual(['task', 'second'])
    } finally { wrapper.unmount() }
  })
  it('关闭后旧响应不回填，重新打开仍保留当前任务', async () => {
    let resolve!: (value: FinanceSourceTaskPage) => void
    const wrapper = setup(task)
    try {
      await open(wrapper)
      vi.mocked(fetchFinanceSourceTasks).mockImplementationOnce(() => new Promise(done => { resolve = done }))
      wrapper.findComponent(ElSelect).props('remoteMethod')!('OLD'); await flushPromises()
      wrapper.findComponent(ElSelect).vm.$emit('visible-change', false)
      resolve(response([{ ...task, id: 'late', task_number: 'LATE' }])); await flushPromises()
      expect(wrapper.findAllComponents(ElOption).map(option => option.props('label'))).toEqual(['TASK'])
      expect(wrapper.findComponent(ElSelect).props('modelValue')).toBe(task.id)
    } finally { wrapper.unmount() }
  })
})
