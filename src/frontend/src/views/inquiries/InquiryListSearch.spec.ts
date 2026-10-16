import { flushPromises, shallowMount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ElementPlus from 'element-plus'
import * as api from '@/api/inquiries'
import { fetchPublishedOptions } from '@/api/referenceData'
import InquiryListView from './InquiryListView.vue'

vi.mock('vue-router', async original => ({
  ...await original<typeof import('vue-router')>(),
  onBeforeRouteLeave: vi.fn(), onBeforeRouteUpdate: vi.fn(),
}))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: () => true, canFor: () => true, user: { employee: { id: 'employee' } } }) }))
vi.mock('@/api/inquiries', async original => ({
  ...await original<typeof import('@/api/inquiries')>(),
  fetchInquiries: vi.fn(), fetchInquiryBoard: vi.fn(), fetchInquiryOptions: vi.fn(),
}))
vi.mock('@/api/referenceData', async original => ({ ...await original<typeof import('@/api/referenceData')>(), fetchPublishedOptions: vi.fn() }))
vi.mock('@/components/inquiries/InquiryActionDialog.vue', () => ({ default: { template: '<div />' } }))
vi.mock('@/components/common/AppWindowDialog.vue', () => ({ default: { template: '<div />' } }))
vi.mock('@/components/quotations/QuotationFromInquiryDialog.vue', () => ({ default: { template: '<div />' } }))

const wrappers: ReturnType<typeof shallowMount>[] = []
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()) })

describe('询盘列表搜索', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(api.fetchInquiries).mockResolvedValue({ data: [], meta: { total: 100, total_pages: 2, page: 2, page_size: 50 } })
    vi.mocked(api.fetchInquiryBoard).mockResolvedValue({ read_only: true, lanes: [] })
    vi.mocked(api.fetchInquiryOptions).mockResolvedValue({ statuses: [], sources: [], owners: [], countries: ['DE'], invalid_reason_codes: [] })
    vi.mocked(fetchPublishedOptions).mockResolvedValue({ data: [], meta: { config_version: null } })
  })

  async function renderSecondPage(keyword = '') {
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/inquiries', component: { template: '<div />' } }] })
    await router.push({ path: '/inquiries', query: { page: '2', country_code: 'DE', ...(keyword ? { q: keyword } : {}) } })
    await router.isReady()
    const wrapper = shallowMount(InquiryListView, { global: { plugins: [createPinia(), ElementPlus, router], stubs: { ElInput: false } } })
    wrappers.push(wrapper)
    await flushPromises()
    expect(api.fetchInquiries).toHaveBeenLastCalledWith(expect.objectContaining({ page: 2, country_code: 'DE' }))
    vi.mocked(api.fetchInquiries).mockClear()
    return wrapper
  }

  it('回车搜索去除空白并返回第一页，中文组合输入期间忽略回车', async () => {
    const wrapper = await renderSecondPage()
    const input = wrapper.get('input[aria-label="搜索询盘"]')
    await input.setValue('  阿尔法  ')
    await input.trigger('keydown', { key: 'Enter', isComposing: true })
    await flushPromises()
    expect(api.fetchInquiries).not.toHaveBeenCalled()

    const enter = new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true })
    input.element.dispatchEvent(enter)
    await flushPromises()
    expect(enter.defaultPrevented).toBe(true)
    expect(api.fetchInquiries).toHaveBeenCalledTimes(1)
    expect(api.fetchInquiries).toHaveBeenLastCalledWith(expect.objectContaining({ q: '阿尔法', page: 1, country_code: 'DE' }))
  })

  it('点击搜索图标按去除空白的关键词查询，返回第一页并保留国家筛选', async () => {
    const wrapper = await renderSecondPage()
    await wrapper.get('input[aria-label="搜索询盘"]').setValue('  Alpha  ')
    const button = wrapper.get('button[aria-label="搜索询盘列表"]')
    expect(button.attributes('type')).toBe('button')
    await button.trigger('click')
    await flushPromises()
    expect(api.fetchInquiries).toHaveBeenCalledTimes(1)
    expect(api.fetchInquiries).toHaveBeenLastCalledWith(expect.objectContaining({ q: 'Alpha', page: 1, country_code: 'DE' }))
  })

  it('清空关键词立即刷新第一页并保留国家筛选', async () => {
    const wrapper = await renderSecondPage('Alpha')
    await wrapper.get('.search-filter').trigger('mouseenter')
    await wrapper.get('.el-input__clear').trigger('click')
    await flushPromises()
    expect(api.fetchInquiries).toHaveBeenCalledTimes(1)
    const query = vi.mocked(api.fetchInquiries).mock.calls[0]?.[0]
    expect(query).toEqual(expect.objectContaining({ page: 1, country_code: 'DE' }))
    expect(query).not.toHaveProperty('q')
  })
})
