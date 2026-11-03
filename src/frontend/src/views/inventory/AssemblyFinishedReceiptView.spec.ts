import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { AxiosError } from 'axios'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import AssemblyFinishedReceiptView from './AssemblyFinishedReceiptView.vue'

const identity = vi.hoisted(() => ({ user: { id: 7 }, initialized: true, identityReady: true, identityGeneration: 0, identityRequestGeneration: 0 }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => identity }))
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
  Object.assign(identity, { user: { id: 7 }, initialized: true, identityReady: true, identityGeneration: 0, identityRequestGeneration: 0 })
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
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()); vi.restoreAllMocks() })
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
    sessionStorage.setItem(`assembly-receipt:${planId}:user:7`, JSON.stringify({ etag: '"receipt-1"', payload }))
    api.preview.mockRejectedValue(new AxiosError('网络不可用'))
    const { wrapper, vm } = await form()
    expect(wrapper.findAll('button').find(button => button.text() === '核对本次提交')!.attributes('disabled')).toBeUndefined()
    await vm.submit()
    expect(api.submit).toHaveBeenCalledExactlyOnceWith(payload, '"receipt-1"')
  })
})

describe('成品入库提交恢复', () => {
  it.each(['', '{broken', '{"payload":{"request_id":"historical-uuid","quantity":2},"etag":"old"}'])('无主历史pending逐字保留、无恢复请求且禁止新UUID提交 %j', async raw => {
    const key = `assembly-receipt:${planId}`
    sessionStorage.setItem(key, raw)
    const { vm, wrapper } = await form()
    await vm.submit()
    expect(wrapper.text()).toContain('管理员人工核对')
    expect(api.preview).not.toHaveBeenCalled(); expect(api.submit).not.toHaveBeenCalled()
    expect(sessionStorage.getItem(key)).toBe(raw)
    expect(sessionStorage.getItem(`${key}:user:7`)).toBeNull()
  })
  it('存储写入失败必须在POST之前停止，不回退临时UUID请求', async () => {
    const { vm } = await form()
    vi.spyOn(Storage.prototype, 'setItem').mockImplementationOnce(() => { throw new Error('storage denied') })
    await vm.submit(); expect(api.submit).not.toHaveBeenCalled()
    expect(sessionStorage.getItem(`assembly-receipt:${planId}:user:7`)).toBeNull()
  })
  it('成功后存储删除异常保留原pending并锁定，不能再发第二个请求', async () => {
    const { vm } = await form()
    vi.spyOn(Storage.prototype, 'removeItem').mockImplementationOnce(() => { throw new Error('storage denied') })
    await vm.submit()
    const raw = sessionStorage.getItem(`assembly-receipt:${planId}:user:7`)
    expect(raw).not.toBeNull(); await vm.submit()
    expect(api.submit).toHaveBeenCalledTimes(1)
    expect(sessionStorage.getItem(`assembly-receipt:${planId}:user:7`)).toBe(raw)
  })
  it('A提交晚回包不能清除A原pending或触发B刷新', async () => {
    const { vm } = await form()
    let finish!: (value: unknown) => void
    api.submit.mockReturnValueOnce(new Promise(resolve => { finish = resolve }))
    const operation = vm.submit(); await flushPromises()
    const key = `assembly-receipt:${planId}:user:7`, raw = sessionStorage.getItem(key)
    identity.user = { id: 8 }; identity.identityGeneration++; identity.identityRequestGeneration++
    finish({ receipt_number: 'late-A' }); await operation
    expect(sessionStorage.getItem(key)).toBe(raw)
    expect(api.preview).toHaveBeenCalledTimes(1)
    expect(sessionStorage.getItem(`assembly-receipt:${planId}:user:8`)).toBeNull()
  })
  it('成功回包只消耗捕获原文，后写入的pending保持锁定', async () => {
    const { vm } = await form()
    let finish!: (value: unknown) => void
    api.submit.mockReturnValueOnce(new Promise(resolve => { finish = resolve }))
    const operation = vm.submit(); await flushPromises()
    const key = `assembly-receipt:${planId}:user:7`
    sessionStorage.setItem(key, 'newer-pending')
    finish({ receipt_number: 'confirmed' }); await operation
    expect(sessionStorage.getItem(key)).toBe('newer-pending')
    await vm.submit(); expect(api.submit).toHaveBeenCalledTimes(1)
  })
  it('原请求已删除时展示服务端原因并解锁，主动再提交才使用新编号', async () => {
    const { wrapper, vm } = await form()
    api.submit.mockRejectedValueOnce(new AxiosError('响应丢失', 'ECONNABORTED'))
    await vm.submit()
    const original = api.submit.mock.calls[0]!
    const message = '本次待入库记录已删除，不能重复提交；如需重新入库，请重新填写。'
    api.submit.mockRejectedValueOnce(Object.assign(new AxiosError(message), {
      response: { status: 409, data: { error: { code: 'RECEIPT_REQUEST_DELETED', message } } },
    }))
    await flushPromises()
    await wrapper.findAll('button').find(button => button.text() === '核对本次提交')!.trigger('click')
    await flushPromises()

    expect(api.submit.mock.calls[1]).toEqual(original)
    expect(api.submit).toHaveBeenCalledTimes(2)
    expect(vm.pending).toBeNull()
    expect(sessionStorage.getItem(`assembly-receipt:${planId}:user:7`)).toBeNull()
    expect(wrapper.text()).toContain(message)
    expect(wrapper.getComponent({ name: 'ElForm' }).props('disabled')).toBe(false)
    expect(wrapper.text()).not.toContain('核对本次提交')

    vm.quantity = '3'
    await wrapper.findAll('button').find(button => button.text() === '提交待入库')!.trigger('click')
    await flushPromises()
    expect(api.submit).toHaveBeenCalledTimes(3)
    expect(api.submit.mock.calls[2]![0].request_id).not.toBe(original[0].request_id)
    expect(api.submit.mock.calls[2]![0].received_quantity).toBe(3)
  })

  it.each(['RECEIPT_REQUEST_CONFLICT', undefined])('其他未确认409（%s）仍保留原请求和锁定状态', async code => {
    const { wrapper, vm } = await form()
    api.submit.mockRejectedValueOnce(Object.assign(new AxiosError('请求冲突'), {
      response: { status: 409, data: { error: { code, message: '请求冲突' } } },
    }))
    await vm.submit(); await flushPromises()

    expect(vm.pending?.payload).toEqual(api.submit.mock.calls[0]![0])
    expect(sessionStorage.getItem(`assembly-receipt:${planId}:user:7`)).not.toBeNull()
    expect(wrapper.getComponent({ name: 'ElForm' }).props('disabled')).toBe(true)
    expect(wrapper.text()).toContain('核对本次提交')
    expect(api.submit).toHaveBeenCalledTimes(1)
  })

  it.each([409, 412])('原有确定失败（状态%s）仍展示原因并清除待核对请求', async status => {
    const { wrapper, vm } = await form()
    api.submit.mockRejectedValueOnce(Object.assign(new AxiosError('额度已变化'), {
      response: { status, data: { error: { code: 'CONFLICT', message: '额度已变化' } } },
    }))
    await vm.submit(); await flushPromises()

    expect(vm.pending).toBeNull()
    expect(sessionStorage.getItem(`assembly-receipt:${planId}:user:7`)).toBeNull()
    expect(wrapper.text()).toContain('额度已变化')
    expect(wrapper.getComponent({ name: 'ElForm' }).props('disabled')).toBe(false)
    expect(api.submit).toHaveBeenCalledTimes(1)
  })
})
