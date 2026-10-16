import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { AxiosError, AxiosHeaders } from 'axios'
import ElementPlus, { ElInput, ElMessage, ElPagination, type SelectInstance } from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { exportCustomers, fetchCustomerOptions, fetchCustomers } from '@/api/customers'
import { fetchPublishedOptions } from '@/api/referenceData'
import CrmPageHeader from '@/components/crm/CrmPageHeader.vue'
import { useAuthStore } from '@/stores/auth'
import type { CustomerOptions } from '@/types/customer'
import CustomerListView from './CustomerListView.vue'

vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }) }))
vi.mock('@/api/customers', async importOriginal => ({
  ...await importOriginal<typeof import('@/api/customers')>(),
  fetchCustomerOptions: vi.fn(), fetchCustomers: vi.fn(), exportCustomers: vi.fn(),
}))
vi.mock('@/api/referenceData', async importOriginal => ({
  ...await importOriginal<typeof import('@/api/referenceData')>(), fetchPublishedOptions: vi.fn(),
}))

const options: CustomerOptions = {
  lifecycle_stages: [],
  activity_statuses: [{ item_code: 'ACTIVE', display_name: '活跃' }, { item_code: 'HIGH_RISK', display_name: '高风险' }],
  customer_grades: [
    { id: 'grade-a', item_code: 'A', display_name: 'A级', description: '' },
    { id: 'grade-b', item_code: 'B', display_name: 'B级', description: '' },
  ],
  country_options: [
    { id: 'country-de', item_code: 'DE', display_name: '德国', description: '' },
    { id: 'country-us', item_code: 'US', display_name: '美国', description: '' },
  ],
  customer_types: [], customer_sources: [], industries: [], interested_products: [],
  primary_regions: [], secondary_regions: [], customer_tags: [], owner_options: [],
}
const wrappers: ReturnType<typeof mount>[] = []

beforeEach(() => {
  vi.mocked(fetchCustomerOptions).mockReset().mockResolvedValue(options)
  vi.mocked(fetchCustomers).mockReset().mockResolvedValue({
    data: [], meta: { page: 1, page_size: 50, total: 150, total_pages: 3 },
  })
  vi.mocked(exportCustomers).mockReset().mockResolvedValue(new Blob(['客户名称\nAlpha'], { type: 'text/csv' }))
  vi.mocked(fetchPublishedOptions).mockReset().mockResolvedValue({ data: [], meta: { config_version: null } })
  vi.spyOn(ElMessage, 'error').mockImplementation(() => ({ close: vi.fn() }))
  vi.spyOn(ElMessage, 'success').mockImplementation(() => ({ close: vi.fn() }))
})

afterEach(() => {
  wrappers.splice(0).forEach(wrapper => wrapper.unmount())
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

async function renderPage() {
  const pinia = createPinia()
  useAuthStore(pinia).user = {
    id: 1, username: 'filter-test', display_name: '筛选测试', is_superuser: true,
    employee: null, permissions: [], data_scope: 'ALL',
  }
  const wrapper = mount(CustomerListView, { global: { plugins: [pinia, ElementPlus] } })
  wrappers.push(wrapper)
  await flushPromises()
  return wrapper
}

async function setSelect(wrapper: ReturnType<typeof mount>, label: string, value: string) {
  const select = wrapper.findAllComponents({ name: 'ElSelect' }).find(item => item.props('ariaLabel') === label)
  if (!select) throw new Error(`没有找到筛选条件：${label}`)
  select.vm.$emit('update:modelValue', value)
  select.vm.$emit('change', value)
  await flushPromises()
}

async function changePage(wrapper: ReturnType<typeof mount>, page: number) {
  const pagination = wrapper.getComponent(ElPagination)
  pagination.vm.$emit('update:current-page', page)
  pagination.vm.$emit('current-change', page)
  await flushPromises()
}

async function fillFilters(wrapper: ReturnType<typeof mount>) {
  await wrapper.get('.filter-control--search input').setValue('  Alpha  ')
  await setSelect(wrapper, '客户状态', 'ACTIVE')
  await setSelect(wrapper, '客户等级', 'A')
  await setSelect(wrapper, '国家或地区', 'DE')
}

describe('客户列表常用筛选与已应用条件', () => {
  it('筛选卡仅保留四个条件，表格卡顶部放新建和导出，并保留业务列顺序', async () => {
    const wrapper = await renderPage()
    const panel = wrapper.get('.filter-panel')
    expect(panel.getComponent(CrmPageHeader).props('title')).toBe('客户列表')
    const form = panel.get('form')
    expect(form.findComponent(ElInput).exists()).toBe(true)
    expect(form.findAllComponents({ name: 'ElSelect' }).map((item: VueWrapper<SelectInstance>) => item.props('ariaLabel')))
      .toEqual(['客户状态', '客户等级', '国家或地区'])
    expect(wrapper.find('.filter-more-button').exists()).toBe(false)
    expect(wrapper.find('.advanced-filter-grid').exists()).toBe(false)
    expect(wrapper.findAll('button').some(button => /更多筛选|高级筛选|导入/.test(button.text()))).toBe(false)
    const surface = wrapper.get('.data-surface')
    const toolbar = surface.get('[data-customer-toolbar]')
    const actions = toolbar.findAll('button').map(button => button.text())
    expect(actions.some(text => text.includes('新建客户'))).toBe(true)
    expect(actions.some(text => text.includes('导出'))).toBe(true)
    expect(surface.element.firstElementChild).toBe(toolbar.element)
    expect(wrapper.findAll('.el-table__header-wrapper th .cell').map(cell => cell.text())).toEqual([
      '客户名称', '国家/地区', '等级', '客户状态', '负责人', '近12个月销售额',
      '最近订单', '最近联系', '下次跟进', '跟进状态', '风险', '操作',
    ])
  })

  it('修改常用条件不发请求，统一应用时去除关键词空白并回到第一页', async () => {
    const wrapper = await renderPage()
    await changePage(wrapper, 2)
    vi.mocked(fetchCustomers).mockClear()
    await fillFilters(wrapper)
    expect(fetchCustomers).not.toHaveBeenCalled()
    await wrapper.get('[data-apply-customer-filters]').trigger('click')
    await flushPromises()
    expect(fetchCustomers).toHaveBeenCalledExactlyOnceWith({
      page: 1, page_size: 50, ordering: '-updated_at', q: 'Alpha',
      activity_status: 'ACTIVE', customer_grade: 'A', country_code: 'DE',
    })
  })

  it('分页和导出沿用已应用条件，不夹带尚未提交的筛选草稿', async () => {
    const wrapper = await renderPage()
    await fillFilters(wrapper)
    await wrapper.get('[data-apply-customer-filters]').trigger('click')
    await flushPromises()
    vi.mocked(fetchCustomers).mockClear()
    await wrapper.get('.filter-control--search input').setValue('未提交关键词')
    await setSelect(wrapper, '客户状态', 'HIGH_RISK')
    await setSelect(wrapper, '客户等级', 'B')
    await setSelect(wrapper, '国家或地区', 'US')
    expect(fetchCustomers).not.toHaveBeenCalled()
    await changePage(wrapper, 2)
    const appliedQuery = {
      page: 2, page_size: 50, ordering: '-updated_at', q: 'Alpha',
      activity_status: 'ACTIVE', customer_grade: 'A', country_code: 'DE',
    }
    expect(fetchCustomers).toHaveBeenCalledExactlyOnceWith(appliedQuery)

    const NativeURL = URL
    vi.stubGlobal('URL', class extends NativeURL {
      static createObjectURL() { return 'blob:customer-filter-export-test' }
      static revokeObjectURL() {}
    })
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    await wrapper.get('.filter-action--export').trigger('click')
    await flushPromises()
    expect(exportCustomers).toHaveBeenCalledExactlyOnceWith(appliedQuery)
  })

  it('重置清空草稿和已应用条件，并恢复默认排序与第一页', async () => {
    const wrapper = await renderPage()
    await fillFilters(wrapper)
    await wrapper.get('[data-apply-customer-filters]').trigger('click')
    await flushPromises()
    wrapper.getComponent({ name: 'ElTable' }).vm.$emit('sort-change', { prop: 'account_name', order: 'ascending' })
    await flushPromises()
    await changePage(wrapper, 2)
    expect(fetchCustomers).toHaveBeenLastCalledWith(expect.objectContaining({ page: 2, ordering: 'account_name' }))
    await setSelect(wrapper, '国家或地区', 'US')
    vi.mocked(fetchCustomers).mockClear()
    await wrapper.get('[data-reset-customer-filters]').trigger('click')
    await flushPromises()
    expect(fetchCustomers).toHaveBeenCalledExactlyOnceWith({ page: 1, page_size: 50, ordering: '-updated_at' })
    expect((wrapper.get('.filter-control--search input').element as HTMLInputElement).value).toBe('')
    expect(wrapper.get('.filter-panel').findAllComponents({ name: 'ElSelect' }).map((item: VueWrapper<SelectInstance>) => item.props('modelValue'))).toEqual(['', '', ''])
  })

  it.each([
    [403, '当前账号没有查看客户列表的权限。'],
    [500, '后端服务暂时异常，请稍后重试。'],
  ])('%s 请求失败显示对应错误，重新加载成功后恢复表格', async (status, message) => {
    const failure = new AxiosError('request failed')
    failure.response = { status: Number(status), statusText: 'error', data: {}, headers: {}, config: { headers: new AxiosHeaders() } }
    vi.mocked(fetchCustomers).mockRejectedValueOnce(failure)
    const wrapper = await renderPage()
    const alert = wrapper.get('[role="alert"]')
    expect(alert.text()).toContain(message)
    expect(wrapper.find('.el-table').exists()).toBe(false)
    await alert.get('button').trigger('click')
    await flushPromises()
    expect(fetchCustomers).toHaveBeenCalledTimes(2)
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    expect(wrapper.find('.el-table').exists()).toBe(true)
  })
})
