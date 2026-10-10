import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import ElementPlus, { ElDatePicker, ElSelect, ElPagination } from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AxiosError } from 'axios'
import SampleListView from './SampleListView.vue'
import { useAuthStore } from '@/stores/auth'

const api = vi.hoisted(() => ({ rows: vi.fn(), options: vi.fn(), stats: vi.fn(), push: vi.fn() }))
vi.mock('vue-router', () => ({ useRoute: () => ({ query: {} }), useRouter: () => ({ push: api.push }) }))
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
  vi.clearAllMocks()
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
    await search.trigger('keyup.enter')
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

  it('保留六个分类，厂长仓库采购筛选使用各自真实字段', async () => {
    api.rows.mockResolvedValue(result('REAL'))
    api.stats.mockResolvedValue({ all: 12, pending_director: 3, pending_payment: 8, pending_pmc: 7, pending_completion: 6 })
    const wrapper = render()
    await flushPromises()
    const tabs = wrapper.findAll('.quick-views button')
    expect(tabs).toHaveLength(6)
    expect(tabs.map(tab => tab.text())).toEqual(['全部申请 12', '我负责的 —', '待我处理 —', '待厂长确认 3', '待仓库核对 —', '等待采购 —'])
    expect(tabs[1]!.attributes('aria-disabled')).toBe('true')
    await tabs[4]!.trigger('click')
    expect(api.rows).toHaveBeenLastCalledWith(expect.objectContaining({ status: 'WAREHOUSE_PENDING', page: 1 }))
    expect(tabs[4]!.attributes('aria-pressed')).toBe('true')
    await tabs[5]!.trigger('click')
    expect(api.rows).toHaveBeenLastCalledWith(expect.objectContaining({ status: 'PROCUREMENT_PENDING', page: 1 }))
    await tabs[3]!.trigger('click')
    expect(api.rows).toHaveBeenLastCalledWith(expect.objectContaining({ status: 'DIRECTOR_REVIEW', page: 1 }))
  })

  it('我负责的使用当前员工的真实统计和 owner 筛选，全部申请清除 owner 条件', async () => {
    api.rows.mockResolvedValue(result('REAL'))
    api.stats.mockImplementation(query => Promise.resolve({ all: query?.owner_employee_id === 'employee-me' ? 2 : 12 }))
    const wrapper = render('employee-me')
    await flushPromises()
    expect(api.stats).toHaveBeenCalledWith({ owner_employee_id: 'employee-me' })
    const tabs = wrapper.findAll('.quick-views button')
    expect(tabs[1]!.text()).toBe('我负责的 2')
    await tabs[1]!.trigger('click')
    await flushPromises()
    expect(api.rows).toHaveBeenLastCalledWith(expect.objectContaining({ page: 1, owner_employee_id: 'employee-me' }))
    expect(tabs[1]!.attributes('aria-pressed')).toBe('true')
    await tabs[0]!.trigger('click')
    await flushPromises()
    expect(api.rows.mock.lastCall![0]).not.toHaveProperty('owner_employee_id')
  })

  it('统计失败仍保留快捷分类布局并显示未知，列表继续正常读取', async () => {
    api.rows.mockResolvedValue(result('REAL'))
    api.stats.mockRejectedValue(new Error('统计暂不可用'))
    const wrapper = render()
    await flushPromises()
    expect(wrapper.findAll('.quick-views button')).toHaveLength(6)
    expect(wrapper.find('.quick-views button').text()).toBe('全部申请 —')
    expect(wrapper.find('.sample-table').text()).toContain('REAL')
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
    await wrapper.find('.search-input input').trigger('keyup.enter')
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
