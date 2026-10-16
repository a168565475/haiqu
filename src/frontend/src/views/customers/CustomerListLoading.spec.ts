import { flushPromises, shallowMount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ElementPlus, { ElMessage } from 'element-plus'
import { fetchCustomerOptions, fetchCustomers } from '@/api/customers'
import { fetchPublishedOptions } from '@/api/referenceData'
import CustomerListView from './CustomerListView.vue'
import type { CustomerOptions } from '@/types/customer'

vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }) }))
vi.mock('@/api/customers', async importOriginal => ({
  ...await importOriginal<typeof import('@/api/customers')>(),
  fetchCustomerOptions: vi.fn(), fetchCustomers: vi.fn(),
}))
vi.mock('@/api/referenceData', async importOriginal => ({
  ...await importOriginal<typeof import('@/api/referenceData')>(), fetchPublishedOptions: vi.fn(),
}))

const legacy: CustomerOptions = {
  lifecycle_stages: [], activity_statuses: [], customer_grades: [], customer_types: [], customer_sources: [],
  industries: [], interested_products: [], primary_regions: [], secondary_regions: [], customer_tags: [], owner_options: [],
  country_options: [{ id: 'country-de', item_code: 'DE', display_name: '德国', description: '' }],
}
function renderPage() {
  return shallowMount(CustomerListView, { global: {
    plugins: [ElementPlus],
    stubs: {
      ElInput: false,
      ElSelect: {
        props: ['modelValue'],
        emits: ['update:modelValue', 'change'],
        template: '<select :value="modelValue" @change="$emit(\'update:modelValue\', $event.target.value); $emit(\'change\', $event.target.value)"><slot /></select>',
      },
      ElOption: { props: ['label', 'value'], template: '<option :value="value">{{ label }}</option>' },
    },
  } })
}

describe('客户列表初始化加载', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.mocked(fetchCustomerOptions).mockReset().mockResolvedValue(legacy)
    vi.mocked(fetchCustomers).mockReset().mockResolvedValue({ data: [], meta: { page: 1, page_size: 50, total: 0, total_pages: 0 } })
    vi.mocked(fetchPublishedOptions).mockReset().mockResolvedValue({ data: [], meta: { config_version: null } })
    vi.spyOn(ElMessage, 'warning').mockImplementation(() => ({ close: vi.fn() }))
    vi.spyOn(ElMessage, 'error').mockImplementation(() => ({ close: vi.fn() }))
  })

  async function renderCountryFilteredSecondPage(keyword = '') {
    const wrapper = renderPage()
    await flushPromises()
    await wrapper.get('.filter-control--search input').setValue(keyword)
    await wrapper.get('select[aria-label="国家或地区"]').setValue('DE')
    await wrapper.get('[data-apply-customer-filters]').trigger('click')
    await flushPromises()
    const pagination = wrapper.getComponent({ name: 'ElPagination' })
    pagination.vm.$emit('update:current-page', 2)
    pagination.vm.$emit('current-change', 2)
    await flushPromises()
    expect(fetchCustomers).toHaveBeenLastCalledWith(expect.objectContaining({ page: 2, country_code: 'DE' }))
    vi.mocked(fetchCustomers).mockClear()
    return wrapper
  }

  it('回车搜索去除关键词首尾空白、返回第一页，并忽略中文组合输入期间的回车', async () => {
    const wrapper = await renderCountryFilteredSecondPage()
    const input = wrapper.get('.filter-control--search input')
    await input.setValue('  阿尔法  ')
    await input.trigger('keydown', { key: 'Enter', isComposing: true })
    await flushPromises()
    expect(fetchCustomers).not.toHaveBeenCalled()

    await input.trigger('keydown', { key: 'Enter', isComposing: false })
    await flushPromises()
    expect(fetchCustomers).toHaveBeenCalledTimes(1)
    expect(fetchCustomers).toHaveBeenLastCalledWith(expect.objectContaining({ q: '阿尔法', page: 1, country_code: 'DE' }))
    wrapper.unmount()
  })

  it('点击放大镜按钮按关键词搜索，返回第一页并保留国家筛选', async () => {
    const wrapper = await renderCountryFilteredSecondPage()
    await wrapper.get('.filter-control--search input').setValue('  Alpha  ')
    await wrapper.get('button[aria-label="搜索客户"]').trigger('click')
    await flushPromises()
    expect(fetchCustomers).toHaveBeenCalledTimes(1)
    expect(fetchCustomers).toHaveBeenLastCalledWith(expect.objectContaining({ q: 'Alpha', page: 1, country_code: 'DE' }))
    wrapper.unmount()
  })

  it('清空关键词立即刷新第一页，并保留国家筛选', async () => {
    const wrapper = await renderCountryFilteredSecondPage('Alpha')
    await wrapper.get('.filter-control--search').trigger('mouseenter')
    await wrapper.get('.el-input__clear').trigger('click')
    await flushPromises()
    expect(fetchCustomers).toHaveBeenCalledTimes(1)
    const query = vi.mocked(fetchCustomers).mock.calls[0]?.[0]
    expect(query).toEqual(expect.objectContaining({ page: 1, country_code: 'DE' }))
    expect(query).not.toHaveProperty('q')
    wrapper.unmount()
  })

  it('兼容选项尚未返回时，字典与列表请求已经并行开始', async () => {
    let resolveOptions!: (value: CustomerOptions) => void
    vi.mocked(fetchCustomerOptions).mockReturnValue(new Promise(resolve => { resolveOptions = resolve }))
    const wrapper = renderPage()
    expect(fetchPublishedOptions).toHaveBeenCalledWith('CUSTOMER_GRADE', undefined)
    expect(fetchCustomers).toHaveBeenCalledTimes(1)
    resolveOptions(legacy)
    await flushPromises()
    expect(wrapper.find('option[value="DE"]').text()).toBe('德国（DE）')
    wrapper.unmount()
  })

  it('统一字典失败时保留兼容筛选项，列表仍可加载', async () => {
    vi.mocked(fetchPublishedOptions).mockRejectedValue(new Error('连接失败'))
    const wrapper = renderPage()
    await flushPromises()
    expect(wrapper.find('option[value="DE"]').exists()).toBe(true)
    expect(ElMessage.warning).toHaveBeenCalledWith(expect.stringContaining('回退到兼容选项'))
    expect(fetchCustomers).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })

  it('有发布版本时展示统一字典，同时保留国家等兼容选项', async () => {
    vi.mocked(fetchPublishedOptions).mockResolvedValue({
      data: [{ id: 'published-a', code: 'A', label: '发布等级', english_label: '', status: 'ACTIVE', sort_order: 1, color: '', extra: {} }],
      meta: { config_version: 7 },
    })
    const wrapper = renderPage()
    await flushPromises()
    expect(wrapper.find('option[value="A"]').exists()).toBe(true)
    expect(wrapper.find('option[value="DE"]').exists()).toBe(true)
    wrapper.unmount()
  })

  it('兼容选项失败时反馈错误，不阻止客户列表请求', async () => {
    vi.mocked(fetchCustomerOptions).mockRejectedValue(new Error('连接失败'))
    const wrapper = renderPage()
    await flushPromises()
    expect(ElMessage.error).toHaveBeenCalledWith(expect.stringContaining('筛选选项加载失败'))
    expect(fetchCustomers).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })
})
