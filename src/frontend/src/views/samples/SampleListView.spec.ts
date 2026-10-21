import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import ElementPlus, { ElDatePicker, ElSelect, ElPagination } from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AxiosError } from 'axios'
import SampleListView from './SampleListView.vue'
import { useAuthStore } from '@/stores/auth'

const api = vi.hoisted(() => ({ rows: vi.fn(), options: vi.fn(), stats: vi.fn(), push: vi.fn(), query: {} as Record<string, string> }))
vi.mock('vue-router', () => ({ useRoute: () => ({ query: api.query }), useRouter: () => ({ push: api.push }) }))
vi.mock('@/api/samples', () => ({
  fetchSamples: api.rows, fetchSampleOptions: api.options, fetchSampleStats: api.stats,
  deleteSample: vi.fn(), fetchSample: vi.fn(),
}))

const result = (name: string) => ({ data: [{ id: name, request_number: name, etag: '"version-1"', customer_name: '客户', products: [], status: 'PMC_REVIEW', status_display: 'PMC待审核', item_summary: { text: '桌子', count: 1 } }], meta: { total: 1 } })
const wrappers: ReturnType<typeof mount>[] = []
function render(employeeId?: string, permissions: string[] = []) {
  const pinia = createPinia()
  if (employeeId) useAuthStore(pinia).user = {
    id: 1, username: 'test', display_name: '测试员工', is_superuser: false, permissions, data_scope: 'OWN',
    employee: { id: employeeId, employee_code: 'TEST', display_name: '测试员工', status: 'ACTIVE' },
  }
  const wrapper = mount(SampleListView, { global: { plugins: [pinia, ElementPlus] } })
  wrappers.push(wrapper)
  return wrapper
}

beforeEach(() => {
  vi.resetAllMocks()
  api.query = {}
  api.options.mockResolvedValue({ statuses: [], sample_types: [], owners: [] })
  api.stats.mockResolvedValue({ all: 1, pending_completion: 0, pending_payment: 0, pending_pmc: 1, pending_metalwork: 0, pending_cutting: 0, finished: 0 })
})
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()) })

describe('打样申请列表', () => {
  it('快速搜索时仅接纳最新响应，并保留服务端状态含义', async () => {
    let resolveFirst: (value: unknown) => void = () => {}
    api.rows.mockImplementationOnce(() => new Promise(resolve => { resolveFirst = resolve }))
    api.rows.mockResolvedValueOnce(result('NEW-REQUEST'))
    const wrapper = render()
    await flushPromises()
    const search = wrapper.find('.search-input input')
    await search.setValue('  NEW  ')
    await search.trigger('keydown.enter')
    await flushPromises()
    expect(api.rows).toHaveBeenLastCalledWith(expect.objectContaining({ search: 'NEW', page: 1 }))
    resolveFirst(result('STALE-REQUEST'))
    await flushPromises()
    expect(wrapper.text()).toContain('NEW-REQUEST')
    expect(wrapper.text()).not.toContain('STALE-REQUEST')
    expect(wrapper.text()).toContain('PMC待审核')
    expect(wrapper.find('.sample-table').text()).not.toContain('待厂长确认')
  })

  it('权限拒绝提供错误与重试，不显示新建或假数据', async () => {
    api.rows.mockRejectedValueOnce(new AxiosError('Forbidden', '403', undefined, undefined, { status: 403, data: {} } as never))
    api.rows.mockResolvedValueOnce({ data: [], meta: { total: 0 } })
    const wrapper = render()
    await flushPromises()
    expect(wrapper.find('[role="alert"]').text()).toContain('没有执行该样品操作的权限')
    expect(wrapper.find('.create-button').exists()).toBe(false)
    await wrapper.find('[role="alert"] button').trigger('click')
    await flushPromises()
    expect(api.rows).toHaveBeenCalledTimes(2)
    expect(wrapper.text()).toContain('暂无打样申请')
  })

  it('移除快捷统计条及请求，保留业务状态筛选', async () => {
    api.rows.mockResolvedValue(result('REAL'))
    const wrapper = render()
    await flushPromises()
    expect(wrapper.find('.quick-views').exists()).toBe(false)
    expect(api.stats).not.toHaveBeenCalled()
    const status = wrapper.findAllComponents(ElSelect).find(component => component.classes().includes('status-filter'))!
    for (const value of ['DIRECTOR_REVIEW', 'WAREHOUSE_PENDING', 'PROCUREMENT_PENDING']) {
      status.vm.$emit('update:modelValue', value)
      status.vm.$emit('change', value)
      await flushPromises()
      expect(api.rows).toHaveBeenLastCalledWith(expect.objectContaining({ status: value, page: 1 }))
    }
  })

  it('中文输入法确认不触发搜索，普通回车只提交一次', async () => {
    api.rows.mockResolvedValue(result('REAL'))
    const wrapper = render()
    await flushPromises()
    api.rows.mockClear()
    const input = wrapper.get('.search-input input')
    await input.setValue('  桌子  ')
    await input.trigger('keydown', { key: 'Enter', isComposing: true })
    await input.trigger('keydown', { key: 'Enter', keyCode: 229 })
    await input.trigger('keyup', { key: 'Enter', isComposing: true })
    await flushPromises()
    expect(api.rows).not.toHaveBeenCalled()
    await input.trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(api.rows).toHaveBeenCalledTimes(1)
    expect(api.rows).toHaveBeenLastCalledWith(expect.objectContaining({ page: 1, search: '桌子' }))
  })

  it('放大镜及清空搜索回到第一页并保留客户和状态上下文', async () => {
    api.query = { customer_id: 'customer-1', status: 'DIRECTOR_REVIEW' }
    api.rows.mockResolvedValue({ ...result('REAL'), meta: { total: 100 } })
    const wrapper = render()
    await flushPromises()
    const pager = wrapper.findComponent(ElPagination)
    pager.vm.$emit('update:current-page', 2)
    await wrapper.get('.search-input input').setValue('  桌子  ')
    api.rows.mockClear()
    await wrapper.get('button[aria-label="搜索打样申请列表"]').trigger('click')
    await flushPromises()
    expect(api.rows).toHaveBeenCalledTimes(1)
    expect(api.rows).toHaveBeenLastCalledWith(expect.objectContaining({ page: 1, search: '桌子', customer_id: 'customer-1', status: 'DIRECTOR_REVIEW' }))
    pager.vm.$emit('update:current-page', 2)
    await wrapper.get('.search-input').trigger('mouseenter')
    api.rows.mockClear()
    await wrapper.get('.el-input__clear').trigger('click')
    await flushPromises()
    expect(api.rows).toHaveBeenCalledTimes(1)
    expect(api.rows).toHaveBeenLastCalledWith(expect.objectContaining({ page: 1, customer_id: 'customer-1', status: 'DIRECTOR_REVIEW' }))
    expect(api.rows.mock.lastCall![0]).not.toHaveProperty('search')
  })
})


describe('打样列表筛选和操作边界', () => {
  it('移除批量与视图工具栏、选择框，并使用申请打样按钮', async () => {
    api.rows.mockResolvedValue(result('REAL'))
    const wrapper = render('employee', ['samples.add_samplerequest'])
    await flushPromises()
    expect(wrapper.find('.table-toolbar').exists()).toBe(false)
    expect(wrapper.findAll('.el-checkbox')).toHaveLength(0)
    expect(wrapper.find('.create-button').text()).toBe('申请打样')
    expect(wrapper.find('.erp-list-toolbar .sample-actions .create-button').exists()).toBe(true)
  })

  it('日期筛选发送完整自然日；重置删除日期条件', async () => {
    api.rows.mockResolvedValue(result('REAL'))
    const wrapper = render()
    await flushPromises()
    await wrapper.find('.more-filters').trigger('click')
    wrapper.findComponent(ElDatePicker).vm.$emit('update:modelValue', [new Date(2026, 8, 1), new Date(2026, 8, 10)])
    await wrapper.find('.filters form').trigger('submit')
    await flushPromises()
    const query = api.rows.mock.lastCall![0]
    expect(new Date(query.requested_from)).toEqual(new Date(2026, 8, 1, 0, 0, 0, 0))
    expect(new Date(query.requested_to)).toEqual(new Date(2026, 8, 10, 23, 59, 59, 999))
    await wrapper.find('.reset-button').trigger('click')
    await flushPromises()
    expect(api.rows.mock.lastCall![0]).not.toHaveProperty('requested_from')
    expect(api.rows.mock.lastCall![0]).not.toHaveProperty('requested_to')
  })

  it('状态、类型、业务员和分页提交真实查询；筛选时回第一页', async () => {
    api.rows.mockResolvedValue({ ...result('REAL'), meta: { total: 80 } })
    const wrapper = render()
    await flushPromises()
    for (const [selector, value] of [['.status-filter', 'PMC_REVIEW'], ['.type-filter', 'PRE_SALES'], ['.owner-filter', 'owner-a']]) {
      const control = wrapper.findAllComponents(ElSelect).find(component => component.classes().includes(selector!.slice(1)))!
      control.vm.$emit('update:modelValue', value)
      control.vm.$emit('change', value)
      await flushPromises()
    }
    expect(api.rows.mock.lastCall![0]).toMatchObject({ status: 'PMC_REVIEW', sample_type: 'PRE_SALES', owner_employee_id: 'owner-a', page: 1 })
    const pager = wrapper.findComponent(ElPagination)
    pager.vm.$emit('update:current-page', 2)
    pager.vm.$emit('current-change', 2)
    await flushPromises()
    expect(api.rows.mock.lastCall![0].page).toBe(2)
    await wrapper.find('.search-input input').setValue('客户')
    await wrapper.find('.search-input input').trigger('keydown.enter')
    await flushPromises()
    expect(api.rows.mock.lastCall![0]).toMatchObject({ search: '客户', page: 1 })
  })

  it('查看和申请打样使用既有路由，不从列表伪造业务状态迁移', async () => {
    api.rows.mockResolvedValue(result('REAL'))
    const wrapper = render('employee', ['samples.add_samplerequest'])
    await flushPromises()
    await wrapper.find('.sample-link').trigger('click')
    expect(api.push).toHaveBeenLastCalledWith({ name: 'sample-detail', params: { sampleId: 'REAL' } })
    await wrapper.find('.create-button').trigger('click')
    expect(api.push).toHaveBeenLastCalledWith({ name: 'sample-new' })
  })
})

it('新版生产阶段查看进入详情，更多保留固定用料入口', async () => {
  const data = result('NEW-PRODUCTION')
  api.rows.mockResolvedValue({ ...data, data: [{ ...data.data[0], status: 'PRODUCTION_PENDING', application_actions: { is_application: true } }] })
  const wrapper = render()
  await flushPromises()
  await wrapper.find('.row-actions button').trigger('click')
  await vi.waitFor(() => expect(wrapper.findAllComponents({ name: 'ElDropdownItem' }).filter(item => item.text() === '查看')).toHaveLength(1))
  wrapper.findAllComponents({ name: 'ElDropdownItem' }).find(item => item.text() === '查看')!.vm.$emit('click')
  await flushPromises()
  expect(api.push).toHaveBeenCalledWith({ name: 'sample-detail', params: { sampleId: 'NEW-PRODUCTION' } })
  expect(wrapper.findAllComponents({ name: 'ElDropdownItem' }).filter(item => item.text() === '查看用料需求')).toHaveLength(1)
})

it('新版申请尚未完善需求时开放编辑入口', async () => {
  const data = result('WAITING-REQUIREMENTS')
  api.rows.mockResolvedValue({ ...data, data: [{
    ...data.data[0],
    status: 'MATERIALS_PENDING',
    application_actions: { is_application: true, can_resubmit: false },
    edit_capabilities: { mode: 'COMPLETE', can_full_edit: true, can_report_edit: true, can_complete: true, can_cancel: false },
  }] })
  const wrapper = render('employee', ['samples.complete_sample_requirements'])
  await flushPromises()
  await wrapper.find('.row-actions button').trigger('click')
  await vi.waitFor(() => expect(wrapper.findAllComponents({ name: 'ElDropdownItem' }).some(item => item.text() === '编辑需求')).toBe(true))
  const edit = wrapper.findAllComponents({ name: 'ElDropdownItem' }).find(item => item.text() === '编辑需求')!
  expect(edit.props('disabled')).toBe(false)
  edit.vm.$emit('click')
  await flushPromises()
  expect(api.push).toHaveBeenCalledWith({ name: 'sample-detail', params: { sampleId: 'WAITING-REQUIREMENTS' } })
})
