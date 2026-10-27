import { flushPromises, shallowMount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '@/api/boms'
import * as productsApi from '@/api/products'
import BomEditorView from './BomEditorView.vue'
import InquiryProductDialog from '@/components/inquiries/InquiryProductDialog.vue'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import BomPrintDocument from '@/components/boms/BomPrintDocument.vue'

const auth = vi.hoisted(() => ({ editable: true }))
vi.mock('vue-router', () => ({ useRoute: () => ({ params: { bomId: 'b1' } }), useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: (key: string) => auth.editable || key === 'boms.view_bom', moduleCan: () => auth.editable }) }))
vi.mock('@/api/boms', async original => ({ ...await original<typeof import('@/api/boms')>(), fetchBomForEdit: vi.fn(), confirmBomProduct: vi.fn() }))
vi.mock('@/api/productionData', async original => ({ ...await original<typeof import('@/api/productionData')>(), fetchAllProductionDataRecords: vi.fn().mockResolvedValue([]) }))
vi.mock('@/api/products', async original => ({ ...await original<typeof import('@/api/products')>(), fetchProductOptions: vi.fn() }))

const record = {
  id: 'b1', bom_number: 'BOM0000775', version_number: 1, status: 'PENDING_CONFIRMATION',
  production_task_id: 'task1', production_task_number: 'HT26002', production_task_product_id: 'line1',
  order_number: 'HT26002', product_code_snapshot: 'HTB-007', product_number_snapshot: 'HTB-007',
  product_name_snapshot: '三折床-不带棚', item_number_snapshot: 'XY-212', specification_snapshot: '186*55*24cm',
  product_color_snapshot: '深宝蓝', product_unit_name: '张', material_snapshot: 'PE',
  product_master_id: 'p1', product_color_id: 'color1', product_category_id: 'cat1', product_unit_id: 'u1',
  product_unit_code_snapshot: 'PCS', order_quantity: '1000', current_order_quantity: '1001',
  source_quantity: null, batch_quantity: null, quantity_difference: '1', quantity_difference_reason: '',
  quantity_requires_confirmation: true, product_information_confirmed: true, sections: [],
  configured_field_labels: {}, is_order_quantity_outdated: false, is_order_product_outdated: false,
}
const versioned = (overrides = {}) => ({ data: { ...record, ...overrides }, etag: 'v1' })
function open() {
  return shallowMount(BomEditorView, { attachTo: document.body, global: { plugins: [ElementPlus], renderStubDefaultSlot: true,
    stubs: { BomProductInfoDialog: false, BomProductOverview: false, BomQuantityCompareCard: false, BomSectionSidebar: false, BomProductConfirmationDialogs: false, ElButton: false, ElInput: false, ElTableColumn: { template: '<div />' } } } })
}
beforeEach(() => {
  vi.clearAllMocks(); auth.editable = true
  vi.mocked(api.fetchBomForEdit).mockResolvedValue(versioned() as never)
  vi.mocked(productsApi.fetchProductOptions).mockResolvedValue({ categories: [], units: [], items: [] })
})

describe('BOM 编辑页页签与核对集成', () => {
  it('打印保留所有分区和当前未保存输入，不调用保存接口', async () => {
    const print = vi.spyOn(window, 'print').mockImplementation(() => {})
    const wrapper = open(); await flushPromises()
    try {
      const vm = wrapper.vm as unknown as { sections: Array<{ title: string; lines: Array<{ part_name: string }> }> }
      vm.sections[0]!.lines[0]!.part_name = '本地未保存部件'
      await wrapper.findAll('button').find(button => button.text() === '预览打印')!.trigger('click')
      expect(print).toHaveBeenCalledOnce()
      const document = wrapper.findComponent(BomPrintDocument)
      expect(document.props('sections')).toHaveLength(7)
      expect(document.props('sections')[0].lines[0].part_name).toBe('本地未保存部件')
      expect(api.confirmBomProduct).not.toHaveBeenCalled()
    } finally { wrapper.unmount(); print.mockRestore() }
  })
  it('切换页签只切显示内容，保留用料编辑与数量说明且不自动保存', async () => {
    const wrapper = open(); await flushPromises()
    try {
      const material = wrapper.get('[role="tab"][aria-controls="bom-material-panel"]')
      const product = wrapper.get('[role="tab"][aria-controls="bom-product-panel"]')
      expect(material.attributes('aria-selected')).toBe('true')
      const reason = wrapper.get('input[placeholder="填写数量差异确认原因"]')
      await reason.setValue('本次核对说明')
      const vm = wrapper.vm as unknown as { sections: Array<{ lines: Array<{ component_name: string }> }> }
      vm.sections[0]!.lines[0]!.component_name = '未保存的床架'
      await product.trigger('click')
      expect(wrapper.get('#bom-product-panel').isVisible()).toBe(true)
      expect(wrapper.get('#bom-material-panel').isVisible()).toBe(false)
      expect(wrapper.get('.product-details').text()).toContain('XY-212')
      expect(wrapper.get('.product-details').find('input').exists()).toBe(false)
      await material.trigger('click')
      expect((reason.element as HTMLInputElement).value).toBe('本次核对说明')
      expect(vm.sections[0]!.lines[0]!.component_name).toBe('未保存的床架')
      expect(api.confirmBomProduct).not.toHaveBeenCalled()
    } finally { wrapper.unmount() }
  })

  it('核对成功才关闭并进入用料页；服务器旧物料不能覆盖本地草稿', async () => {
    vi.mocked(api.fetchBomForEdit).mockResolvedValue(versioned({ product_information_confirmed: false }) as never)
    const wrapper = open(); await flushPromises()
    try {
      const dialog = wrapper.findComponent(InquiryProductDialog)
      expect(dialog.props('modelValue')).toBe(true)
      const vm = wrapper.vm as unknown as { sections: Array<{ lines: Array<{ component_name: string }> }> }
      vm.sections[0]!.lines[0]!.component_name = '本地草稿'
      vi.mocked(api.confirmBomProduct).mockRejectedValueOnce(new Error('保存失败'))
      dialog.vm.$emit('confirm', { item: { product_id: 'p1', product_color_id: 'color1', material: 'PE' } })
      await flushPromises()
      expect(dialog.props('modelValue')).toBe(true)
      expect(dialog.props('saveError')).toContain('保存失败')
      vi.mocked(api.confirmBomProduct).mockResolvedValueOnce(versioned({ product_information_confirmed: false }) as never)
      dialog.vm.$emit('confirm', { item: { product_id: 'p1', product_color_id: 'color1', material: 'PE' } })
      await flushPromises()
      expect(dialog.props('modelValue')).toBe(true)
      expect(dialog.props('saveError')).toContain('服务器尚未确认')
      vi.mocked(api.confirmBomProduct).mockResolvedValue({ ...versioned(), etag: 'v2' } as never)
      dialog.vm.$emit('confirm', { item: { product_id: 'p1', product_color_id: 'color1', material: 'PE' } })
      await flushPromises()
      expect(dialog.props('modelValue')).toBe(false)
      expect(wrapper.get('[role="tab"][aria-controls="bom-material-panel"]').attributes('aria-selected')).toBe('true')
      expect(vm.sections[0]!.lines[0]!.component_name).toBe('本地草稿')
    } finally { wrapper.unmount() }
  })

  it('只读用户查看未核对产品时仍能正常关闭信息窗口', async () => {
    auth.editable = false
    vi.mocked(api.fetchBomForEdit).mockResolvedValue(versioned({ product_information_confirmed: false }) as never)
    const wrapper = open(); await flushPromises()
    try {
      expect(wrapper.findComponent(InquiryProductDialog).props('modelValue')).toBe(false)
      const readonly = wrapper.findAllComponents(AppWindowDialog).find(dialog => dialog.props('title') === '产品信息')!
      expect(readonly.props('modelValue')).toBe(true)
      readonly.vm.$emit('update:modelValue', false); await flushPromises()
      expect(readonly.props('modelValue')).toBe(false)
    } finally { wrapper.unmount() }
  })

  it('方向键仅移动页签焦点，激活页签后显示对应内容', async () => {
    const wrapper = open(); await flushPromises()
    try {
      const product = wrapper.get('#bom-product-tab')
      const material = wrapper.get('#bom-material-tab')
      ;(material.element as HTMLButtonElement).focus()
      await material.trigger('keydown', { key: 'ArrowLeft' })
      expect(document.activeElement).toBe(product.element)
      expect(product.attributes('tabindex')).toBe('0')
      expect(material.attributes('aria-selected')).toBe('true')
      await product.trigger('click')
      expect(product.attributes('aria-selected')).toBe('true')
      await product.trigger('keydown', { key: 'End' })
      expect(document.activeElement).toBe(material.element)
    } finally { wrapper.unmount() }
  })

  it('字典重试重新读取但不重新打开核对窗口', async () => {
    vi.mocked(api.fetchBomForEdit).mockResolvedValue(versioned({ product_information_confirmed: false }) as never)
    vi.mocked(productsApi.fetchProductOptions).mockRejectedValueOnce(new Error('字典失败'))
    const wrapper = open(); await flushPromises()
    try {
      const dialog = wrapper.findComponent(InquiryProductDialog)
      expect(dialog.props('catalogError')).toContain('字典失败')
      dialog.vm.$emit('retry-catalog'); await flushPromises()
      expect(dialog.props('catalogError')).toBe('')
      expect(dialog.props('modelValue')).toBe(true)
      expect(api.fetchBomForEdit).toHaveBeenCalledTimes(1)
    } finally { wrapper.unmount() }
  })
})
