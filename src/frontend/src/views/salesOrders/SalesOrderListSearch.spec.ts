import { flushPromises, shallowMount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '@/api/salesOrders'
import SalesOrderListView from './SalesOrderListView.vue'

vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: () => true, canFor: () => true, user: {} }) }))
vi.mock('@/api/salesOrders', () => ({ fetchSalesOrders: vi.fn(), fetchSalesOrderOptions: vi.fn() }))

const wrappers: ReturnType<typeof shallowMount>[] = []
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()) })

describe('销售订单列表搜索', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(api.fetchSalesOrders).mockResolvedValue({ data: [], meta: { total: 150, total_pages: 3, page: 2, page_size: 50 } })
    vi.mocked(api.fetchSalesOrderOptions).mockResolvedValue({
      statuses: [], source_types: [], confirmation_methods: [], customers: [], transaction_entities: [],
      buyer_addresses: [], employees: [], products: [], currencies: [], accepted_quotation_versions: [], seller_template: null,
    })
  })

  async function renderSecondPage(keyword = '') {
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/', component: { template: '<div />' } }] })
    await router.push('/')
    await router.isReady()
    const wrapper = shallowMount(SalesOrderListView, { global: { plugins: [ElementPlus, router], stubs: { ElInput: false } } })
    wrappers.push(wrapper)
    await flushPromises()
    wrapper.findAllComponents({ name: 'ElSelect' }).find(item => item.classes().includes('filter-control--status'))!.vm.$emit('update:modelValue', 'CONFIRMED')
    wrapper.findAllComponents({ name: 'ElSelect' }).find(item => item.classes().includes('filter-control--source'))!.vm.$emit('update:modelValue', 'QUOTATION')
    wrapper.getComponent({ name: 'ElPagination' }).vm.$emit('update:currentPage', 2)
    await wrapper.get('input').setValue(keyword)
    wrapper.getComponent({ name: 'ElPagination' }).vm.$emit('change')
    await flushPromises()
    expect(api.fetchSalesOrders).toHaveBeenLastCalledWith(expect.objectContaining({ page: 2, status: 'CONFIRMED', source_type: 'QUOTATION' }))
    vi.mocked(api.fetchSalesOrders).mockClear()
    return wrapper
  }

  it('回车搜索去除空白并返回第一页，中文输入法确认不触发查询', async () => {
    const wrapper = await renderSecondPage()
    const input = wrapper.get('input')
    await input.setValue('  阿尔法  ')
    await input.trigger('keydown', { key: 'Enter', isComposing: true })
    await input.trigger('keydown', { key: 'Enter', keyCode: 229 })
    await flushPromises()
    expect(api.fetchSalesOrders).not.toHaveBeenCalled()

    const enter = new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true })
    input.element.dispatchEvent(enter)
    await flushPromises()
    expect(enter.defaultPrevented).toBe(true)
    expect(api.fetchSalesOrders).toHaveBeenCalledTimes(1)
    expect(api.fetchSalesOrders).toHaveBeenLastCalledWith(expect.objectContaining({ q: '阿尔法', page: 1, status: 'CONFIRMED', source_type: 'QUOTATION' }))
  })

  it('点击放大镜搜索返回第一页并保留状态及来源筛选', async () => {
    const wrapper = await renderSecondPage()
    await wrapper.get('input').setValue('  SO-2026  ')
    await wrapper.get('button[aria-label="搜索销售订单列表"]').trigger('click')
    await flushPromises()
    expect(api.fetchSalesOrders).toHaveBeenCalledTimes(1)
    expect(api.fetchSalesOrders).toHaveBeenLastCalledWith(expect.objectContaining({ q: 'SO-2026', page: 1, status: 'CONFIRMED', source_type: 'QUOTATION' }))
  })

  it('清空关键词立即刷新第一页并保留状态及来源筛选', async () => {
    const wrapper = await renderSecondPage('Alpha')
    await wrapper.get('.filter-control--search').trigger('mouseenter')
    await wrapper.get('.el-input__clear').trigger('click')
    await flushPromises()
    expect(api.fetchSalesOrders).toHaveBeenCalledTimes(1)
    expect(api.fetchSalesOrders).toHaveBeenLastCalledWith(expect.objectContaining({ q: undefined, page: 1, status: 'CONFIRMED', source_type: 'QUOTATION' }))
  })
})
