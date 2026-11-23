import { flushPromises, mount, shallowMount } from '@vue/test-utils'
import ElementPlus, { ElInput, ElMessageBox } from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '@/api/purchaseOrders'
import PurchaseOrderConfirmView from './PurchaseOrderConfirmView.vue'

vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: () => true, moduleCan: () => true }) }))

const navigation = vi.hoisted(() => ({ push: vi.fn() }))
vi.mock('vue-router', () => ({
  useRouter: () => navigation,
  useRoute: () => ({ params: { id: 'order-1' } }),
}))
vi.mock('@/api/purchaseOrders', async original => ({
  ...await original<typeof import('@/api/purchaseOrders')>(),
  fetchVersionedPurchaseOrder: vi.fn(),
  fetchPurchaseOrderSupplierOptions: vi.fn(),
  updatePurchaseOrder: vi.fn(),
  confirmVersionedPurchaseOrder: vi.fn(),
}))

describe('采购订单确认校验', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(api.fetchPurchaseOrderSupplierOptions).mockResolvedValue({ suppliers: [] })
    vi.mocked(api.fetchVersionedPurchaseOrder).mockResolvedValue({
      etag: 'version-1',
      data: {
        id: 'order-1',
        order_number: 'CGDD2026091746',
        status: 'DRAFT',
        currency_code: 'CNY',
        product_summary: [],
        lines: [{
          id: 'line-1', line_number: 1, raw_bar_length_m: '2.96', suggested_bar_count: 96,
          actual_bar_count: 96, actual_purchase_quantity: null, quantity_difference_reason: '',
          supplier_id: 'supplier-1', delivery_date: '2026-10-08', unit_price: null,
          source_unit_text: '米',
        }],
      },
    } as never)
  })

  afterEach(() => vi.restoreAllMocks())

  it('生产批次草稿确认时跳过留空或填零的行，保留四位小数的实际采购行', async () => {
    const original = await api.fetchVersionedPurchaseOrder('order-1')
    const base: typeof original.data.lines[number] = { ...original.data.lines[0]!, raw_bar_length_m: null, actual_bar_count: null, source_unit_text: '个' }
    const active = { ...base, line_number: 6, id: 'buy', actual_purchase_quantity: '0.0001', unit_price: '2' }
    const order = { ...original.data, purchase_group_id: 'g', lines: [
      { ...base, id: 'skip-price', actual_purchase_quantity: '5', unit_price: '0.0000', supplier_id: null, delivery_date: null },
      { ...base, id: 'skip-quantity', line_number: 2, actual_purchase_quantity: '0', supplier_id: null, delivery_date: null },
      { ...base, id: 'blank-price', line_number: 3, actual_purchase_quantity: '5', unit_price: null, supplier_id: null, delivery_date: null },
      { ...base, id: 'blank-quantity', line_number: 4, actual_purchase_quantity: null, unit_price: '2', supplier_id: null, delivery_date: null },
      { ...base, id: 'blank-both', line_number: 5, actual_purchase_quantity: null, unit_price: null, supplier_id: null, delivery_date: null },
      active,
    ] }
    vi.mocked(api.fetchVersionedPurchaseOrder).mockResolvedValue({ data: order, etag: 'version-1' })
    vi.mocked(api.updatePurchaseOrder).mockResolvedValue({ data: { ...order, lines: [active] }, etag: 'version-2' })
    vi.mocked(api.confirmVersionedPurchaseOrder).mockResolvedValue({ data: { ...order, status: 'SUBMITTED', lines: [active] }, etag: 'version-3' })
    const confirm = vi.spyOn(ElMessageBox, 'confirm').mockRejectedValueOnce('cancel').mockResolvedValue('confirm' as never)
    const wrapper = shallowMount(PurchaseOrderConfirmView, { global: { plugins: [ElementPlus] } })
    try {
      await flushPromises()
      const vm = wrapper.vm as any
      expect(vm.confirmationErrors).toEqual([])
      expect(vm.lineAmount(vm.order.lines[0])).toBe('本批不买')
      await vm.confirmAndContinue()
      expect(confirm.mock.calls[0]?.[0]).toContain('本批将跳过 5 项材料。')
      expect(api.updatePurchaseOrder).not.toHaveBeenCalled()
      await vm.confirmAndContinue()
      expect(api.updatePurchaseOrder).toHaveBeenCalledExactlyOnceWith('order-1', expect.objectContaining({
        skipped_line_ids: ['skip-price', 'skip-quantity', 'blank-price', 'blank-quantity', 'blank-both'],
        lines: [expect.objectContaining({ id: 'buy', actual_purchase_quantity: '0.0001' })],
      }), 'version-1')
      expect(api.confirmVersionedPurchaseOrder).toHaveBeenCalledExactlyOnceWith('order-1')
    } finally { wrapper.unmount() }
  })

  it('重开草稿保留手填套数与独立采购数量，拆开后要求分别报价', async () => {
    const original = await api.fetchVersionedPurchaseOrder('order-1')
    const pricing = { anchor_id: 'stock-1', quantity: 1500, unit_price: '5.0000' }
    const base: typeof original.data.lines[number] = { ...original.data.lines[0]!, raw_bar_length_m: null, actual_bar_count: null, set_pricing: pricing,
      unit_price: null, source_unit_text: '米', supplier_id: 'supplier-1', delivery_date: '2026-11-28' }
    const order = { ...original.data, purchase_group_id: 'g', lines: [
      { ...base, id: 'line-1', purchase_group_line_id: 'stock-1', actual_purchase_quantity: '3200' },
      { ...base, id: 'line-2', purchase_group_line_id: 'stock-2', actual_purchase_quantity: '1600.1234' },
    ] }
    vi.mocked(api.fetchVersionedPurchaseOrder).mockResolvedValue({ data: order, etag: 'version-1' })
    const wrapper = shallowMount(PurchaseOrderConfirmView, { global: { plugins: [ElementPlus] } })
    await flushPromises()
    try {
      const vm = wrapper.vm as unknown as {
        totalScaled: bigint; confirmationErrors: string[]
        order: typeof order; updatePayload: () => { lines: typeof order.lines; skipped_line_ids?: string[] }
        saveSet: (change: import('./purchaseSetPricing').SetPricingChange) => void
      }
      expect(vm.totalScaled).toBe(75000000n)
      expect(vm.confirmationErrors).toEqual([])
      expect(vm.updatePayload().lines[1]).toMatchObject({ actual_purchase_quantity: '1600.1234', unit_price: null, set_pricing: pricing })
      vm.saveSet({ anchorId: 'stock-1', members: [], pricing: null, supplierId: null, deliveryDate: '' })
      expect(vm.updatePayload().skipped_line_ids).toEqual(['line-1', 'line-2'])
      expect(vm.confirmationErrors).toEqual(['本批至少要采购一项材料。'])
      vm.order.lines[0]!.unit_price = '2'
      vm.order.lines[1]!.unit_price = '3'
      expect(vm.updatePayload().lines).toHaveLength(2)
      expect(vm.updatePayload().lines.every(line => line.set_pricing === null)).toBe(true)
      expect(vm.updatePayload().skipped_line_ids).toBeUndefined()
    } finally { wrapper.unmount() }
  })

  it('KG确认页保留四位重量输入，修改后按重量计价并保存且不发送旧根数', async () => {
    const initial = await api.fetchVersionedPurchaseOrder('order-1')
    const weightLine = { ...initial.data.lines[0], section_type: 'PROFILE', source_unit_text: 'KG',
      actual_bar_count: 96, actual_purchase_quantity: '284.16', actual_purchase_weight_kg: '12.3456',
      suggested_purchase_weight_kg: '25.5', raw_bar_weight_kg: '2.5', unit_price: '2' }
    vi.mocked(api.fetchVersionedPurchaseOrder).mockResolvedValue({ ...initial, data: { ...initial.data, lines: [weightLine] } } as never)
    const wrapper = mount(PurchaseOrderConfirmView, { global: { plugins: [ElementPlus], stubs: { ElDatePicker: true } } })
    await flushPromises()
    try {
      const input = wrapper.get('input[aria-label="第 1 行实际采购重量（kg）"]')
      expect((input.element as HTMLInputElement).value).toBe('12.3456')
      await input.setValue('14.5678')
      await input.trigger('blur')
      const vm = wrapper.vm as unknown as { order: { lines: Array<{ actual_purchase_quantity: string }> }; totalScaled: bigint; confirmationErrors: string[]; saveChanges: (showSuccess: boolean) => Promise<boolean> }
      expect(vm.order.lines[0]!.actual_purchase_quantity).toBe('14.5678')
      expect(vm.totalScaled).toBe(291356n)
      expect(vm.confirmationErrors).toEqual([])
      expect(wrapper.find('[aria-label="实际采购根数"]').exists()).toBe(false)
      expect(wrapper.findAll('.el-input-group__append').map(node => node.text())).toContain('元/kg')
      expect(wrapper.text()).not.toMatch(/折算采购米数|换算采购根数|96 根|284.16 米/)
      vi.mocked(api.updatePurchaseOrder).mockResolvedValue({ data: { ...initial.data, lines: [{ ...weightLine, actual_purchase_weight_kg: '14.5678', actual_purchase_quantity: '14.5678' }] }, etag: 'version-2' } as never)
      expect(await vm.saveChanges(false)).toBe(true)
      const payload = vi.mocked(api.updatePurchaseOrder).mock.calls[0]![1]
      expect(payload.lines[0]).toMatchObject({ actual_purchase_quantity: '14.5678', actual_purchase_weight_kg: '14.5678' })
      expect(payload.lines[0]).not.toHaveProperty('actual_bar_count')
    } finally { wrapper.unmount() }
  })

  it('打样未填齐草稿从schema4快照恢复单根参数和KG，修改与清空均准确提交', async () => {
    const initial = await api.fetchVersionedPurchaseOrder('order-1')
    const partial = { ...initial.data.lines[0], section_type: 'PROFILE', source_unit_text: 'KG', required_quantity: null,
      raw_bar_length_m: null, raw_bar_weight_kg: null, actual_bar_count: null, actual_purchase_quantity: null, actual_purchase_weight_kg: null,
      unit_price: '2', calculation_snapshot: { schema_version: 4, measurement_unit: 'kg', shortage_meters: '12',
        raw_bar_length_m: '6', raw_bar_weight_kg: '2.5', actual_purchase_weight_kg: '12.3456' } }
    vi.mocked(api.fetchVersionedPurchaseOrder).mockResolvedValue({ ...initial, data: { ...initial.data, source_type: 'SAMPLE', lines: [partial] } } as never)
    const wrapper = mount(PurchaseOrderConfirmView, { global: { plugins: [ElementPlus], stubs: { ElDatePicker: true } } })
    await flushPromises()
    try {
      const vm = wrapper.vm as unknown as { order: { lines: Array<{ raw_bar_length_m: string | null; raw_bar_weight_kg: string | null; actual_purchase_quantity: string }> }; confirmationErrors: string[]; saveChanges: (show: boolean) => Promise<boolean> }
      expect(vm.order.lines[0]).toMatchObject({ raw_bar_length_m: '6', raw_bar_weight_kg: '2.5', actual_purchase_quantity: '12.3456' })
      expect(vm.confirmationErrors).toEqual([])
      await wrapper.get('[aria-label="修改管材单根参数"]').trigger('click'); await flushPromises()
      const length = wrapper.findAllComponents(ElInput).find(input => input.props('ariaLabel') === '采购每根长度（米）')!
      const unitWeight = wrapper.findAllComponents(ElInput).find(input => input.props('ariaLabel') === '采购每根标准重量（kg）')!
      await length.get('input').setValue('3.05'); await unitWeight.get('input').setValue('3')
      expect(wrapper.text()).toContain('12 kg')
      expect(wrapper.find('[aria-label="实际采购根数"]').exists()).toBe(false)
      vi.mocked(api.updatePurchaseOrder).mockImplementation(async () => ({ data: { ...initial.data, source_type: 'SAMPLE', lines: vm.order.lines }, etag: 'version-2' }) as never)
      expect(await vm.saveChanges(false)).toBe(true)
      const payload = vi.mocked(api.updatePurchaseOrder).mock.calls[0]![1].lines[0]!
      expect(payload).toMatchObject({ raw_bar_length_m: '3.05', raw_bar_weight_kg: '3', actual_purchase_quantity: '12.3456' })
      expect(payload).not.toHaveProperty('actual_bar_count')
      expect(payload).not.toHaveProperty('actual_purchase_weight_kg')
      vm.order.lines[0]!.raw_bar_length_m = null; vm.order.lines[0]!.raw_bar_weight_kg = null
      expect(vm.confirmationErrors[0]).toContain('有效每根长度')
      expect(vm.confirmationErrors[0]).toContain('有效每根标准重量')
      expect(await vm.saveChanges(false)).toBe(true)
      expect(vi.mocked(api.updatePurchaseOrder).mock.calls[1]![1].lines[0]).toMatchObject({ raw_bar_length_m: null, raw_bar_weight_kg: null, actual_purchase_quantity: '12.3456' })
    } finally { wrapper.unmount() }
  })

  it('管材填入根数后只提示真正缺少的字段，并在点击确认时弹窗', async () => {
    const alert = vi.spyOn(ElMessageBox, 'alert').mockResolvedValue('confirm' as never)
    const wrapper = shallowMount(PurchaseOrderConfirmView, { global: { plugins: [ElementPlus] } })
    await flushPromises()
    const vm = wrapper.vm as unknown as { confirmationErrors: string[]; confirmAndContinue: () => Promise<void> }

    expect(vm.confirmationErrors).toEqual(['第 1 行缺少：采购单价'])
    expect(wrapper.find('.review-card').exists()).toBe(false)
    await vm.confirmAndContinue()
    expect(alert).toHaveBeenCalledTimes(1)
    expect(alert.mock.calls[0]?.[1]).toBe('请完善采购信息')
    expect(api.updatePurchaseOrder).not.toHaveBeenCalled()
    expect(api.confirmVersionedPurchaseOrder).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('旧米制管材的单价仍明确按元每米显示', async () => {
    const wrapper = mount(PurchaseOrderConfirmView, { global: { plugins: [ElementPlus], stubs: { ElDatePicker: true } } })
    await flushPromises()
    try {
      expect(wrapper.findAll('.el-input-group__append').map(node => node.text())).toContain('元/米')
      expect(wrapper.text()).not.toContain('元/kg')
      expect(wrapper.get('input[aria-label="实际采购数量（米）"]').element).toHaveProperty('value', '284.16')
      expect(wrapper.find('[aria-label="实际采购根数"]').exists()).toBe(false)
      expect(wrapper.get('.quantity-cell').text()).not.toContain('根')
    } finally { wrapper.unmount() }
  })

  it('旧米制输入保持米单价，非整根米数不保存或取整', async () => {
    const wrapper = mount(PurchaseOrderConfirmView, { global: { plugins: [ElementPlus], stubs: { ElDatePicker: true } } })
    await flushPromises()
    try {
      const vm = wrapper.vm as unknown as { order: { lines: Array<{ actual_bar_count: string; unit_price: string }> }; confirmationErrors: string[]; totalScaled: bigint; saveChanges: (success: boolean) => Promise<boolean> }
      const input = wrapper.get('input[aria-label="实际采购数量（米）"]')
      await input.setValue('5')
      expect(vm.confirmationErrors.join(' ')).toContain('每根长度的整数倍')
      expect(await vm.saveChanges(false)).toBe(false)
      expect(api.updatePurchaseOrder).not.toHaveBeenCalled()
      await input.setValue('5.92')
      vm.order.lines[0]!.unit_price = '2'
      expect(vm.order.lines[0]!.actual_bar_count).toBe('2')
      expect(vm.totalScaled).toBe(118400n)
      vi.mocked(api.updatePurchaseOrder).mockResolvedValue({ data: vm.order, etag: 'version-2' } as never)
      expect(await vm.saveChanges(false)).toBe(true)
      expect(vi.mocked(api.updatePurchaseOrder).mock.calls[0]![1].lines[0]).toMatchObject({ actual_bar_count: '2', actual_purchase_quantity: null })
    } finally { wrapper.unmount() }
  })

  it('保存时不回传已经隐藏的历史差异原因', async () => {
    const wrapper = shallowMount(PurchaseOrderConfirmView, { global: { plugins: [ElementPlus] } })
    await flushPromises()
    const vm = wrapper.vm as unknown as {
      order: { lines: Array<{ quantity_difference_reason: string }> }
      saveChanges: (showSuccess: boolean) => Promise<boolean>
    }
    vm.order.lines[0]!.quantity_difference_reason = '历史记录'
    vi.mocked(api.updatePurchaseOrder).mockResolvedValue({ data: vm.order, etag: 'version-2' } as never)

    expect(await vm.saveChanges(false)).toBe(true)
    const payload = vi.mocked(api.updatePurchaseOrder).mock.calls[0]?.[1]
    expect(payload?.lines[0]).not.toHaveProperty('quantity_difference_reason')
    wrapper.unmount()
  })

  it.each(['SAMPLE', 'PRODUCTION'])('%s 管材再次保存保留对应的根数和长度契约', async (sourceType) => {
    const wrapper = shallowMount(PurchaseOrderConfirmView, { global: { plugins: [ElementPlus] } })
    await flushPromises()
    const vm = wrapper.vm as unknown as {
      order: { source_type: string; lines: Array<{ actual_bar_count: number; raw_bar_length_m: string }> }
      saveChanges: (showSuccess: boolean) => Promise<boolean>
    }
    vm.order.source_type = sourceType
    vm.order.lines[0]!.actual_bar_count = 4
    vm.order.lines[0]!.raw_bar_length_m = '3.05'
    vi.mocked(api.updatePurchaseOrder).mockResolvedValue({ data: vm.order, etag: 'version-2' } as never)

    try {
      expect(await vm.saveChanges(false)).toBe(true)
      const call = vi.mocked(api.updatePurchaseOrder).mock.calls[0]!
      expect(call[2]).toBe('version-1')
      expect(call[1].lines[0]).toMatchObject({ actual_bar_count: 4, actual_purchase_quantity: null })
      if (sourceType === 'SAMPLE') {
        expect(call[1].lines[0]).toHaveProperty('raw_bar_length_m', '3.05')
      } else {
        expect(call[1].lines[0]).not.toHaveProperty('raw_bar_length_m')
      }
    } finally {
      wrapper.unmount()
    }
  })

  it.each(['个', '片'])('五金实际KG改变时不显示%s参考，金额仍按KG', async unit => {
    const data = { id: 'order-1', status: 'DRAFT', source_type: 'PRODUCTION', currency_code: 'CNY', product_summary: [],
      lines: [{ id: 'hardware-1', line_number: 1, part_name: unit === '片' ? '垫片' : '铆钉', section_type: 'ACCESSORY', section_title: '五金件', source_unit_text: 'KG',
        actual_purchase_quantity: '3.96', unit_price: '8.5', raw_bar_length_m: null, supplier_id: 'supplier-1', delivery_date: '2026-12-01',
        calculation_snapshot: { measurement_kind: 'HARDWARE_WEIGHT', hardware_quantity_unit: unit, hardware_unit_weight_kg: '0.00396000' } }] }
    vi.mocked(api.fetchVersionedPurchaseOrder).mockResolvedValue({ data, etag: 'version-1' } as never)
    const wrapper = mount(PurchaseOrderConfirmView, { global: { plugins: [ElementPlus] } })
    try {
      await flushPromises()
      expect(wrapper.find('.hardware-quantity-reference').exists()).toBe(false)
      await wrapper.get('[aria-label="第 1 行实际采购重量（kg）"]').setValue('4')
      await flushPromises()
      expect(wrapper.text()).not.toContain('（参考）')
      const vm = wrapper.vm as any
      expect(vm.lineAmount(vm.order.lines[0])).toContain('34')
      expect(vm.order.lines[0].calculation_snapshot.hardware_unit_weight_kg).toBe('0.00396000')
    } finally { wrapper.unmount() }
  })

  it('保存并确认后直接进入该订单供应商采购表，不进入模板选择页', async () => {
    const initial = await api.fetchVersionedPurchaseOrder('order-1')
    initial.data.lines[0]!.unit_price = '2'
    vi.mocked(api.updatePurchaseOrder).mockResolvedValue({ data: initial.data, etag: 'version-2' })
    vi.mocked(api.confirmVersionedPurchaseOrder).mockResolvedValue({ data: { ...initial.data, status: 'SUBMITTED' }, etag: 'version-3' })
    vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue('confirm' as never)
    const wrapper = shallowMount(PurchaseOrderConfirmView, { global: { plugins: [ElementPlus] } })
    try {
      await flushPromises()
      await (wrapper.vm as any).confirmAndContinue()
      expect(api.updatePurchaseOrder).toHaveBeenCalledTimes(1)
      expect(api.confirmVersionedPurchaseOrder).toHaveBeenCalledExactlyOnceWith('order-1')
      expect(navigation.push).toHaveBeenCalledExactlyOnceWith({ name: 'supplier-purchase-sheets', query: { purchase_order_id: 'order-1' } })
      expect(wrapper.text()).not.toContain('选择模板')
    } finally { wrapper.unmount() }
  })
})
