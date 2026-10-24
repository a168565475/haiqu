import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { AxiosError } from 'axios'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import AssemblyFinishedReceiptView from './AssemblyFinishedReceiptView.vue'

const api = vi.hoisted(() => ({ preview: vi.fn(), submit: vi.fn(), options: vi.fn() }))
const route = vi.hoisted(() => ({ query: {} as Record<string, string | string[] | null | undefined> }))
vi.mock('vue-router', () => ({ useRoute: () => route, useRouter: () => ({ push: vi.fn() }) }))
vi.mock('@/api/finishedReceipts', () => ({ fetchAssemblyPreview: api.preview, submitAssemblyReceipt: api.submit }))
vi.mock('@/api/inventory', () => ({ fetchInventoryOptions: api.options }))

const planId = '86e0c84b-a809-4689-845b-806012ad342c'
const preview = {
  schedule_product_id: planId, actual_color: '', receipt_date: '2026-09-29', received_total: 0,
  maximum_receivable: 10, remaining_receivable: 10, order_maximum: 10, reported_minimum: 10,
  order_quantity: 10, tolerance_percent: '0', unit_name: '张', etag: '"receipt-1"',
}
const wrappers: ReturnType<typeof mount>[] = []
beforeEach(() => {
  vi.resetAllMocks()
  route.query = { schedule_product_id: planId }
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

describe('成品入库来源参数', () => {
  it.each([
    undefined, null, '', 'plan-1', ` ${planId}`, [planId], [planId, planId],
  ].map(source => [source]))('无效或重复来源 %j 不请求预览和库位，也不能提交', async source => {
    route.query = { schedule_product_id: source }
    const { wrapper, vm } = await form()
    expect(wrapper.text()).toContain('请从装配内部计划的产品行进入成品入库')
    expect(wrapper.findAll('button').find(button => button.text() === '提交待入库')!.attributes('disabled')).toBeDefined()
    await vm.load()
    await vm.submit()
    expect(api.preview).not.toHaveBeenCalled()
    expect(api.options).not.toHaveBeenCalled()
    expect(api.submit).not.toHaveBeenCalled()
  })
  it('合法单值来源仍按原参数请求预览和库位', async () => {
    await form()
    expect(api.preview).toHaveBeenCalledExactlyOnceWith(planId)
    expect(api.options).toHaveBeenCalledTimes(1)
    expect(api.submit).not.toHaveBeenCalled()
  })
  it.each([400, 409])('合法来源被后端以 %s 拦截时保留提示且不能新提交', async status => {
    const message = '只有生产中的订单产品可以办理成品入库。'
    api.preview.mockRejectedValue(Object.assign(new AxiosError(message), { response: { status, data: { error: { message } } } }))
    const { wrapper, vm } = await form()
    expect(wrapper.text()).toContain(message)
    expect(wrapper.findAll('button').find(button => button.text() === '提交待入库')!.attributes('disabled')).toBeDefined()
    await vm.submit()
    expect(api.submit).not.toHaveBeenCalled()
  })
  it('合法来源已有待核对请求时，预览失败仍可用原编号核对', async () => {
    const payload = { request_id: 'pending-receipt', schedule_product_id: planId, location_id: 'location-1', receipt_date: '2026-09-29', received_quantity: 2, quantity_per_box: null, actual_color: '', remark: '' }
    sessionStorage.setItem(`assembly-receipt:${planId}`, JSON.stringify({ etag: '"receipt-1"', payload }))
    api.preview.mockRejectedValue(new AxiosError('网络不可用'))
    const { wrapper, vm } = await form()
    expect(wrapper.findAll('button').find(button => button.text() === '核对本次提交')!.attributes('disabled')).toBeUndefined()
    await vm.submit()
    expect(api.submit).toHaveBeenCalledExactlyOnceWith(payload, '"receipt-1"')
  })
})
