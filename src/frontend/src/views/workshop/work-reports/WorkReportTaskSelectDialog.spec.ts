import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElSelect } from 'element-plus'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'

import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import WorkReportTaskSelectDialog from './WorkReportTaskSelectDialog.vue'

const api = vi.hoisted(() => ({ tasks: vi.fn() }))
vi.mock('@/api/workshopReporting', () => ({ fetchWorkReportTasks: api.tasks }))
enableAutoUnmount(afterEach)

const task = { id: 'task-1', task_number: 'HT26050', order_number: 'SO-001', workshops: [{ id: 'workshop-1', name: '金工车间' }] }
const secondTask = { id: 'task-2', task_number: 'HT26051', order_number: 'SO-002', workshops: [{ id: 'workshop-2', name: '车缝车间' }] }
const response = (data = [task], page = 1, totalPages = 1) => ({ data, meta: { page, page_size: 20, total: data.length, total_pages: totalPages } })
const mountDialog = (props = {}) => mount(WorkReportTaskSelectDialog, {
  attachTo: document.body,
  props: { modelValue: true, ...props },
  global: {
    plugins: [ElementPlus],
    stubs: { AppWindowDialog: { template: '<section><slot /><footer><slot name="footer" /></footer></section>', props: ['modelValue', 'showClose', 'closeOnPressEscape'] } },
  },
})

beforeEach(() => {
  api.tasks.mockReset()
  api.tasks.mockResolvedValue(response([task, secondTask]))
})

it('先选任务再选车间，变更任务必须重新选择车间，不默认第一项', async () => {
  const wrapper = mountDialog()
  await flushPromises()
  const [taskSelect, workshopSelect] = wrapper.findAllComponents(ElSelect)
  expect(taskSelect!.props('modelValue')).toBe('')
  expect(workshopSelect!.props('disabled')).toBe(true)
  expect(wrapper.find('[data-testid="work-report-task-confirm"]').attributes('disabled')).toBeDefined()
  await taskSelect!.setValue('task-1')
  taskSelect!.vm.$emit('change', 'task-1')
  await flushPromises()
  expect(workshopSelect!.props('modelValue')).toBe('')
  await workshopSelect!.setValue('workshop-1')
  await wrapper.find('[data-testid="work-report-task-confirm"]').trigger('click')
  expect(wrapper.emitted('select')).toEqual([[{ productionTaskId: 'task-1', workshopId: 'workshop-1' }]])
  await taskSelect!.setValue('task-2')
  taskSelect!.vm.$emit('change', 'task-2')
  await flushPromises()
  expect(workshopSelect!.props('modelValue')).toBe('')
  expect(wrapper.find('[data-testid="work-report-task-confirm"]').attributes('disabled')).toBeDefined()
})

it('搜索按关键字重新请求，加载更多追加下一页，旧搜索响应不覆盖新结果', async () => {
  api.tasks.mockResolvedValue(response([task], 1, 2))
  const wrapper = mountDialog()
  await flushPromises()
  const taskSelect = wrapper.findAllComponents(ElSelect)[0]!
  await taskSelect.find('.el-select__wrapper').trigger('click')
  await flushPromises()
  api.tasks.mockResolvedValueOnce(response([secondTask], 2, 2))
  const loadMore = Array.from(document.body.querySelectorAll('button')).find(item => item.textContent?.trim() === '加载更多')
  expect(loadMore).toBeDefined()
  loadMore!.click()
  await flushPromises()
  expect(api.tasks).toHaveBeenLastCalledWith({ q: undefined, page: 2, page_size: 20 })
  expect(taskSelect.findAllComponents({ name: 'ElOption' })).toHaveLength(2)

  let finishOld!: (value: unknown) => void
  api.tasks.mockImplementationOnce(() => new Promise(resolve => { finishOld = resolve }))
  const searchTasks = taskSelect.props('remoteMethod')!
  searchTasks('HT26050')
  api.tasks.mockResolvedValueOnce(response([secondTask]))
  searchTasks('HT26051')
  await flushPromises()
  finishOld(response([task]))
  await flushPromises()
  expect(api.tasks).toHaveBeenLastCalledWith({ q: 'HT26051', page: 1, page_size: 20 })
  expect(taskSelect.findAllComponents({ name: 'ElOption' }).map(item => item.props('value'))).toEqual(['task-2'])
})

it('空结果有明确提示，失败展示后端原因且不能确认，重试可恢复', async () => {
  api.tasks.mockResolvedValueOnce(response([]))
  const wrapper = mountDialog()
  await flushPromises()
  const taskSelect = wrapper.findAllComponents(ElSelect)[0]!
  expect(taskSelect.props('noDataText')).toBe('暂无可查看的生产任务单')
  api.tasks.mockRejectedValueOnce({ response: { data: { error: { message: '没有报工查看权限。' } } } })
  const searchTasks = taskSelect.props('remoteMethod')!
  searchTasks('HT')
  await flushPromises()
  expect(wrapper.text()).toContain('没有报工查看权限。')
  expect(wrapper.find('[data-testid="work-report-task-confirm"]').attributes('disabled')).toBeDefined()
  await wrapper.find('.el-alert button').trigger('click')
  await flushPromises()
  expect(wrapper.find('.el-alert').exists()).toBe(false)
})

it('关闭弹窗使旧请求失效，重新打开后不恢复旧搜索内容', async () => {
  let finishOld!: (value: unknown) => void
  api.tasks.mockImplementationOnce(() => new Promise(resolve => { finishOld = resolve }))
  const wrapper = mountDialog()
  await wrapper.setProps({ modelValue: false })
  api.tasks.mockResolvedValueOnce(response([secondTask]))
  await wrapper.setProps({ modelValue: true })
  await flushPromises()
  finishOld(response([task]))
  await flushPromises()
  expect(wrapper.findAllComponents({ name: 'ElOption' }).map(item => item.props('value'))).toEqual(['task-2'])
})

it('确认处理中禁用取消、窗口关闭及 Escape，不能再关闭后等待晚到导航', async () => {
  const wrapper = mountDialog({ initialTask: task, initialWorkshopId: 'workshop-1', submitting: true })
  await flushPromises()
  const dialog = wrapper.findComponent(AppWindowDialog)
  expect(dialog.props('showClose')).toBe(false)
  expect(dialog.props('closeOnPressEscape')).toBe(false)
  dialog.vm.$emit('update:modelValue', false)
  await flushPromises()
  expect(wrapper.emitted('update:modelValue')).toBeUndefined()
  expect(wrapper.findAll('footer button').every(button => button.attributes('disabled') !== undefined)).toBe(true)
})
