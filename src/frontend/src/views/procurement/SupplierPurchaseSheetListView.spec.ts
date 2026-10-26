import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '@/api/purchaseOrders'
import type { SupplierPurchaseSheet } from '@/types/purchaseOrder'
import SupplierPurchaseSheetListView from './SupplierPurchaseSheetListView.vue'

vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }), useRoute: () => ({ query: {} }) }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ user: { is_superuser: true }, moduleCan: () => true }) }))
vi.mock('@/api/purchaseOrders', () => ({
  fetchSupplierPurchaseSheets: vi.fn(), batchDownloadSupplierPurchaseSheets: vi.fn(),
  batchPublishSupplierPurchaseSheets: vi.fn(), downloadSupplierPurchaseSheetXlsx: vi.fn(),
}))

const rows = [
  { id: 'draft', sheet_number: 'CGDD-1', version_number: 1, status: 'DRAFT', status_display: '草稿', total_amount: '10', updated_at: '2026-10-26T00:00:00Z' },
  { id: 'published', sheet_number: 'CGDD-2', version_number: 1, status: 'PUBLISHED', status_display: '已发布', total_amount: '20', updated_at: '2026-10-26T00:00:00Z' },
] as SupplierPurchaseSheet[]

beforeEach(() => {
  vi.resetAllMocks()
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
