import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'

import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import WorkReportTaskSelectDialog from './WorkReportTaskSelectDialog.vue'

const api = vi.hoisted(() => ({ tasks: vi.fn() }))
vi.mock('@/api/workshopReporting', () => ({ fetchWorkReportTasks: api.tasks }))

enableAutoUnmount(afterEach)

const task = {
  id: 'task-1', task_number: 'HT26050', order_number: 'SO-001',
  product: { id: 'product-1', name: '靠背凳', number: '100260001', image_url: '/api/task-image/1/' }, product_count: 2,
  reported_amount: '644.00', progress: { status: 'READY', percentage: 25 },
  workshops: [
    { id: 'workshop-1', name: '金工车间', reported_amount: '584.00', progress: { status: 'READY', percentage: 40 } },
    { id: 'workshop-2', name: '车缝车间', reported_amount: '60.00', progress: { status: 'NOT_CONFIGURED', percentage: null } },
  ],
}
const secondTask = {
  id: 'task-2', task_number: 'HT26051', order_number: 'SO-002',
  product: null, product_count: 0, reported_amount: '0.00', progress: { status: 'UNAVAILABLE', percentage: null },
  workshops: [{ id: 'workshop-2', name: '车缝车间', reported_amount: '0.00', progress: { status: 'READY', percentage: 0 } }],
}
const response = (data: unknown[] = [task], page = 1, totalPages = 1) => ({ data, meta: { page, page_size: 20, total: data.length, total_pages: totalPages } })
const mountDialog = (props = {}) => mount(WorkReportTaskSelectDialog, {
  attachTo: document.body,
  props: { modelValue: true, ...props },
  global: {
    plugins: [ElementPlus],
    stubs: { AppWindowDialog: { template: '<section><slot /><footer><slot name="footer" /></footer></section>', props: ['modelValue', 'showClose', 'closeOnPressEscape'] } },
  },
})
const cardSelector = (id: string) => `[data-testid="work-report-task-card"][data-task-id="${id}"]`
const workshopSelector = (name: string) => `[data-testid="work-report-workshop-choice"][data-workshop-name="${name}"]`

beforeEach(() => {
  api.tasks.mockReset()
  api.tasks.mockResolvedValue(response([task, secondTask]))
})

it('任务以卡片选择，四车间只启用该任务授权项，变更任务必须重选车间', async () => {
  const wrapper = mountDialog()
  await flushPromises()
  expect(wrapper.findAll('[data-testid="work-report-task-card"]')).toHaveLength(2)
  const workshops = wrapper.findAll('[data-testid="work-report-workshop-choice"]')
  expect(workshops.map(item => item.attributes('data-workshop-name'))).toEqual(['金工车间', '车缝车间', '装配车间', '敲布孔'])
  expect(workshops.every(item => item.attributes('disabled') !== undefined)).toBe(true)
  expect(wrapper.find('[data-testid="work-report-task-confirm"]').attributes('disabled')).toBeDefined()
  await wrapper.get(cardSelector('task-1')).trigger('click')
  expect(wrapper.get(cardSelector('task-1')).attributes('aria-pressed')).toBe('true')
  expect(wrapper.get(workshopSelector('金工车间')).attributes('disabled')).toBeUndefined()
  expect(wrapper.get(workshopSelector('装配车间')).attributes('disabled')).toBeDefined()
  await wrapper.get(workshopSelector('金工车间')).trigger('click')
  await wrapper.get('[data-testid="work-report-task-confirm"]').trigger('click')
  expect(wrapper.emitted('select')).toEqual([[{ productionTaskId: 'task-1', workshopId: 'workshop-1' }]])
  await wrapper.get(cardSelector('task-2')).trigger('click')
  expect(wrapper.get(workshopSelector('车缝车间')).attributes('aria-pressed')).toBe('false')
  expect(wrapper.get('[data-testid="work-report-task-confirm"]').attributes('disabled')).toBeDefined()
})

it('卡片呈现真实图片、产品数和任务合计，选车间仅切换当前卡片的统计口径', async () => {
  const wrapper = mountDialog()
  await flushPromises()
  const first = wrapper.get(cardSelector('task-1'))
  expect(first.get('img').attributes('src')).toBe('/api/task-image/1/')
  expect(first.text()).toContain('共 2 条产品明细')
  expect(first.text()).toContain('可查看车间已报工')
  expect(first.text()).toContain('¥644.00')
  expect(first.get('[role="progressbar"]').attributes('aria-valuenow')).toBe('25')
  await first.trigger('click')
  await wrapper.get(workshopSelector('金工车间')).trigger('click')
  expect(first.text()).toContain('金工车间已报工')
  expect(first.text()).toContain('¥584.00')
  expect(first.get('[role="progressbar"]').attributes('aria-valuenow')).toBe('40')
  expect(wrapper.get(cardSelector('task-2')).text()).toContain('可查看车间已报工')
  expect(wrapper.get(cardSelector('task-2')).text()).toContain('¥0.00')
  await wrapper.get(workshopSelector('车缝车间')).trigger('click')
  expect(first.text()).toContain('¥60.00')
  expect(first.text()).toContain('待配置')
  expect(first.find('[role="progressbar"]').exists()).toBe(false)
})

it('未知进度与真实零进度分开，缺失金额不假装为零，图片失败退为占位图标', async () => {
  api.tasks.mockResolvedValueOnce(response([task, secondTask, { id: 'legacy', task_number: 'HT旧', order_number: 'SO旧', workshops: [] }]))
  const wrapper = mountDialog()
  await flushPromises()
  expect(wrapper.get(cardSelector('task-2')).text()).toContain('暂无进度')
  expect(wrapper.get(cardSelector('legacy')).text()).not.toContain('¥0.00')
  expect(wrapper.get(cardSelector('legacy')).text()).toContain('待配置')
  await wrapper.get(cardSelector('task-1')).get('img').trigger('error')
  expect(wrapper.get(cardSelector('task-1')).find('img').exists()).toBe(false)
  expect(wrapper.get(cardSelector('task-1')).get('[data-testid="task-image-placeholder"]').attributes('aria-label')).toBe('图片暂不可用')
  await wrapper.get(cardSelector('task-2')).trigger('click')
  await wrapper.get(workshopSelector('车缝车间')).trigger('click')
  expect(wrapper.get(cardSelector('task-2')).get('[role="progressbar"]').attributes('aria-valuenow')).toBe('0')
})

it('初始任务由最新响应更新金额和图片，已失权车间清除后不能确认', async () => {
  const staleTask = { ...task, reported_amount: '999.00', product: { ...task.product, image_url: '/old-image/' } }
  api.tasks.mockResolvedValueOnce(response([{ ...task, workshops: [task.workshops[1]] }]))
  const wrapper = mountDialog({ initialTask: staleTask, initialWorkshopId: 'workshop-1' })
  await flushPromises()
  const first = wrapper.get(cardSelector('task-1'))
  expect(first.text()).toContain('¥644.00')
  expect(first.text()).not.toContain('¥999.00')
  expect(first.get('img').attributes('src')).toBe('/api/task-image/1/')
  expect(wrapper.get(workshopSelector('金工车间')).attributes('disabled')).toBeDefined()
  expect(wrapper.get('[data-testid="work-report-task-confirm"]').attributes('disabled')).toBeDefined()
})

it('初始任务不在首屏时按任务 ID 重新确认权限并恢复车间，拒绝时不保留旧卡片', async () => {
  api.tasks.mockResolvedValueOnce(response([secondTask])).mockResolvedValueOnce(response([task]))
  const wrapper = mountDialog({ initialTask: task, initialWorkshopId: 'workshop-1' })
  await flushPromises()
  expect(api.tasks).toHaveBeenLastCalledWith({ production_task_id: 'task-1', page: 1, page_size: 1 })
  expect(wrapper.get(workshopSelector('金工车间')).attributes('aria-pressed')).toBe('true')
  expect(wrapper.get('[data-testid="work-report-task-confirm"]').attributes('disabled')).toBeUndefined()
  await wrapper.setProps({ modelValue: false })
  api.tasks.mockResolvedValueOnce(response([secondTask])).mockRejectedValueOnce({ response: { data: { error: { message: '没有报工查看权限。' } } } })
  await wrapper.setProps({ modelValue: true })
  await flushPromises()
  expect(wrapper.find(cardSelector('task-1')).exists()).toBe(false)
  expect(wrapper.text()).toContain('没有报工查看权限。')
  expect(wrapper.get('[data-testid="work-report-task-confirm"]').attributes('disabled')).toBeDefined()
})

it('输入搜索与 Enter 提交都加载新结果，清空恢复列表，分页去重且忽略旧搜索响应', async () => {
  api.tasks.mockResolvedValueOnce(response([task], 1, 2))
  const wrapper = mountDialog()
  await flushPromises()
  api.tasks.mockResolvedValueOnce(response([task, secondTask], 2, 2))
  await wrapper.get('[data-testid="work-report-task-more"]').trigger('click')
  await flushPromises()
  expect(api.tasks).toHaveBeenLastCalledWith({ q: undefined, page: 2, page_size: 20 })
  expect(wrapper.findAll('[data-testid="work-report-task-card"]')).toHaveLength(2)

  let finishOld!: (value: unknown) => void
  api.tasks.mockImplementationOnce(() => new Promise(resolve => { finishOld = resolve }))
  const input = wrapper.get('input[data-testid="work-report-task-search"]')
  await input.setValue('HT26050')
  await wrapper.get('form').trigger('submit')
  api.tasks.mockResolvedValueOnce(response([secondTask]))
  await input.setValue('  HT26051  ')
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  finishOld(response([task]))
  await flushPromises()
  expect(api.tasks).toHaveBeenLastCalledWith({ q: 'HT26051', page: 1, page_size: 20 })
  expect(wrapper.findAll('[data-testid="work-report-task-card"]').map(item => item.attributes('data-task-id'))).toEqual(['task-2'])
  api.tasks.mockResolvedValueOnce(response([task, secondTask]))
  await wrapper.get('[data-testid="work-report-task-clear"]').trigger('click')
  await flushPromises()
  expect(api.tasks).toHaveBeenLastCalledWith({ q: undefined, page: 1, page_size: 20 })
  expect((input.element as HTMLInputElement).value).toBe('')
  expect(wrapper.findAll('[data-testid="work-report-task-card"]')).toHaveLength(2)
})

it('只编辑搜索框未提交不会混入下一页请求的查询条件', async () => {
  api.tasks.mockResolvedValueOnce(response([task], 1, 2))
  const wrapper = mountDialog()
  await flushPromises()
  await wrapper.get('input[data-testid="work-report-task-search"]').setValue('尚未搜索')
  api.tasks.mockResolvedValueOnce(response([secondTask], 2, 2))
  await wrapper.get('[data-testid="work-report-task-more"]').trigger('click')
  await flushPromises()
  expect(api.tasks).toHaveBeenLastCalledWith({ q: undefined, page: 2, page_size: 20 })
})

it('已选任务后重新搜索无匹配结果，清除旧卡片和车间范围，不能继续确认', async () => {
  const wrapper = mountDialog()
  await flushPromises()
  await wrapper.get(cardSelector('task-1')).trigger('click')
  await wrapper.get(workshopSelector('金工车间')).trigger('click')
  api.tasks.mockResolvedValueOnce(response([]))
  await wrapper.get('input[data-testid="work-report-task-search"]').setValue('不存在的任务')
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  expect(wrapper.findAll('[data-testid="work-report-task-card"]')).toHaveLength(0)
  expect(wrapper.text()).toContain('暂无可查看的生产任务单')
  expect(wrapper.findAll('[data-testid="work-report-workshop-choice"]').every(button => button.attributes('disabled') !== undefined)).toBe(true)
  expect(wrapper.get('[data-testid="work-report-task-confirm"]').attributes('disabled')).toBeDefined()
})

it('空结果有明确提示，失败展示后端原因且不能确认，重试可恢复', async () => {
  api.tasks.mockResolvedValueOnce(response([]))
  const wrapper = mountDialog()
  await flushPromises()
  expect(wrapper.text()).toContain('暂无可查看的生产任务单')
  api.tasks.mockRejectedValueOnce({ response: { data: { error: { message: '没有报工查看权限。' } } } })
  await wrapper.get('input[data-testid="work-report-task-search"]').setValue('HT')
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  expect(wrapper.text()).toContain('没有报工查看权限。')
  expect(wrapper.get('[data-testid="work-report-task-confirm"]').attributes('disabled')).toBeDefined()
  await wrapper.get('.el-alert button').trigger('click')
  await flushPromises()
  expect(wrapper.find('.el-alert').exists()).toBe(false)
  expect(wrapper.findAll('[data-testid="work-report-task-card"]')).toHaveLength(2)
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
  expect(wrapper.findAll('[data-testid="work-report-task-card"]').map(item => item.attributes('data-task-id'))).toEqual(['task-2'])
})

it('确认处理中禁用任务、车间、取消、窗口关闭及 Escape，不能关闭后等待晚到导航', async () => {
  const wrapper = mountDialog({ initialTask: task, initialWorkshopId: 'workshop-1', submitting: true })
  await flushPromises()
  const dialog = wrapper.findComponent(AppWindowDialog)
  expect(dialog.props('showClose')).toBe(false)
  expect(dialog.props('closeOnPressEscape')).toBe(false)
  dialog.vm.$emit('update:modelValue', false)
  await flushPromises()
  expect(wrapper.emitted('update:modelValue')).toBeUndefined()
  expect(wrapper.findAll('footer button').every(button => button.attributes('disabled') !== undefined)).toBe(true)
  expect(wrapper.findAll('[data-testid="work-report-task-card"], [data-testid="work-report-workshop-choice"]').every(button => button.attributes('disabled') !== undefined)).toBe(true)
})
