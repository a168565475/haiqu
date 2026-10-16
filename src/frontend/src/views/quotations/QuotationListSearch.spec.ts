import { flushPromises, shallowMount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ElementPlus from 'element-plus'
import * as api from '@/api/quotations'
import QuotationListView from './QuotationListView.vue'

vi.mock('vue-router', () => ({
  useRoute: () => ({ query: { customer_id: 'customer-1' } }),
  useRouter: () => ({ push: vi.fn() }),
}))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({
  hasPermission: () => true, canFor: () => true, user: null,
}) }))
vi.mock('@/api/quotations', async original => ({
  ...await original<typeof import('@/api/quotations')>(),
  fetchQuotations: vi.fn(), fetchQuotationOptions: vi.fn(),
}))

const wrappers: ReturnType<typeof shallowMount>[] = []
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()) })

describe('报价列表搜索', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(api.fetchQuotations).mockResolvedValue({ data: [], meta: { total: 100, total_pages: 5, page: 2, page_size: 20 } })
    vi.mocked(api.fetchQuotationOptions).mockResolvedValue({ outcome_statuses: [], display_statuses: [], currencies: [{ value: 'USD', label: 'USD' }], owners: [] })
  })

  async function renderSecondPage(keyword = '') {
    const wrapper = shallowMount(QuotationListView, { global: {
      plugins: [ElementPlus],
      stubs: { ElInput: false, ElForm: { template: '<form><slot /></form>' }, ElFormItem: { template: '<div><slot /></div>' }, ElCard: { template: '<div><slot /></div>' } },
    } })
    wrappers.push(wrapper)
    await flushPromises()
    await wrapper.get('input').setValue(keyword)
    const currency = wrapper.findAllComponents({ name: 'ElSelect' }).find(item => item.classes().includes('quotation-currency-filter'))!
    currency.vm.$emit('update:modelValue', 'USD')
    const pagination = wrapper.getComponent({ name: 'ElPagination' })
    pagination.vm.$emit('update:current-page', 2)
    pagination.vm.$emit('current-change', 2)
    await flushPromises()
    expect(api.fetchQuotations).toHaveBeenLastCalledWith(expect.objectContaining({ page: 2, currency_code: 'USD', customer_id: 'customer-1' }))
    vi.mocked(api.fetchQuotations).mockClear()
    return wrapper
  }

  it('回车搜索去除首尾空白、返回第一页并保留筛选，组合输入回车不搜索', async () => {
    const wrapper = await renderSecondPage()
    const input = wrapper.get('input')
    await input.setValue('  阿尔法  ')
    await input.trigger('keydown', { key: 'Enter', isComposing: true })
    await flushPromises()
    expect(api.fetchQuotations).not.toHaveBeenCalled()
    const enter = new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true })
    input.element.dispatchEvent(enter)
    await flushPromises()
    expect(enter.defaultPrevented).toBe(true)
    expect(api.fetchQuotations).toHaveBeenCalledTimes(1)
    expect(api.fetchQuotations).toHaveBeenLastCalledWith(expect.objectContaining({ q: '阿尔法', page: 1, currency_code: 'USD', customer_id: 'customer-1' }))
    expect(input.attributes('aria-label')).toBe('搜索报价')
  })

  it('放大镜按钮查询去除空白的关键词，保留币种与客户范围并返回第一页', async () => {
    const wrapper = await renderSecondPage()
    await wrapper.get('input').setValue('  Alpha  ')
    const button = wrapper.find('button[aria-label="搜索报价列表"]')
    expect(button.exists()).toBe(true)
    expect(button.attributes('type')).toBe('button')
    await button.trigger('click')
    await flushPromises()
    expect(api.fetchQuotations).toHaveBeenCalledTimes(1)
    expect(api.fetchQuotations).toHaveBeenLastCalledWith(expect.objectContaining({ q: 'Alpha', page: 1, currency_code: 'USD', customer_id: 'customer-1' }))
  })

  it('清空关键词立即查询第一页，保留币种与客户范围', async () => {
    const wrapper = await renderSecondPage('Alpha')
    await wrapper.get('.el-input').trigger('mouseenter')
    await wrapper.get('.el-input__clear').trigger('click')
    await flushPromises()
    expect(api.fetchQuotations).toHaveBeenCalledTimes(1)
    const query = vi.mocked(api.fetchQuotations).mock.calls[0]?.[0]
    expect(query).toEqual(expect.objectContaining({ page: 1, currency_code: 'USD', customer_id: 'customer-1' }))
    expect(query).not.toHaveProperty('q')
  })
})
