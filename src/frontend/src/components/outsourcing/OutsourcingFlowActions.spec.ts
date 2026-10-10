import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { OutsourcingOrderDetail } from '@/types/outsourcing'
import OutsourcingFlowActions from './OutsourcingFlowActions.vue'

const api = vi.hoisted(() => ({ context: vi.fn(), reconciliation: vi.fn(), options: vi.fn(), dispatch: vi.fn(), returned: vi.fn(), flow: vi.fn() }))
vi.mock('@/api/outsourcing', () => ({
  fetchOutsourcingDispatchContext: api.context, fetchOutsourcingReconciliation: api.reconciliation,
  fetchOutsourcingOptions: api.options, confirmOutsourcingDispatch: api.dispatch,
  confirmOutsourcingReturn: api.returned, confirmOutsourcingFlow: api.flow,
}))
const detail = {
  id: 'order-1', direct_handoff: false, can_confirm_dispatch: true, can_confirm_return: true,
  can_return_raw: true, can_reconcile: true, can_complete: true, dispatch: { id: 'dispatch-1' },
} as OutsourcingOrderDetail
const wrappers: ReturnType<typeof mount>[] = []
function createView(overrides: Partial<OutsourcingOrderDetail> = {}) {
  const wrapper = mount(OutsourcingFlowActions, {
    props: { detail: { ...detail, ...overrides }, etag: '"order-1"' },
    global: { plugins: [ElementPlus], stubs: { AppWindowDialog: { props: ['modelValue'], template: '<section v-if="modelValue"><slot/><slot name="footer"/></section>' } } },
  })
  wrappers.push(wrapper)
  return wrapper
}
beforeEach(() => {
  vi.resetAllMocks()
  api.context.mockResolvedValue({ materials: [] })
  api.reconciliation.mockResolvedValue({ outputs: [], raw_materials: [] })
  api.options.mockResolvedValue({ receivers: [], semi_finished_zones: [], defective_zones: [] })
})
afterEach(() => wrappers.splice(0).forEach(wrapper => wrapper.unmount()))

describe('旧外发入口门禁', () => {
  it('直接交接即使携带旧的可操作标记，也不渲染旧流程按钮', () => {
    const wrapper = createView({ direct_handoff: true })
    expect(wrapper.findAll('button')).toHaveLength(0)
  })

  it.each(['dispatch', 'return', 'raw', 'record', 'complete'])('直接交接禁止通过 %s 方法绕开入口', async mode => {
    const wrapper = createView({ direct_handoff: true, direct_handoff_lock_reason: '金工直接交接，请从管材工作台回货' })
    const vm = wrapper.vm as any
    await vm.open(mode)
    expect(vm.visible).toBe(false)
    vm.mode = mode
    await vm.load()
    await vm.submit()
    expect(vm.error).toContain('金工直接交接')
    for (const call of Object.values(api)) expect(call).not.toHaveBeenCalled()
  })

  it('普通外发的旧入口仍按原有权限显示并能打开', async () => {
    const wrapper = createView()
    const buttons = wrapper.findAll('.flow-actions button').map(button => button.text())
    expect(buttons).toEqual(['确认外发', '登记回货', '原料退回', '投入与损耗', '结清检查'])
    await wrapper.findAll('button').find(button => button.text() === '确认外发')!.trigger('click')
    await flushPromises()
    expect(api.context).toHaveBeenCalledWith('order-1')
    expect((wrapper.vm as any).visible).toBe(true)
  })

  it('普通单无对应能力时也不能直接调用打开方法', async () => {
    const wrapper = createView({ can_confirm_dispatch: false, can_confirm_return: false })
    const vm = wrapper.vm as any
    await vm.open('dispatch')
    await vm.open('return')
    expect(api.context).not.toHaveBeenCalled()
    expect(api.reconciliation).not.toHaveBeenCalled()
  })

  it('撤销后即使保留发料记录，也不显示或执行原流程操作', async () => {
    const wrapper = createView({ status: 'CANCELLED' })
    expect(wrapper.find('.flow-actions').exists()).toBe(false)
    await (wrapper.vm as any).open('complete')
    expect(api.reconciliation).not.toHaveBeenCalled()
    expect(api.flow).not.toHaveBeenCalled()
  })

  it('弹窗打开后单据转为直接交接时，提交和重试加载仍受限制', async () => {
    const wrapper = createView()
    const vm = wrapper.vm as any
    await vm.open('return')
    expect(api.reconciliation).toHaveBeenCalledTimes(1)
    await wrapper.setProps({ detail: { ...detail, direct_handoff: true } })
    await vm.submit()
    await vm.load()
    expect(api.returned).not.toHaveBeenCalled()
    expect(api.reconciliation).toHaveBeenCalledTimes(1)
    expect(wrapper.find('.flow-actions').exists()).toBe(false)
    expect(vm.error).toContain('不可执行')
  })
})

it('本次可领为零的空行不进入确认发料请求', async () => {
  const material = (id: string, max: string) => ({
    material_item_id: id, factory_name: '加工厂', material_name: id, specification: '', color: '', unit: '个',
    planned_issue_quantity: '10', max_issue_quantity: max, internal_issued_quantity: '0',
    outsourcing_issued_quantity: '0', order_remaining: max, available_stock: max, quota_error: '',
    procurement_unit: '个', conversion_snapshot: { schema_version: 2, kind: 'OTHER', raw_material_id: id },
    zones: max === '0' ? [] : [{ zone_id: 'zone-1', warehouse_name: '材料仓', zone_name: '一区',
      available_quantity: '10', available_input_quantity: '10', available_meters: null }],
  })
  api.context.mockResolvedValue({ materials: [material('available', '10'), material('empty', '0')] })
  api.dispatch.mockResolvedValue({})
  const wrapper = createView()
  const vm = wrapper.vm as any
  await vm.open('dispatch')
  vm.dispatchRows[0].quantity = '10'
  await vm.submit()

  expect(api.dispatch).toHaveBeenCalledTimes(1)
  expect(api.dispatch.mock.calls[0][1].lines).toEqual([
    { material_item_id: 'available', zone_id: 'zone-1', requested_quantity: '10' },
  ])

  api.dispatch.mockClear()
  api.context.mockResolvedValue({ materials: [material('available', '10'), material('required', '10')] })
  const requiredView = createView()
  const requiredVm = requiredView.vm as any
  await requiredVm.open('dispatch')
  requiredVm.dispatchRows[0].quantity = '10'
  await requiredVm.submit()
  expect(api.dispatch).not.toHaveBeenCalled()
  expect(requiredVm.error).toContain('required')
})

describe('公共回货仅接收合格半成品', () => {
  it.each(['PUBLIC_V2', 'LEGACY'] as const)('%s 的回货界面与提交保持对应口径', async stockMode => {
    api.reconciliation.mockResolvedValue({
      outputs: [{ factory_id: 'factory-1', factory_name: '车缝厂', allocation_id: 'allocation-1',
        component: '椅面裁片', unit: '套', remaining: '60' }],
      raw_materials: [{ factory_id: 'factory-1', factory_name: '车缝厂', allocation_id: 'allocation-1',
        dispatch_line_id: 'dispatch-line-1', component: '面料', unit: '米', conversion_snapshot: { kind: 'FABRIC' } }],
    })
    api.options.mockResolvedValue({ receivers: [{ id: 'receiver-1', name: '接收员' }],
      semi_finished_zones: [{ id: 'good-zone', name: '半成品仓' }],
      defective_zones: [{ id: 'bad-zone', name: '不良仓' }] })
    api.returned.mockResolvedValue({})
    const wrapper = createView({ stock_mode: stockMode })
    const vm = wrapper.vm as any
    await vm.open('return')
    await flushPromises()
    const isPublic = stockMode === 'PUBLIC_V2'
    expect(wrapper.text().includes('不良品库区')).toBe(!isPublic)
    expect(wrapper.text().includes('不良原因')).toBe(!isPublic)
    expect(wrapper.find('input[aria-label="不良数量"]').exists()).toBe(!isPublic)
    expect(wrapper.text().includes('进入公共半成品库存')).toBe(isPublic)
    vm.good['allocation-1'] = '60'
    vm.rawInputs['dispatch-line-1'] = '90'
    // 即使残留旧输入，公共回货也只能提交合格数量。
    vm.defective['allocation-1'] = '3'
    vm.defectReasons['allocation-1'] = '表面污损'
    vm.receipt.badZone = 'bad-zone'
    await vm.submit()
    expect(api.returned).toHaveBeenCalledTimes(1)
    const payload = api.returned.mock.calls[0][1]
    expect(payload.defective_zone_id).toBe(isPublic ? null : 'bad-zone')
    expect(payload.lines).toEqual([{ allocation_id: 'allocation-1', good_quantity: '60',
      defective_quantity: isPublic ? '0' : '3', defect_reason: isPublic ? '' : '表面污损' }])
    expect(payload.raw_inputs).toEqual([expect.objectContaining({ dispatch_line_id: 'dispatch-line-1', kind: 'RAW_INPUT', quantity: '90' })])
  })
})
