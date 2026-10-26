import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, ref } from 'vue'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import ComplaintListView from './ComplaintListView.vue'
import { pageInstanceKey } from '@/utils/pageInstanceKey'

const api = vi.hoisted(() => ({ rows: vi.fn(), stats: vi.fn(), options: vi.fn() }))
vi.mock('@/api/complaints', () => ({ fetchComplaints: api.rows, fetchComplaintStats: api.stats, fetchComplaintOptions: api.options }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: () => true }) }))
vi.mock('@/composables/useOptions', () => ({ useOptions: () => ({ options: ref([]), load: vi.fn().mockResolvedValue([]) }) }))
vi.mock('@/components/complaints/ComplaintCreateDialog.vue', () => ({ default: { template: '<div />' } }))
vi.mock('@/directives/glassSpotlight', () => ({ vGlassSpotlight: {} }))

const stubs = {
  ElButton: { template: '<button><slot /></button>' },
  ElInput: { props: ['modelValue'], emits: ['update:modelValue'], template: '<input :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)" />' },
  ElSelect: { template: '<select><slot /></select>' },
  ElOption: true, ElAlert: true, ElEmpty: true, ElTable: true, ElTableColumn: true,
  ElDropdown: { template: '<div><slot /></div>' }, ElDropdownMenu: true, ElDropdownItem: true,
  ElCheckbox: true, ElPagination: { props: ['currentPage', 'pageSize'], template: '<div />' },
}
let wrapper: VueWrapper | undefined

async function openPage(embedded = false) {
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/complaints', name: 'complaints', component: ComplaintListView },
  ] })
  await router.push('/complaints')
  await router.isReady()
  const root = defineComponent({
    components: { ComplaintListView },
    setup: () => ({ pageInstanceKey, embedded }),
    template: embedded
      ? '<ComplaintListView embedded customer-id="customer-1" />'
      : '<router-view v-slot="{ Component, route }"><component :is="Component" :key="pageInstanceKey(route, 1)" /></router-view>',
  })
  wrapper = mount(root, { global: { plugins: [router], stubs, directives: { loading: {} } } })
  await flushPromises()
  return router
}

async function click(text: string) {
  const button = wrapper!.findAll('button').find(item => item.text() === text)
  expect(button).toBeDefined()
  await button!.trigger('click')
  await flushPromises()
}

beforeEach(() => {
  vi.clearAllMocks()
  api.rows.mockResolvedValue({ data: [], meta: { total: 100 } })
  api.stats.mockResolvedValue({ by_type: [], by_owner: [], sla: { normal: 0, at_risk: 0, overdue: 0 }, closed: 0, cancelled: 0 })
  api.options.mockResolvedValue({ statuses: [], employees: [] })
})
afterEach(() => { wrapper?.unmount(); wrapper = undefined })

describe('客诉查询与页面实例', () => {
  it('应用筛选只加载一次列表和统计，保留分析面板状态且不重取选项', async () => {
    const router = await openPage()
    await click('收起分析')
    await wrapper!.get('input').setValue('质量')
    await click('应用筛选')
    expect(router.currentRoute.value.query.q).toBe('质量')
    expect(api.rows).toHaveBeenCalledTimes(2)
    expect(api.stats).toHaveBeenCalledTimes(2)
    expect(api.options).toHaveBeenCalledTimes(1)
    expect(wrapper!.text()).toContain('展开分析')
    expect(api.rows).toHaveBeenLastCalledWith({ page: 1, page_size: 50, q: '质量' })
  })

  it('外部查询和浏览器后退同步筛选与页码，仍保留同一页面实例', async () => {
    const router = await openPage()
    await router.push('/complaints?q=first&page=2&page_size=20')
    await flushPromises()
    await router.push('/complaints?q=second&page=3&page_size=100')
    await flushPromises()
    expect(wrapper!.get('input').element.value).toBe('second')
    router.back()
    await vi.waitFor(() => expect(router.currentRoute.value.query.q).toBe('first'))
    await flushPromises()
    expect(wrapper!.get('input').element.value).toBe('first')
    expect(api.rows).toHaveBeenLastCalledWith({ page: 2, page_size: 20, q: 'first' })
    expect(api.rows).toHaveBeenCalledTimes(4)
    expect(api.options).toHaveBeenCalledTimes(1)
  })

  it('相同筛选再次提交仍刷新一次，嵌入客户页不修改地址', async () => {
    const router = await openPage(true)
    await wrapper!.get('input').setValue('客户问题')
    await click('应用筛选')
    await click('应用筛选')
    expect(api.rows).toHaveBeenCalledTimes(3)
    expect(api.rows).toHaveBeenLastCalledWith({ page: 1, page_size: 50, customer_id: 'customer-1', q: '客户问题' })
    expect(router.currentRoute.value.fullPath).toBe('/complaints')
  })

  it('普通列表相同查询重复提交只刷新一次', async () => {
    await openPage()
    await click('应用筛选')
    await click('应用筛选')
    expect(api.rows).toHaveBeenCalledTimes(3)
    expect(api.options).toHaveBeenCalledTimes(1)
  })
})
