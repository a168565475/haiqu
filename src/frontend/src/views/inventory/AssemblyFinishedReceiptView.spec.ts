import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import AssemblyFinishedReceiptView from './AssemblyFinishedReceiptView.vue'

const api = vi.hoisted(() => ({ preview: vi.fn(), submit: vi.fn(), options: vi.fn() }))
vi.mock('vue-router', () => ({ useRoute: () => ({ query: { schedule_product_id: 'plan-1' } }), useRouter: () => ({ push: vi.fn() }) }))
vi.mock('@/api/finishedReceipts', () => ({ fetchAssemblyPreview: api.preview, submitAssemblyReceipt: api.submit }))
vi.mock('@/api/inventory', () => ({ fetchInventoryOptions: api.options }))

const preview = {
  schedule_product_id: 'plan-1', actual_color: '', receipt_date: '2026-09-29', received_total: 0,
  maximum_receivable: 10, remaining_receivable: 10, order_maximum: 10, reported_minimum: 10,
  order_quantity: 10, tolerance_percent: '0', unit_name: '张', etag: '"receipt-1"',
}
const wrappers: ReturnType<typeof mount>[] = []
beforeEach(() => {
  vi.resetAllMocks()
  sessionStorage.clear()
  api.preview.mockResolvedValue({ ...preview })
  api.submit.mockResolvedValue({ id: 'receipt-1', receipt_number: 'RK-TEST', replayed: false })
  api.options.mockResolvedValue({
    warehouses: [{ id: 'warehouse-1', warehouse_name: '成品仓', warehouse_type: 'FINISHED', status: 'ACTIVE' }],
    zones: [{ id: 'zone-1', warehouse: 'warehouse-1', zone_name: '库区', status: 'ACTIVE' }],
    locations: [{ id: 'location-1', zone: 'zone-1', warehouse_id: 'warehouse-1', location_number: 'A1', status: 'ACTIVE', remaining_box_slots: null }],
  })
})
afterEach(() => wrappers.splice(0).forEach(wrapper => wrapper.unmount()))
async function form() {
  const wrapper = mount(AssemblyFinishedReceiptView, { global: { plugins: [ElementPlus] } })
  wrappers.push(wrapper)
  await flushPromises()
  const vm = wrapper.vm as any
  vm.quantity = '2'; vm.zone = 'zone-1'; vm.location = 'location-1'
  return { wrapper, vm }
}

describe('成品入库颜色选填', () => {
  it.each(['', '灰色'])('颜色为“%s”时正常提交并保留原值', async color => {
    api.preview.mockResolvedValue({ ...preview, actual_color: color })
    const { wrapper, vm } = await form()
    if (!color) expect(wrapper.text()).toContain('未填写（可留空）')
    await vm.submit()
    expect(api.submit).toHaveBeenCalledTimes(1)
    expect(api.submit.mock.calls[0]![0]).toMatchObject({ actual_color: color, received_quantity: 2, location_id: 'location-1' })
  })
  it('空颜色仍校验入库数量', async () => {
    const { vm } = await form()
    vm.quantity = '0'
    await vm.submit()
    expect(api.submit).not.toHaveBeenCalled()
    expect(vm.error).toContain('入库数量必须为正整数')
  })
  it('空颜色仍校验库位', async () => {
    const { vm } = await form()
    vm.location = ''
    await vm.submit()
    expect(api.submit).not.toHaveBeenCalled()
    expect(vm.error).toContain('有效的成品仓')
  })
})
