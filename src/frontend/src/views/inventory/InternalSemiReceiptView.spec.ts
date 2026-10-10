import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import InternalSemiReceiptView from './InternalSemiReceiptView.vue'

const api = vi.hoisted(() => ({ preview: vi.fn(), confirm: vi.fn() }))
vi.mock('vue-router', () => ({
  useRoute: () => ({ query: { schedule_product_id: 'plan-1', plan_category: 'SEWING' } }),
  useRouter: () => ({ push: vi.fn(), back: vi.fn() }),
}))
vi.mock('@/api/internalReceipts', () => ({
  fetchReceiptPreview: api.preview,
  confirmInternalReceipt: api.confirm,
}))

const preview = {
  schedule_product_id: 'plan-1', plan_category: 'SEWING', etag: '"receipt-1"',
  production_order: 'HT-001', product: '折叠椅', order_quantity: '100', actor: '仓管员',
  receipt_date: '2026-09-29', excluded: [],
  zones: [{ id: 'zone-1', warehouse: '半成品仓', name: '一楼' }],
  lines: [
    { bom_line_id: 'line-1', component_key: 'part-1', usage: '1', stage: '车缝完成', required: '100', received: '0', can_receive: '100', input_remaining: '100', input_supported: '100', attributes: { part_name: '椅套', category: '裁片', material: '涤纶', specification: '600D', color: '黑色', unit_name: '套' } },
    { bom_line_id: 'line-2', component_key: 'part-2', usage: '1', stage: '车缝完成', required: '100', received: '0', can_receive: '100', input_remaining: '100', input_supported: '100', attributes: { part_name: '靠背套', category: '裁片', material: '涤纶', specification: '600D', color: '黑色', unit_name: '套' } },
    { bom_line_id: 'line-3', component_key: 'part-3', usage: '1', stage: '车缝完成', required: '100', received: '0', can_receive: '100', input_remaining: '100', input_supported: '100', attributes: { part_name: '座套', category: '裁片', material: '涤纶', specification: '600D', color: '黑色', unit_name: '套' } },
  ],
}

const wrappers: ReturnType<typeof mount>[] = []

beforeEach(() => {
  vi.resetAllMocks()
  sessionStorage.clear()
  api.preview.mockResolvedValue(structuredClone(preview))
  api.confirm.mockResolvedValue({ receipt_number: 'RK-001' })
})
afterEach(() => wrappers.splice(0).forEach(wrapper => wrapper.unmount()))

describe('车缝半成品入库', () => {
  it('不显示勾选框，空白和零忽略，仅提交大于零的数量', async () => {
    const wrapper = mount(InternalSemiReceiptView, { global: { plugins: [ElementPlus] } })
    wrappers.push(wrapper)
    await flushPromises()

    expect(wrapper.find('input[type="checkbox"]').exists()).toBe(false)
    const vm = wrapper.vm as any
    vm.quantities = { 'line-1': '', 'line-2': '0', 'line-3': '5' }
    await vm.submit()

    expect(api.confirm).toHaveBeenCalledTimes(1)
    expect(api.confirm.mock.calls[0]![0].lines).toEqual([{ bom_line_id: 'line-3', quantity: '5' }])
  })

  it('所有数量为空或零时不提交', async () => {
    const wrapper = mount(InternalSemiReceiptView, { global: { plugins: [ElementPlus] } })
    wrappers.push(wrapper)
    await flushPromises()

    const vm = wrapper.vm as any
    vm.quantities = { 'line-1': '', 'line-2': '0' }
    await vm.submit()

    expect(api.confirm).not.toHaveBeenCalled()
    expect(vm.error).toContain('至少填写一项大于 0')
  })
})
