import { flushPromises, shallowMount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { describe, expect, it, vi } from 'vitest'
import * as api from '@/api/purchaseOrders'
import SupplierPurchaseSheetEditorView from './SupplierPurchaseSheetEditorView.vue'
import PurchaseReturnConfirmDialog from '@/components/procurement/PurchaseReturnConfirmDialog.vue'

vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }), useRoute: () => ({ params: { id: 'sheet-1' } }) }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ user: { is_superuser: true }, moduleCan: () => true }) }))
vi.mock('@/api/purchaseOrders', async original => ({ ...await original<typeof import('@/api/purchaseOrders')>(), fetchSupplierPurchaseSheet: vi.fn() }))

describe('管材采购与退货显示单位', () => {
  it.each(['DRAFT', 'PUBLISHED'])('采购表%s金额两位显示，四位单价和计算原值不变', async status => {
    const content = { title: '采购合同', order: {}, buyer: { name: '甲方' }, seller: { name: '乙方' }, settlement_mode: 'NORMAL', quality_standards: [],
      lines: [{ source_purchase_order_line_id: 'pipe', measurement_kind: 'PIPE', quantity: '3', unit: '米', unit_price: '1.2345', amount: '3.7035' }] }
    vi.mocked(api.fetchSupplierPurchaseSheet).mockResolvedValue({ data: { id: 'sheet-1', status, content_snapshot: content, line_images: [], total_amount: '3.7035' }, etag: 'version-1' } as never)
    const wrapper = shallowMount(SupplierPurchaseSheetEditorView, { global: { plugins: [ElementPlus] } })
    try {
      await flushPromises()
      const cells = wrapper.get('.reference-contract-table tbody tr').findAll('td')
      expect(cells[5]!.text()).toBe('1.2345 元/米')
      expect(cells[6]!.text()).toBe('3.70')
      expect(wrapper.get('.total-value').text()).toBe('3.70')
      const vm = wrapper.vm as unknown as { content: typeof content; syncCalculatedAmounts: () => void }
      vm.syncCalculatedAmounts()
      expect(vm.content.lines[0]).toMatchObject({ quantity: '3', unit_price: '1.2345', amount: '3.7035' })
    } finally { wrapper.unmount() }
  })

  it('已发布采购表无序号，完整分列规格属性和纯颜色，数量单价去尾零而金额两位', async () => {
    const line = { source_purchase_order_line_id: 'plastic', part_name: '半通', specification: '16', material: 'PE', remark: '无毛刺', section_title: '塑料件类', quantity: '48.0000', unit: '只', unit_price: '0.4500', amount: '21.6000',
      material_attributes_snapshot: { fields: [{ key: 'part_name', label: '品名', value: '半通' }, { key: 'material', label: '材质', value: 'PE' }, { key: 'plastic_color', label: '颜色', value: '黑色' }, { key: 'specification', label: '规格', value: '16' }] } }
    const content = { title: '塑料采购合同', order: { source_type: 'PRODUCTION' }, buyer: { name: '甲方' }, seller: { name: '乙方' }, settlement_mode: 'NORMAL', quality_standards: [], lines: [line] }
    vi.mocked(api.fetchSupplierPurchaseSheet).mockResolvedValue({ data: { id: 'sheet-1', sheet_number: 'CGDD261024002', version_number: 1, supplier_name_snapshot: '乙方', template_name: '塑料件采购合同', status: 'PUBLISHED', content_snapshot: content, line_images: [], total_amount: '21.6' }, etag: 'version-1' } as never)
    const wrapper = shallowMount(SupplierPurchaseSheetEditorView, { global: { plugins: [ElementPlus], renderStubDefaultSlot: true } })
    try {
      await flushPromises()
      const cells = wrapper.get('.reference-contract-table tbody tr').findAll('td')
      expect(wrapper.findAll('.reference-contract-table th').map(cell => cell.text())).toEqual(['产品名称', '产品规格', '物料属性', '颜色', '数量', '含税单价（元）', '金额（元）'])
      expect(cells.map(cell => cell.text())).toEqual(['半通', '16', '材质：PE；要求：无毛刺', '黑色', '48 只', '0.45', '21.60'])
      expect(wrapper.find('.bom-source-block').exists()).toBe(false)
      expect(wrapper.get('.published-info').text()).toContain('导出 Excel')
      expect(wrapper.get('.published-info').text()).not.toContain('PDF')
    } finally { wrapper.unmount() }
  })

  it('草稿的材质编辑位于属性列，补充要求单独保存到remark', async () => {
    const content = { title: '塑料采购合同', order: { source_type: 'PRODUCTION' }, buyer: { name: '甲方' }, seller: { name: '乙方' }, settlement_mode: 'NORMAL', quality_standards: [], lines: [{ source_purchase_order_line_id: 'plastic', part_name: '半通', specification: '16', material: 'PE', remark: '', quantity: '48', unit: '只', unit_price: '0.45', amount: '21.6', material_attributes_snapshot: { fields: [{ key: 'plastic_color', label: '颜色', value: '黑色' }] } }] }
    vi.mocked(api.fetchSupplierPurchaseSheet).mockResolvedValue({ data: { id: 'sheet-1', sheet_number: 'CGDD261024002', version_number: 1, supplier_name_snapshot: '乙方', template_name: '塑料件采购合同', status: 'DRAFT', content_snapshot: content, line_images: [] }, etag: 'version-1' } as never)
    const wrapper = shallowMount(SupplierPurchaseSheetEditorView, { global: { plugins: [ElementPlus], renderStubDefaultSlot: true } })
    try {
      await flushPromises()
      const cells = wrapper.get('.reference-contract-table tbody tr').findAll('td')
      expect(cells[2]!.find('[aria-label="产品材质"]').exists()).toBe(true)
      expect(cells[3]!.text()).toBe('黑色')
      const inputs = wrapper.findAllComponents({ name: 'ElInput' })
      inputs.find(input => input.attributes('aria-label') === '产品材质')!.vm.$emit('update:modelValue', 'PP')
      inputs.find(input => input.attributes('aria-label') === '补充要求')!.vm.$emit('update:modelValue', '无毛刺')
      await flushPromises()
      expect((wrapper.vm as any).content.lines[0]).toMatchObject({ material: 'PP', remark: '无毛刺', specification: '16' })
      expect(wrapper.get('.property-panel').text()).toContain('导出 Excel')
      expect(wrapper.get('.property-panel').text()).not.toContain('PDF')
    } finally { wrapper.unmount() }
  })

  it('采购表只显示采购单位米，金额继续使用米数乘每米单价', async () => {
    const content = { title: '管材采购合同', order: {}, buyer: { name: '甲方' }, seller: { name: '乙方' }, settlement_mode: 'NORMAL', quality_standards: [],
      lines: [{ source_purchase_order_line_id: 'pipe', measurement_kind: 'PIPE', actual_bar_count: 808, raw_bar_length_m: '3.35', quantity: '2706.8', unit: '米', unit_price: '2.5', amount: '6767' }] }
    vi.mocked(api.fetchSupplierPurchaseSheet).mockResolvedValue({ data: { id: 'sheet-1', sheet_number: 'CGDD261020002', version_number: 1, supplier_name_snapshot: '乙方', template_name: '管材采购模板', status: 'DRAFT', content_snapshot: content, line_images: [] }, etag: 'version-1' } as never)
    const wrapper = shallowMount(SupplierPurchaseSheetEditorView, { global: { plugins: [ElementPlus] } }); await flushPromises()
    const cells = wrapper.get('.reference-contract-table tbody tr').findAll('td')
    expect(cells[4]!.text()).toBe('2706.8 米')
    expect(cells[4]!.find('small').exists()).toBe(false)
    expect(cells[5]!.text()).toContain('元/米')
    const vm = wrapper.vm as unknown as { content: { lines: Array<{ quantity: string; actual_bar_count: number; amount: string }> }; totalAmount: number; syncCalculatedAmounts: () => void }
    vm.syncCalculatedAmounts()
    expect(vm.totalAmount).toBe(6767)
    expect(vm.content.lines[0]).toMatchObject({ quantity: '2706.8', actual_bar_count: 808, amount: '6767' })
    wrapper.unmount()
  })
  it.each(['DRAFT', 'PUBLISHED'])('PIPE_WEIGHT采购表%s锁定数量和单价，显示kg与元/kg', async status => {
    const content = { title: '管材采购合同', order: {}, buyer: { name: '甲方' }, seller: { name: '乙方' }, settlement_mode: 'NORMAL', quality_standards: [],
      lines: [{ source_purchase_order_line_id: 'pipe', measurement_kind: 'PIPE_WEIGHT', actual_bar_count: 808, raw_bar_length_m: '3.35', actual_purchase_meters: '2706.8', actual_purchase_weight_kg: '300', quantity: '300', unit: 'KG', unit_price: '2.5', amount: '750' }] }
    vi.mocked(api.fetchSupplierPurchaseSheet).mockResolvedValue({ data: { id: 'sheet-1', sheet_number: 'CGDD261020002', version_number: 1, supplier_name_snapshot: '乙方', template_name: '管材采购模板', status, content_snapshot: content, line_images: [], total_amount: '750' }, etag: 'version-1' } as never)
    const wrapper = shallowMount(SupplierPurchaseSheetEditorView, { global: { plugins: [ElementPlus] } }); await flushPromises()
    try {
      const cells = wrapper.get('.reference-contract-table tbody tr').findAll('td')
      expect(cells[4]!.text()).toBe('300 kg')
      expect(cells[5]!.text()).toBe('2.5 元/kg')
      expect(cells[6]!.text()).toBe('750.00')
      expect(cells[4]!.find('[aria-label="数量"]').exists()).toBe(false)
      expect(cells[5]!.find('[aria-label="含税单价"]').exists()).toBe(false)
      expect(cells[4]!.text()).not.toMatch(/根|米/)
      expect((wrapper.vm as unknown as { totalAmount: number }).totalAmount).toBe(750)
    } finally { wrapper.unmount() }
  })
  it('五金重量采购表显示kg与元/kg，不按个修改数量或单价', async () => {
    const content = { title: '五金采购合同', order: {}, buyer: { name: '甲方' }, seller: { name: '乙方' }, settlement_mode: 'NORMAL', quality_standards: [],
      lines: [{ source_purchase_order_line_id: 'rivet', section_type: 'ACCESSORY', section_title: '五金件', measurement_kind: 'HARDWARE_WEIGHT', quantity: '0.04752', unit: 'KG', unit_price: '8.5', amount: '0.4039', calculation_snapshot: { measurement_kind: 'HARDWARE_WEIGHT', hardware_quantity_unit: '个', hardware_unit_weight_kg: '0.00396' } }] }
    vi.mocked(api.fetchSupplierPurchaseSheet).mockResolvedValue({ data: { id: 'sheet-1', sheet_number: 'CGDD261020003', supplier_name_snapshot: '乙方', template_name: '五金采购模板', status: 'DRAFT', content_snapshot: content, line_images: [], total_amount: '0.4039' }, etag: 'version-1' } as never)
    const wrapper = shallowMount(SupplierPurchaseSheetEditorView, { global: { plugins: [ElementPlus] } }); await flushPromises()
    try {
      const cells = wrapper.get('.reference-contract-table tbody tr').findAll('td')
      expect(cells[4]!.text()).toContain('0.04752 kg')
      expect(cells[4]!.text()).not.toContain('参考')
      expect(cells[4]!.find('small').exists()).toBe(false)
      expect(cells[5]!.text()).toBe('8.5 元/kg')
      expect(cells[6]!.text()).toBe('0.40')
      expect(cells[4]!.find('[aria-label="数量"]').exists()).toBe(false)
      expect(cells[5]!.find('[aria-label="含税单价"]').exists()).toBe(false)
    } finally { wrapper.unmount() }
  })
  it('退货数量与单位列均使用采购单位米，不再显示根数换算提示', () => {
    const wrapper = shallowMount(PurchaseReturnConfirmDialog, { props: { visible: true, submitting: false, action: 'view', record: {
      id: 'return-1', status: 'COMPLETED', lines: [{ id: 'pipe', quantity: '33.5000', unit: '米', raw_bar_length_m: '3.35', return_bar_count: 10 }],
    } as never }, global: { plugins: [ElementPlus], stubs: { ElDialog: { template: '<div><slot /></div>' } } } })
    const cells = wrapper.get('tbody tr').findAll('td')
    expect(cells[3]!.text()).toBe('33.5'); expect(cells[4]!.text()).toBe('米')
    expect(cells[3]!.attributes('title')).toBeUndefined()
    wrapper.unmount()
  })
})
