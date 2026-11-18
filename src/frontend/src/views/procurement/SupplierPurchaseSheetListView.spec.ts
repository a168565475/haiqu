import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '@/api/purchaseOrders'
import type { SupplierPurchaseSheet } from '@/types/purchaseOrder'
import SupplierPurchaseSheetListView from './SupplierPurchaseSheetListView.vue'
import PurchaseSheetTemplateSelectView from './PurchaseSheetTemplateSelectView.vue'

const state = vi.hoisted(() => ({ query: {} as Record<string, string>, canGenerate: true }))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }), useRoute: () => ({ query: state.query, params: { id: 'order-1' } }) }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ user: { is_superuser: false }, moduleCan: (permission: string) => permission === 'access_control.generate_purchasesheets' ? state.canGenerate : true }) }))
vi.mock('@/api/purchaseOrders', () => ({
  fetchSupplierPurchaseSheets: vi.fn(), batchDownloadSupplierPurchaseSheets: vi.fn(),
  batchPublishSupplierPurchaseSheets: vi.fn(), downloadSupplierPurchaseSheetXlsx: vi.fn(),
  ensureDefaultPurchaseSheets: vi.fn(), fetchPurchaseSheetOptions: vi.fn(), generatePurchaseSheets: vi.fn(),
}))

const rows = [
  { id: 'draft', sheet_number: 'CGDD-1', version_number: 1, status: 'DRAFT', status_display: '草稿', total_amount: '10', updated_at: '2026-10-26T00:00:00Z' },
  { id: 'published', sheet_number: 'CGDD-2', version_number: 1, status: 'PUBLISHED', status_display: '已发布', total_amount: '20', updated_at: '2026-10-26T00:00:00Z' },
] as SupplierPurchaseSheet[]

beforeEach(() => {
  vi.resetAllMocks()
  state.query = {}
  state.canGenerate = true
  vi.mocked(api.ensureDefaultPurchaseSheets).mockResolvedValue(undefined)
  vi.mocked(api.fetchSupplierPurchaseSheets).mockResolvedValue({ data: rows, meta: { total: rows.length } } as never)
  vi.mocked(api.batchDownloadSupplierPurchaseSheets).mockResolvedValue(new Blob(['excel-zip'], { type: 'application/zip' }))
  Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn(() => 'blob:excel-export') })
  Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() })
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
})
afterEach(() => vi.restoreAllMocks())

async function renderList() {
  const wrapper = mount(SupplierPurchaseSheetListView, {
    global: { plugins: [ElementPlus], stubs: { AppWindowDialog: { template: '<div><slot /><slot name="footer" /></div>' } } },
  })
  await flushPromises()
  return wrapper
}

describe('供应商采购表只提供Excel导出', () => {
  it('金额统一显示两位，零和待结算分开且不改后端值', async () => {
    const values = ['0', '12.3456', '999.9950', '123456789012345678.1234', null]
    const items = values.map((total_amount, index) => ({ ...rows[0]!, id: `amount-${index}`, total_amount }))
    vi.mocked(api.fetchSupplierPurchaseSheets).mockResolvedValue({ data: items, meta: { total: items.length } } as never)
    const wrapper = await renderList()
    try {
      const text = wrapper.text()
      for (const expected of ['¥0.00', '¥12.35', '¥1,000.00', '¥123,456,789,012,345,678.12', '待结算']) expect(text).toContain(expected)
      expect(items.map(item => item.total_amount)).toEqual(values)
    } finally { wrapper.unmount() }
  })

  it('模板选择总额和供应商金额显示两位，空值不冒充零', async () => {
    const data = { purchase_order: { id: 'order-1', order_number: '采购单', total_amount: '12.3456' },
      suppliers: [{ supplier_id: 'supplier-1', supplier_name: '供应商甲', total_amount: '0', line_count: 1 },
        { supplier_id: 'supplier-2', supplier_name: '供应商乙', total_amount: null, line_count: 1 }],
      templates: [], existing_sheet_count: 0 }
    vi.mocked(api.fetchPurchaseSheetOptions).mockResolvedValue(data as never)
    const wrapper = mount(PurchaseSheetTemplateSelectView, { global: { plugins: [ElementPlus] } })
    try {
      await flushPromises()
      expect(wrapper.get('.order-total strong').text()).toBe('¥12.35')
      expect(wrapper.findAll('.supplier-total strong').map(item => item.text())).toEqual(['¥0.00', '¥—'])
      expect(data.purchase_order.total_amount).toBe('12.3456')
      expect(api.generatePurchaseSheets).not.toHaveBeenCalled()
    } finally { wrapper.unmount() }
  })

  it('订单确认后自动准备默认草稿，再显示供应商采购表列表', async () => {
    state.query = { purchase_order_id: 'order-1' }
    const wrapper = await renderList()
    try {
      expect(api.ensureDefaultPurchaseSheets).toHaveBeenCalledExactlyOnceWith('order-1')
      expect(api.fetchSupplierPurchaseSheets).toHaveBeenCalledWith(expect.objectContaining({ purchase_order_id: 'order-1' }))
      expect(wrapper.text()).not.toContain('生成采购表')
      expect(api.batchPublishSupplierPurchaseSheets).not.toHaveBeenCalled()
    } finally { wrapper.unmount() }
  })

  it.each([false, true])('只读账号或无订单范围列表不自动生成：有权限=%s', async canGenerate => {
    state.canGenerate = canGenerate
    state.query = canGenerate ? {} : { purchase_order_id: 'order-1' }
    const wrapper = await renderList()
    try {
      expect(api.ensureDefaultPurchaseSheets).not.toHaveBeenCalled()
      expect(api.fetchSupplierPurchaseSheets).toHaveBeenCalledTimes(1)
    } finally { wrapper.unmount() }
  })

  it('缺少模板等生成失败直接显示真实原因，不显示假成功列表', async () => {
    state.query = { purchase_order_id: 'order-1' }
    vi.mocked(api.ensureDefaultPurchaseSheets).mockRejectedValueOnce(new Error('暂无可用采购合同模板'))
    const wrapper = await renderList()
    try {
      expect(wrapper.text()).toContain('暂无可用采购合同模板')
      expect(api.fetchSupplierPurchaseSheets).not.toHaveBeenCalled()
      expect(api.batchPublishSupplierPurchaseSheets).not.toHaveBeenCalled()
    } finally { wrapper.unmount() }
  })
  it('列表使用更多菜单，保留编辑、查看、Excel和批量下载入口', async () => {
    const wrapper = await renderList()
    try {
      expect(wrapper.get('[data-testid="sheet-batch-download"]').text()).toBe('批量下载Excel')
      const actions = wrapper.findAll('.row-more-button')
      expect(actions).toHaveLength(2)
      expect(actions[0]!.attributes('aria-label')).toBe('CGDD-1的更多操作')
      expect(wrapper.findAll('th').map(cell => cell.text())).toEqual(expect.arrayContaining(['更新人', '更新时间']))
      expect(wrapper.text()).not.toContain('V1')
      expect(wrapper.text()).not.toContain('历史未关联')
      await actions[0]!.trigger('click')
      await flushPromises()
      const menu = document.body.querySelector('.el-dropdown-menu')
      expect(menu?.textContent).toContain('编辑')
      expect(menu?.textContent).toContain('下载 Excel')
      expect(wrapper.text()).not.toContain('PDF')
    } finally { wrapper.unmount() }
  })

  it('仅选已发布采购表才可打包下载Excel', async () => {
    const wrapper = await renderList()
    try {
      const button = wrapper.get('[data-testid="sheet-batch-download"]')
      expect(button.attributes('disabled')).toBeDefined()
      wrapper.findComponent({ name: 'ElTable' }).vm.$emit('selection-change', rows)
      await flushPromises()
      expect(button.attributes('disabled')).toBeDefined()
      await (wrapper.vm as unknown as { batchDownload: () => Promise<void> }).batchDownload()
      expect(api.batchDownloadSupplierPurchaseSheets).not.toHaveBeenCalled()
      wrapper.findComponent({ name: 'ElTable' }).vm.$emit('selection-change', [rows[1]])
      await flushPromises()
      expect(button.attributes('disabled')).toBeUndefined()
      await button.trigger('click')
      await flushPromises()
      expect(api.batchDownloadSupplierPurchaseSheets).toHaveBeenCalledExactlyOnceWith(['published'])
      expect(URL.createObjectURL).toHaveBeenCalledTimes(1)
      expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:excel-export')
    } finally { wrapper.unmount() }
  })
})
