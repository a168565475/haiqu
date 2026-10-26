import { flushPromises, shallowMount, type VueWrapper } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fetchPurchaseOrderOptions } from '@/api/purchaseOrders'
import type { PurchaseOrderInput, PurchaseOrderSource, PurchaseOrderSupplierOption } from '@/types/purchaseOrder'
import type { SupplierCategory } from '@/types/supplier'
import PurchaseOrderFormView from './PurchaseOrderFormView.vue'

vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }), useRoute: () => ({ name: 'purchase-order-create-details', query: {} }) }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ user: { is_superuser: true }, hasPermission: () => true }) }))
vi.mock('@/api/purchaseOrders', () => ({ fetchPurchaseOrderOptions: vi.fn(), fetchPurchaseOrderSource: vi.fn(), fetchSamplePurchaseOrderSource: vi.fn(), createPurchaseOrder: vi.fn() }))

type Page = {
  lines: Array<{ category: string; supplier_id: string | null; suggested_supplier_category: SupplierCategory | null }>
  source: PurchaseOrderSource
  sourceLoading: boolean
  supplierCategories: string[]
  bulkSupplierCategory: string | null
  bulkSupplierId: string | null
  bulkSupplierOptions: PurchaseOrderSupplierOption[]
  applyBulkSupplier: (value: string | null) => void
  refreshBulkSupplier: () => void
  resetSource: () => void
  applySource: (source: PurchaseOrderSource) => void
  buildPayload: () => PurchaseOrderInput
}
let wrapper: VueWrapper
let page: Page
const source = (): PurchaseOrderSource => ({ can_create: true, selected_bom_id: 'bom-1', blockers: [],
  has_creatable_bom: true, requires_bom_selection: false, bom_options: [], source_revision: 'v1', preview_lines: [], default_currency_id: null,
  lines: [
  { bom_line_id: 'line-1', category: '五金件', source_quantity_text: '2' },
  { bom_line_id: 'line-2', category: '五金件', source_quantity_text: '3' },
  { bom_line_id: 'line-3', category: '包材', source_quantity_text: '4' },
  ].map(line => ({
    bom_number: 'BOM-1', bom_status: 'VERIFIED', bom_status_display: '已确认', section_type: 'HARDWARE', section_title: line.category,
    product_line_id: 'product-1', product_line_number: 1, product_number: 'P-1', product_name: '椅子', product_specification: '', product_color: '',
    material: '', part_name: '材料', specification: '', raw_material: '', source_bom_line_id_snapshot: line.bom_line_id,
    required_quantity: line.source_quantity_text, source_quantity_field: 'quantity', source_unit_text: '个', quantity_parse_status: 'READY',
    suggested_supplier_category: line.category === '五金件' ? 'HARDWARE' : 'PACKAGING', category_source: 'SECTION', ...line,
  })),
})
beforeEach(async () => {
  vi.clearAllMocks()
  vi.mocked(fetchPurchaseOrderOptions).mockResolvedValue({ production_tasks: [], suppliers: [
    { id: 'supplier-a', supplier_number: 'A', supplier_name: '五金供应商', supplier_categories: ['HARDWARE'] },
    { id: 'supplier-b', supplier_number: 'B', supplier_name: '包材供应商', supplier_categories: ['PACKAGING'] },
    { id: 'supplier-c', supplier_number: 'C', supplier_name: '五金包材供应商', supplier_categories: ['HARDWARE', 'PACKAGING'] },
  ], currencies: [], default_currency_id: null })
  wrapper = shallowMount(PurchaseOrderFormView, { global: { plugins: [ElementPlus], stubs: { ElDatePicker: { template: '<div />' } } } })
  await flushPromises()
  page = wrapper.vm as unknown as Page
  page.applySource(source())
  await flushPromises()
})
afterEach(() => wrapper.unmount())
const categorySelect = () => wrapper.get('[data-testid="purchase-bulk-supplier-category"]').getComponent({ name: 'ElSelect' })
async function chooseCategory(value: string | null) {
  categorySelect().vm.$emit('update:modelValue', value)
  categorySelect().vm.$emit('change', value)
  await flushPromises()
}

describe('采购按分类统一供应商', () => {
  it('未选择分类时禁用统一供应商，分类从当前明细去重生成', async () => {
    expect(page.supplierCategories).toEqual(['五金件', '包材'])
    expect(wrapper.get('[data-testid="purchase-bulk-supplier"]').getComponent({ name: 'ElSelect' }).props('disabled')).toBe(true)
    page.applyBulkSupplier('supplier-a')
    expect(page.lines.map(row => row.supplier_id)).toEqual([null, null, null])
    await chooseCategory('五金件')
    expect(wrapper.get('[data-testid="purchase-bulk-supplier"]').getComponent({ name: 'ElSelect' }).props('disabled')).toBe(false)
  })

  it('只更新所选分类，并按原接口逐行带入供应商', async () => {
    page.lines[2]!.supplier_id = 'supplier-b'
    await chooseCategory('五金件')
    const control = wrapper.get('[data-testid="purchase-bulk-supplier"]').getComponent({ name: 'ElSelect' })
    control.vm.$emit('update:modelValue', 'supplier-a'); control.vm.$emit('change', 'supplier-a')
    await flushPromises()
    expect(page.lines.map(row => row.supplier_id)).toEqual(['supplier-a', 'supplier-a', 'supplier-b'])
    expect(page.buildPayload().lines.map(row => row.supplier_id)).toEqual(['supplier-a', 'supplier-a', 'supplier-b'])
  })

  it('切换分类仅回显该类共同供应商，混合供应商时留空', async () => {
    page.lines[0]!.supplier_id = page.lines[1]!.supplier_id = 'supplier-a'
    page.lines[2]!.supplier_id = 'supplier-b'
    await chooseCategory('五金件'); expect(page.bulkSupplierId).toBe('supplier-a')
    await chooseCategory('包材'); expect(page.bulkSupplierId).toBe('supplier-b')
    expect(page.lines.map(row => row.supplier_id)).toEqual(['supplier-a', 'supplier-a', 'supplier-b'])
    await chooseCategory('五金件')
    page.lines[1]!.supplier_id = 'supplier-b'; page.refreshBulkSupplier()
    expect(page.bulkSupplierId).toBeNull()
    page.lines[1]!.supplier_id = 'supplier-a'; page.refreshBulkSupplier()
    expect(page.bulkSupplierId).toBe('supplier-a')
  })

  it('清空只影响当前分类，清空分类不修改任何明细，全部分类须明确选择', async () => {
    await chooseCategory('__all__'); page.applyBulkSupplier('supplier-a')
    await chooseCategory('五金件'); page.applyBulkSupplier(null)
    expect(page.lines.map(row => row.supplier_id)).toEqual([null, null, 'supplier-a'])
    await chooseCategory(null); page.applyBulkSupplier('supplier-b')
    expect(page.bulkSupplierId).toBeNull()
    expect(page.lines.map(row => row.supplier_id)).toEqual([null, null, 'supplier-a'])
    await chooseCategory('__all__'); page.applyBulkSupplier('supplier-b')
    expect(page.lines.map(row => row.supplier_id)).toEqual(['supplier-b', 'supplier-b', 'supplier-b'])
  })

  it('来源重新载入或清空时重置分类，不沿用上一张单的范围', async () => {
    await chooseCategory('五金件'); page.applySource(source())
    expect(page.bulkSupplierCategory).toBeNull(); expect(page.bulkSupplierId).toBeNull()
    await chooseCategory('__all__'); page.resetSource()
    expect(page.bulkSupplierCategory).toBeNull(); expect(page.supplierCategories).toEqual([])
  })

  it('未分类可单独选择，预览、加载中和失效分类不能批量改值', async () => {
    page.lines[2]!.category = ''
    await chooseCategory('未分类'); page.applyBulkSupplier('supplier-b')
    expect(page.lines.map(row => row.supplier_id)).toEqual([null, null, 'supplier-b'])
    await chooseCategory('五金件'); page.source.can_create = false; page.applyBulkSupplier('supplier-b')
    page.source.can_create = true; page.sourceLoading = true; page.applyBulkSupplier('supplier-b')
    page.sourceLoading = false; await chooseCategory('不存在的分类'); page.applyBulkSupplier('supplier-b')
    expect(page.lines.map(row => row.supplier_id)).toEqual([null, null, 'supplier-b'])
  })

  it('按物料对应的类别筛选，支持供应商多类别；全部分类显示完整列表', async () => {
    await chooseCategory('五金件')
    expect(page.bulkSupplierOptions.map(row => row.id)).toEqual(['supplier-a', 'supplier-c'])
    await chooseCategory('包材')
    expect(page.bulkSupplierOptions.map(row => row.id)).toEqual(['supplier-b', 'supplier-c'])
    await chooseCategory('__all__')
    expect(page.bulkSupplierOptions.map(row => row.id)).toEqual(['supplier-a', 'supplier-b', 'supplier-c'])
  })

  it('同一显示分类包含多种供应商类别时，仅显示同时支持各类别的供应商', async () => {
    page.lines[1]!.suggested_supplier_category = 'PACKAGING'
    await chooseCategory('五金件')
    expect(page.bulkSupplierOptions.map(row => row.id)).toEqual(['supplier-c'])
  })

  it('未识别分类或没有匹配供应商时明确提示，不回退全部供应商', async () => {
    page.lines[0]!.suggested_supplier_category = null
    await chooseCategory('五金件')
    expect(page.bulkSupplierOptions).toEqual([])
    expect(wrapper.get('[data-testid="purchase-bulk-supplier"]').getComponent({ name: 'ElSelect' }).props('noDataText')).toContain('尚未对应')
    page.applyBulkSupplier('supplier-a')
    expect(page.lines.map(row => row.supplier_id)).toEqual([null, null, null])
    page.lines[0]!.suggested_supplier_category = page.lines[1]!.suggested_supplier_category = 'FABRIC'
    await flushPromises()
    expect(page.bulkSupplierOptions).toEqual([])
    expect(wrapper.get('[data-testid="purchase-bulk-supplier"]').getComponent({ name: 'ElSelect' }).props('noDataText')).toContain('维护对应类别')
  })

  it('切换类别保留已填供应商，仅拒绝新选择的不匹配候选', async () => {
    page.lines[2]!.supplier_id = 'supplier-a'
    await chooseCategory('包材')
    expect(page.bulkSupplierId).toBe('supplier-a')
    expect(page.lines[2]!.supplier_id).toBe('supplier-a')
    page.applyBulkSupplier('supplier-a')
    expect(page.lines[2]!.supplier_id).toBe('supplier-a')
    page.applyBulkSupplier('supplier-b')
    expect(page.lines[2]!.supplier_id).toBe('supplier-b')
  })
})
