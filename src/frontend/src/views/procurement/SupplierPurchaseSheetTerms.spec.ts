import { flushPromises, shallowMount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { describe, expect, it, vi } from 'vitest'
import * as api from '@/api/purchaseOrders'
import SupplierPurchaseSheetEditorView from './SupplierPurchaseSheetEditorView.vue'

vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }), useRoute: () => ({ params: { id: 'sheet-1' } }) }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ user: { is_superuser: true }, moduleCan: () => true }) }))
vi.mock('@/api/purchaseOrders', async original => ({ ...await original<typeof import('@/api/purchaseOrders')>(), fetchSupplierPurchaseSheet: vi.fn(), saveSupplierPurchaseSheet: vi.fn(), fetchSupplierPurchaseSheetPreview: vi.fn() }))

async function render(status = 'DRAFT', original = false) {
  vi.mocked(api.fetchSupplierPurchaseSheetPreview).mockResolvedValue({
    columns: [100], rows: [], images: [], width: 100, height: 100,
    margins: { top: 10, left: 10, right: 10, bottom: 10 },
    terms: { title: '原版标题', payment_and_delivery: '原版交期条款', quality_standards: ['原版质量要求'] },
  })
  vi.mocked(api.fetchSupplierPurchaseSheet).mockResolvedValue({ data: {
    id: 'sheet-1', status, template_code: original ? 'FABRIC' : undefined, sheet_number: 'CG-1', version_number: 1, supplier_name_snapshot: '乙方', template_name: '采购合同', content_snapshot: {
      title: '采购合同', order: {}, buyer: { name: '甲方' }, seller: { name: '乙方' },
      payment_and_delivery: '原交期条款', quality_standards: ['原质量要求'], lines: [], settlement_mode: 'NORMAL',
    }, line_images: [],
  }, etag: 'v1' } as never)
  const wrapper = shallowMount(SupplierPurchaseSheetEditorView, { global: { plugins: [ElementPlus], renderStubDefaultSlot: true } })
  await flushPromises()
  return wrapper
}
type Editor = {
  openTerm: (key: 'payment_and_delivery' | 'quality_standards') => void
  applyTerm: () => void
  editingTerm: string | null
  termDraft: string
  content: { payment_and_delivery: string; quality_standards: string[]; original_template_edits?: string[] }
}

describe('采购条款按钮弹窗', () => {
  it('取消不改当前条款，确认只更新本地草稿，不自动保存', async () => {
    const wrapper = await render()
    try {
      expect(wrapper.findAll('.term-buttons el-button-stub')).toHaveLength(6)
      expect(wrapper.find('.terms-section el-input-stub').exists()).toBe(false)
      const vm = wrapper.vm as unknown as Editor
      vm.openTerm('payment_and_delivery')
      expect(vm.termDraft).toBe('原交期条款')
      vm.termDraft = '取消的修改'
      vm.editingTerm = null
      expect(vm.content.payment_and_delivery).toBe('原交期条款')
      vm.openTerm('payment_and_delivery')
      expect(vm.termDraft).toBe('原交期条款')
      vm.termDraft = '确认的修改'
      vm.applyTerm()
      expect(vm.content.payment_and_delivery).toBe('确认的修改')
      expect(vm.editingTerm).toBeNull()
      expect(api.saveSupplierPurchaseSheet).not.toHaveBeenCalled()
    } finally { wrapper.unmount() }
  })
  it('质量标准保留每行一条的保存契约', async () => {
    const wrapper = await render()
    try {
      const vm = wrapper.vm as unknown as Editor
      vm.openTerm('quality_standards')
      vm.termDraft = ' 第一条\n\n第二条 '
      vm.applyTerm()
      expect(vm.content.quality_standards).toEqual(['第一条', '第二条'])
    } finally { wrapper.unmount() }
  })
  it('原版合同默认显示同源预览，弹窗读取原文，只标记已确认的改动', async () => {
    const wrapper = await render('DRAFT', true)
    try {
      expect(wrapper.find('purchase-sheet-original-preview-stub').exists()).toBe(true)
      expect(wrapper.find('.a4-canvas').exists()).toBe(false)
      const vm = wrapper.vm as unknown as Editor
      vm.openTerm('payment_and_delivery')
      expect(vm.termDraft).toBe('原版交期条款')
      vm.editingTerm = null
      expect(vm.content.original_template_edits).toBeUndefined()
      vm.openTerm('payment_and_delivery')
      vm.termDraft = '确认修改原版交期'
      vm.applyTerm()
      expect(vm.content.original_template_edits).toEqual(['payment_and_delivery'])
      expect(vm.content.payment_and_delivery).toBe('确认修改原版交期')
      expect(api.saveSupplierPurchaseSheet).not.toHaveBeenCalled()
    } finally { wrapper.unmount() }
  })
  it('已发布采购表不能打开条款编辑', async () => {
    const wrapper = await render('PUBLISHED')
    try {
      const vm = wrapper.vm as unknown as Editor
      vm.openTerm('payment_and_delivery')
      expect(vm.editingTerm).toBeNull()
      expect(wrapper.find('.term-buttons').exists()).toBe(false)
    } finally { wrapper.unmount() }
  })
})
