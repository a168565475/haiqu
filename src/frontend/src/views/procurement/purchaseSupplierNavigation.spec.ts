import { flushPromises, mount, shallowMount, RouterLinkStub } from '@vue/test-utils'
import { createPinia } from 'pinia'
import ElementPlus, { ElSelect } from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import AppSidebar from '@/components/navigation/AppSidebar.vue'
import { useAuthStore } from '@/stores/auth'
import PurchaseOrderListView from './PurchaseOrderListView.vue'

const mocks = vi.hoisted(() => ({
  push: vi.fn(),
  list: vi.fn(),
  stats: vi.fn(),
  options: vi.fn(),
  remove: vi.fn(),
  detail: vi.fn(),
  complete: vi.fn(),
}))

vi.mock('vue-router', async (importOriginal) => ({
  ...await importOriginal<typeof import('vue-router')>(),
  useRouter: () => ({ push: mocks.push }),
  useRoute: () => ({ meta: { activeMenu: 'purchase-orders' } }),
}))

vi.mock('@/api/purchaseOrders', () => ({
  fetchPurchaseOrders: mocks.list,
  fetchPurchaseOrderStats: mocks.stats,
  fetchPurchaseOrderFilterOptions: mocks.options,
  deletePurchaseOrder: mocks.remove,
  fetchVersionedPurchaseOrder: mocks.detail,
  completePurchaseOrder: mocks.complete,
}))

const mounted: Array<{ unmount: () => void }> = []

function mountNavigation(permissions: string[], superuser = false) {
  const pinia = createPinia()
  useAuthStore(pinia).user = {
    id: 1, username: 'navigation-test', display_name: '导航测试',
    is_superuser: superuser, employee: null, permissions, data_scope: 'ALL',
  }
  const sidebar = shallowMount(AppSidebar, {
    global: { plugins: [pinia], stubs: { RouterLink: RouterLinkStub } },
  })
  const page = shallowMount(PurchaseOrderListView, {
    global: {
      plugins: [pinia, ElementPlus],
      stubs: { ElButton: { template: '<button><slot /></button>' } },
    },
  })
  mounted.push(sidebar, page)
  return { sidebar, page }
}

describe('采购订单中的供应商入口与权限边界', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.list.mockResolvedValue({ data: [], meta: { total: 0, total_pages: 0 } })
    mocks.stats.mockResolvedValue({ total: 0, draft: 0, submitted: 0, completed: 0, mailed: 0, unmailed: 0, mailing_pending: 0, amounts: [] })
    mocks.options.mockResolvedValue({ production_tasks: [], suppliers: [], currencies: [], default_currency_id: null })
    mocks.push.mockResolvedValue(undefined)
  })

  afterEach(() => {
    mounted.splice(0).forEach((wrapper) => wrapper.unmount())
  })

  it.each([
    { label: '仅供应商权限', permissions: ['procurement.view_supplier'], superuser: false, purchase: false, supplier: true },
    { label: '仅采购查看权限', permissions: ['procurement.view_purchaseorder'], superuser: false, purchase: true, supplier: false },
    { label: '两种查看权限', permissions: ['procurement.view_purchaseorder', 'procurement.view_supplier'], superuser: false, purchase: true, supplier: true },
    { label: '无查看权限', permissions: [], superuser: false, purchase: false, supplier: false },
    { label: '管理员', permissions: [], superuser: true, purchase: true, supplier: true },
  ])('$label：入口可见性和采购请求各自遵循权限', async ({ permissions, superuser, purchase, supplier }) => {
    const { sidebar, page } = mountNavigation(permissions, superuser)
    await flushPromises()

    const procurementGroup = sidebar.find('[data-menu-key="procurement-management"]')
    expect(procurementGroup.exists()).toBe(purchase || supplier)
    if (purchase || supplier) {
      await procurementGroup.trigger('focus')
      expect(procurementGroup.attributes('aria-expanded')).toBe('true')
    }

    expect(sidebar.text()).not.toContain('供应商')
    const purchaseLink = sidebar.findAllComponents(RouterLinkStub)
      .find((link) => {
        const target = link.props('to')
        return typeof target === 'object' && target?.name === 'purchase-orders'
      })
    expect(Boolean(purchaseLink)).toBe(purchase || supplier)
    expect(page.find('[data-testid="purchase-suppliers-entry"]').exists()).toBe(supplier)
    expect(page.text().includes('无权查看采购订单')).toBe(!purchase)
    expect(mocks.list).toHaveBeenCalledTimes(purchase ? 1 : 0)
    expect(mocks.stats).toHaveBeenCalledTimes(purchase ? 1 : 0)
    expect(mocks.options).toHaveBeenCalledTimes(purchase ? 1 : 0)
  })

  it('仅有供应商权限时，可以从页头进入完整供应商路由', async () => {
    const { page } = mountNavigation(['procurement.view_supplier'])
    await page.get('[data-testid="purchase-suppliers-entry"]').trigger('click')

    expect(mocks.push).toHaveBeenCalledWith({ name: 'suppliers' })
    expect(mocks.list).not.toHaveBeenCalled()
    expect(mocks.stats).not.toHaveBeenCalled()
    expect(mocks.remove).not.toHaveBeenCalled()
  })

  it('状态标签筛选真实采购状态，更新时间排序切换发送对应参数', async () => {
    const { page } = mountNavigation(['procurement.view_purchaseorder'])
    await flushPromises()
    expect(mocks.list).toHaveBeenLastCalledWith(expect.objectContaining({ page: 1, page_size: 50, ordering: '-updated_at' }))

    await page.get('[data-testid="purchase-status-SUBMITTED"]').trigger('click')
    await flushPromises()
    expect(mocks.list).toHaveBeenLastCalledWith(expect.objectContaining({ status: 'SUBMITTED', page: 1 }))
    expect(page.get('[data-testid="purchase-status-SUBMITTED"]').attributes('aria-pressed')).toBe('true')

    await page.get('[data-testid="purchase-sort"]').trigger('click')
    await flushPromises()
    expect(mocks.list).toHaveBeenLastCalledWith(expect.objectContaining({ status: 'SUBMITTED', ordering: 'updated_at' }))

    await page.get('[data-testid="purchase-status-all"]').trigger('click')
    await flushPromises()
    expect(mocks.list).toHaveBeenLastCalledWith(expect.objectContaining({ status: '' }))
  })

  it('统计读取失败显示未知值，不把失败伪装成零条订单', async () => {
    mocks.stats.mockRejectedValueOnce(new Error('网络断开'))
    const { page } = mountNavigation(['procurement.view_purchaseorder'])
    await flushPromises()
    expect(page.get('[data-testid="purchase-status-all"]').text()).toContain('—')
    expect(page.get('[data-testid="purchase-status-all"]').text()).not.toContain('0')
    expect(page.find('.load-error').exists()).toBe(true)
  })

  it('已完成采购标签使用真实统计并提交完成状态筛选', async () => {
    mocks.stats.mockResolvedValueOnce({ total: 12, draft: 3, submitted: 5, completed: 4, amounts: [] })
    const { page } = mountNavigation(['procurement.view_purchaseorder'])
    await flushPromises()
    expect(page.get('[data-testid="purchase-status-COMPLETED"]').text()).toContain('4')
    await page.get('[data-testid="purchase-status-COMPLETED"]').trigger('click')
    await flushPromises()
    expect(mocks.list).toHaveBeenLastCalledWith(expect.objectContaining({ status: 'COMPLETED' }))
    expect(page.text()).not.toContain('查看明细')
  })

  it('退货状态筛选只查询列表，不导航到退货管理', async () => {
    const { page } = mountNavigation(['procurement.view_purchaseorder'])
    await flushPromises()
    const select = page.findAllComponents(ElSelect).find((item) => item.attributes('aria-label') === '退货状态筛选')!
    select.vm.$emit('update:modelValue', 'QUALITY_GENERATED')
    select.vm.$emit('change', 'QUALITY_GENERATED')
    await flushPromises()
    expect(mocks.list).toHaveBeenLastCalledWith(expect.objectContaining({ return_status: 'QUALITY_GENERATED' }))
    expect(mocks.push).not.toHaveBeenCalled()
  })

  it('采购列表使用入库情况列并显示仓库流程状态', async () => {
    mocks.list.mockResolvedValueOnce({
      data: [{
        id: 'purchase-1', order_number: 'CGDD2026091701', source_type: 'PRODUCTION',
        production_task_number: 'HT26001', delivery_date: '2026-09-30', is_historical_unlinked: false,
        product_summary: [], line_count: 1, supplier_assigned_line_count: 1, supplier_count: 1,
        supplier_summary: [{ id: 'supplier-1', supplier_number: 'GYS001', supplier_name: '测试供应商' }],
        currency_code: 'CNY', total_amount: '100.00', is_mailed: false,
        status: 'PURCHASING', status_display: '采购中', created_at: '2026-09-17T00:00:00Z',
        completion: {
          can_complete: false, blocked_reason: '等待入库', inbound_status: 'PENDING_RECEIPT',
          inbound_status_display: '等待入库', has_returns: false, return_status: 'NONE', return_status_display: '无退货',
        },
      }],
      meta: { total: 1, total_pages: 1 },
    })
    const pinia = createPinia()
    useAuthStore(pinia).user = {
      id: 1, username: 'inbound-status-test', display_name: '入库状态测试',
      is_superuser: false, employee: null, permissions: ['procurement.view_purchaseorder'], data_scope: 'ALL',
    }
    const page = mount(PurchaseOrderListView, { global: { plugins: [pinia, ElementPlus] } })
    mounted.push(page)
    await flushPromises()

    expect(page.text()).toContain('入库情况')
    expect(page.text()).not.toContain('退货情况')
    expect(page.get('[data-testid="purchase-inbound-status"]').text()).toBe('等待入库')
    expect(page.find('[data-testid="purchase-return-status"]').exists()).toBe(false)
  })
})
