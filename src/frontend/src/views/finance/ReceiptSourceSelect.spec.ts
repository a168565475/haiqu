import { DOMWrapper, flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElOption, ElSelect } from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ReceiptSourceSelect from './ReceiptSourceSelect.vue'
import { fetchFinanceSourceTasks, fetchFinanceStatements } from '@/api/financeStatements'
import type { FinanceSourceTask, FinanceSourceTaskPage, FinanceStatement, FinanceStatementPage } from '@/types/financeStatements'

vi.mock('@/api/financeStatements', () => ({ fetchFinanceSourceTasks: vi.fn(), fetchFinanceStatements: vi.fn() }))
const task: FinanceSourceTask = { id: 'task', task_number: 'TASK', status: 'READY', source_order_date: '2026-10-23', task_order_date: '2026-10-24', task_delivery_date: '2026-11-15', salesperson: { id: 'sales', code: 'SALES', name: '合成业务员' } }
const statement = { id: 'statement', number: 'BILL', production_task_id: 'task', status: 'ACTIVE' } as FinanceStatement
const meta = (page = 1) => ({ page, page_size: 20, total: 21, total_pages: 2 })
const taskPage = (data = [task], page = 1): FinanceSourceTaskPage => ({ data, meta: meta(page) })
const statementPage = (data = [statement], page = 1): FinanceStatementPage => ({ data, meta: meta(page) })
const setup = (mode: 'task' | 'statement' = 'task') => mount(ReceiptSourceSelect, {
  attachTo: document.body, props: { mode, taskId: 'task', selectedTask: { id: 'current-task', task_number: 'CURRENT TASK', salesperson: task.salesperson }, selectedStatement: { ...statement, id: 'current-statement', number: 'CURRENT BILL' } },
  global: { plugins: [ElementPlus] },
})
const open = async (wrapper: ReturnType<typeof setup>) => { await wrapper.get('.el-select__wrapper').trigger('click'); await flushPromises() }
const click = async (text: string) => { await new DOMWrapper(document.body).findAll('button').find(button => button.text() === text)!.trigger('click'); await flushPromises() }
const ids = (wrapper: ReturnType<typeof setup>) => wrapper.findAllComponents(ElOption).map(option => option.props('value'))

describe('收款来源搜索下拉（合成组件测试）', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(fetchFinanceSourceTasks).mockResolvedValue(taskPage())
    vi.mocked(fetchFinanceStatements).mockResolvedValue(statementPage())
  })
  it.each(['task', 'statement'] as const)('%s分页保持当前来源，失败重试未完成页', async mode => {
    const wrapper = setup(mode)
    try {
      await open(wrapper)
      expect(wrapper.findComponent(ElSelect).props('remoteShowSuffix')).toBe(true)
      if (mode === 'task') {
        expect(fetchFinanceSourceTasks).toHaveBeenLastCalledWith({ q: '', mode: 'receipt', page: 1, page_size: 20 }, expect.any(AbortSignal))
        expect(wrapper.findAllComponents(ElOption).map(option => option.props('label'))).toEqual(['CURRENT TASK · 合成业务员', 'TASK · 合成业务员'])
        vi.mocked(fetchFinanceSourceTasks).mockRejectedValueOnce(new Error('offline'))
      } else {
        expect(fetchFinanceStatements).toHaveBeenLastCalledWith({ q: '', task_id: 'task', status: 'ACTIVE', page: 1, page_size: 20 }, expect.any(AbortSignal))
        vi.mocked(fetchFinanceStatements).mockRejectedValueOnce(new Error('offline'))
      }
      await click('加载更多')
      expect(document.body.textContent).toContain('来源加载失败，请重试')
      expect(wrapper.findComponent(ElSelect).props('modelValue')).toBe(`current-${mode}`)
      if (mode === 'task') vi.mocked(fetchFinanceSourceTasks).mockResolvedValueOnce(taskPage([{ ...task, id: 'second' }], 2))
      else vi.mocked(fetchFinanceStatements).mockResolvedValueOnce(statementPage([{ ...statement, id: 'second' }], 2))
      await click('重试')
      expect(ids(wrapper)).toEqual([`current-${mode}`, mode, 'second'])
      const api = mode === 'task' ? fetchFinanceSourceTasks : fetchFinanceStatements
      expect(vi.mocked(api).mock.calls.at(-1)?.[0].page).toBe(2)
    } finally { wrapper.unmount() }
  })
  it.each(['task', 'statement'] as const)('%s选择交给父表单确认，取消保持旧值，确认才回填', async mode => {
    const wrapper = setup(mode)
    try {
      await open(wrapper)
      const select = wrapper.findComponent(ElSelect)
      await wrapper.findAllComponents(ElOption).find(option => option.props('value') === mode)!.trigger('click'); await flushPromises()
      expect(wrapper.emitted(mode)?.[0]).toEqual([mode === 'task' ? task : statement])
      expect(select.props('modelValue')).toBe(`current-${mode}`)
      await wrapper.setProps(mode === 'task' ? { selectedTask: task } : { selectedStatement: statement })
      expect(select.props('modelValue')).toBe(mode)
    } finally { wrapper.unmount() }
  })
  it('搜索请求隔离，失败重试同一查询，空结果保留当前任务', async () => {
    let finish!: (value: FinanceSourceTaskPage) => void
    const wrapper = setup()
    try {
      await open(wrapper)
      vi.mocked(fetchFinanceSourceTasks).mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
      wrapper.findComponent(ElSelect).props('remoteMethod')!('OLD'); await flushPromises()
      const oldSignal = vi.mocked(fetchFinanceSourceTasks).mock.calls.at(-1)![1]!
      vi.mocked(fetchFinanceSourceTasks).mockRejectedValueOnce(new Error('offline'))
      wrapper.findComponent(ElSelect).props('remoteMethod')!(' NEW '); await flushPromises()
      expect(oldSignal.aborted).toBe(true)
      finish(taskPage([{ ...task, id: 'late' }])); await flushPromises()
      expect(ids(wrapper)).toEqual(['current-task'])
      vi.mocked(fetchFinanceSourceTasks).mockResolvedValueOnce({ data: [], meta: { ...meta(), total: 0, total_pages: 0 } })
      await click('重试')
      expect(fetchFinanceSourceTasks).toHaveBeenLastCalledWith({ q: 'NEW', mode: 'receipt', page: 1, page_size: 20 }, expect.any(AbortSignal))
      expect(ids(wrapper)).toEqual(['current-task'])
      expect(wrapper.findComponent(ElSelect).props('modelValue')).toBe('current-task')
      expect(wrapper.findComponent(ElOption).props('label')).toBe('CURRENT TASK · 合成业务员')
    } finally { wrapper.unmount() }
  })
  it('更换任务取消旧账单查询，只展示新任务结果', async () => {
    let finish!: (value: FinanceStatementPage) => void
    vi.mocked(fetchFinanceStatements).mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    const wrapper = setup('statement')
    try {
      await open(wrapper)
      const oldSignal = vi.mocked(fetchFinanceStatements).mock.calls[0]![1]!
      vi.mocked(fetchFinanceStatements).mockResolvedValueOnce(statementPage([{ ...statement, id: 'new', production_task_id: 'new-task' }]))
      await wrapper.setProps({ taskId: 'new-task', selectedStatement: null }); await flushPromises()
      finish(statementPage()); await flushPromises()
      expect(oldSignal.aborted).toBe(true)
      expect(fetchFinanceStatements).toHaveBeenLastCalledWith({ q: '', task_id: 'new-task', status: 'ACTIVE', page: 1, page_size: 20 }, expect.any(AbortSignal))
      expect(ids(wrapper)).toEqual(['new'])
      expect(wrapper.findComponent(ElSelect).props('modelValue')).toBeUndefined()
    } finally { wrapper.unmount() }
  })
  it('未选任务禁用账单，关闭或卸载后旧响应不回填', async () => {
    let finish!: (value: FinanceStatementPage) => void
    const wrapper = setup('statement')
    try {
      await wrapper.setProps({ taskId: undefined, selectedStatement: null })
      expect(wrapper.findComponent(ElSelect).props('disabled')).toBe(true)
      expect(fetchFinanceStatements).not.toHaveBeenCalled()
      await wrapper.setProps({ taskId: 'task' })
      vi.mocked(fetchFinanceStatements).mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
      await open(wrapper)
      const signal = vi.mocked(fetchFinanceStatements).mock.calls[0]![1]!
      wrapper.findComponent(ElSelect).vm.$emit('visible-change', false)
      finish(statementPage()); await flushPromises()
      expect(signal.aborted).toBe(true); expect(ids(wrapper)).toEqual([])
    } finally { wrapper.unmount() }
  })
})
