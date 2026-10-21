import { flushPromises, shallowMount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { describe, expect, it, vi } from 'vitest'
import * as api from '@/api/purchaseOrders'
import SupplierPurchaseSheetEditorView from './SupplierPurchaseSheetEditorView.vue'
import PurchaseReturnConfirmDialog from '@/components/procurement/PurchaseReturnConfirmDialog.vue'

vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }), useRoute: () => ({ params: { id: 'sheet-1' } }) }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ user: { is_superuser: true }, moduleCan: () => true }) }))
vi.mock('@/api/purchaseOrders', async original => ({ ...await original<typeof import('@/api/purchaseOrders')>(), fetchSupplierPurchaseSheet: vi.fn() }))
vi.mock('@/components/procurement/PurchaseSheetPdfPreview.vue', () => ({ default: { template: '<div />' } }))

describe('管材采购与退货显示单位', () => {
  it('采购表显示根数，计算金额继续使用米数乘每米单价', async () => {
    const content = { title: '管材采购合同', order: {}, buyer: { name: '甲方' }, seller: { name: '乙方' }, settlement_mode: 'NORMAL', quality_standards: [],
      lines: [{ source_purchase_order_line_id: 'pipe', measurement_kind: 'PIPE', actual_bar_count: 808, raw_bar_length_m: '3.35', quantity: '2706.8', unit: '米', unit_price: '2.5', amount: '6767' }] }
    vi.mocked(api.fetchSupplierPurchaseSheet).mockResolvedValue({ data: { id: 'sheet-1', sheet_number: 'CGDD261020002', version_number: 1, supplier_name_snapshot: '乙方', template_name: '管材采购模板', status: 'DRAFT', content_snapshot: content, line_images: [] }, etag: 'version-1' } as never)
    const wrapper = shallowMount(SupplierPurchaseSheetEditorView, { global: { plugins: [ElementPlus] } }); await flushPromises()
    const cells = wrapper.get('.reference-contract-table tbody tr').findAll('td')
    expect(cells[4]!.text()).toMatch(/^808 根/)
    expect(cells[4]!.get('small').text()).toBe('2706.8 米 · 3.35 米/根')
    expect(cells[5]!.text()).toContain('元/米')
    const vm = wrapper.vm as unknown as { content: { lines: Array<{ quantity: string; actual_bar_count: number; amount: string }> }; totalAmount: number; syncCalculatedAmounts: () => void }
    vm.syncCalculatedAmounts()
    expect(vm.totalAmount).toBe(6767)
    expect(vm.content.lines[0]).toMatchObject({ quantity: '2706.8', actual_bar_count: 808, amount: '6767' })
    wrapper.unmount()
  })
  it('退货数量与单位列一致使用根，米数放换算提示', () => {
    const wrapper = shallowMount(PurchaseReturnConfirmDialog, { props: { visible: true, submitting: false, action: 'view', record: {
      id: 'return-1', status: 'COMPLETED', lines: [{ id: 'pipe', quantity: '33.5000', unit: '米', raw_bar_length_m: '3.35', return_bar_count: 10 }],
    } as never }, global: { plugins: [ElementPlus], stubs: { ElDialog: { template: '<div><slot /></div>' } } } })
    const cells = wrapper.get('tbody tr').findAll('td')
    expect(cells[3]!.text()).toBe('10'); expect(cells[4]!.text()).toBe('根')
    expect(cells[3]!.attributes('title')).toBe('33.5 米 · 3.35 米/根')
    wrapper.unmount()
  })
})
