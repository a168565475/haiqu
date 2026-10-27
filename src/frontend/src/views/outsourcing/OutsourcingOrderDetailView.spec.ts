import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElMessageBox } from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import OutsourcingOrderDetailView from './OutsourcingOrderDetailView.vue'

const api = vi.hoisted(() => ({ fetch: vi.fn(), remove: vi.fn(), revoke: vi.fn(), push: vi.fn(), replace: vi.fn() }))
const auth = vi.hoisted(() => ({ permissions: new Set(['outsourcing.view_outsourcingorder']) }))
const route = vi.hoisted(() => ({ params: { orderId: 'order-1' }, path: '/workshop/outsourcing/order-1', query: {} as Record<string, string>, meta: { outsourcingWorkspace: 'workshop' } }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ user: { is_superuser: false }, hasPermission: (permission: string) => auth.permissions.has(permission) }) }))
vi.mock('@/api/outsourcing', () => ({ fetchOutsourcingOrder: api.fetch, deleteOutsourcingOrder: api.remove, revokeDispatchedOutsourcingOrder: api.revoke, outsourcingProductImageUrl: () => '' }))
vi.mock('vue-router', () => ({ useRoute: () => route, useRouter: () => ({ push: api.push, replace: api.replace }) }))
const baseDetail = {
  id: 'order-1', order_number: '原单-001', status: 'PARTIAL_RETURN', status_display: '部分回货', planned_amount: '25.0000',
  schedule_number: '排产-001', production_task_number: '任务-001', craft: { name: '喷塑', outsourcing_code: 'POWDER_COATING' },
  products: [{ id: 'product-1', product: { product_name: '桌子' }, image_file_id: null, planned_quantity: 100,
    processing_items: [{ id: 'part-1', part_name: '前脚管', allocations: [{ id: 'allocation-1', factory_id: 'factory-1',
      factory_name: '喷塑厂', unit: '支', allocated_quantity: '100', unit_price: '0.2500', planned_amount: '25.0000', materials: [],
    }] }],
  }],
  returns: [{ id: 'return-1', return_number: '回货-001', return_date: '2026-09-22', factory_name: '喷塑厂',
    lines: [{ allocation_id: 'allocation-1', quality: 'GOOD', returned_quantity: '24', unit: '支' }],
  }],
  dispatch: null, can_delete: true, can_revoke_dispatched: true, direct_handoff: true, direct_handoff_lock_reason: '金工直接交接，请从管材外发闭环登记合格回货。',
  direct_handoff_summary: [{ allocation_id: 'allocation-1', part_name: '前脚管', factory_id: 'factory-1', factory_name: '喷塑厂', unit: '支',
    handoff_pieces: 60, returned_good_pieces: 24, returned_unsprayed_pieces: 12, remaining_return_pieces: 24,
  }],
}
const wrappers: ReturnType<typeof mount>[] = []
async function createView(detail: Record<string, unknown> = structuredClone(baseDetail)) {
  api.fetch.mockResolvedValue({ data: detail, etag: '"order-1"' })
  const wrapper = mount(OutsourcingOrderDetailView, {
    global: { plugins: [ElementPlus], stubs: { OutsourcingFlowActions: true, MetalProcessingP4View: true } },
  })
  wrappers.push(wrapper)
  await flushPromises()
  return wrapper
}
beforeEach(() => { route.meta.outsourcingWorkspace = 'workshop'; vi.resetAllMocks(); route.query = {}; auth.permissions = new Set(['outsourcing.view_outsourcingorder']) })
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()); vi.restoreAllMocks() })

describe('原外发详情的直接交接展示及保护', () => {
  it('仓库仅有入库权限查看普通原料单仍读取普通详情，不误入金工投影', async () => {
    route.meta.outsourcingWorkspace = 'warehouse'
    auth.permissions = new Set(['outsourcing.confirm_return_outsourcingorder'])
    const wrapper = await createView({ ...structuredClone(baseDetail), direct_handoff: false })
    expect(api.fetch).toHaveBeenCalledWith('order-1', true)
    expect(wrapper.find('metal-processing-p4-view-stub').exists()).toBe(false)
    expect(wrapper.find('outsourcing-flow-actions-stub').exists()).toBe(true)
  })
  it('车间不能通过详情方法撤销并退料，仓库不显示永久删除', async () => {
    const detail = { ...structuredClone(baseDetail), direct_handoff: false, can_delete: false, can_revoke_dispatched: true }
    const workshop = await createView(detail)
    expect(workshop.find('.delete-order-button').exists()).toBe(false)
    await (workshop.vm as any).deleteOrder()
    expect(api.revoke).not.toHaveBeenCalled()
    route.meta.outsourcingWorkspace = 'warehouse'
    const warehouse = await createView({ ...detail, can_delete: true, can_revoke_dispatched: false })
    expect(warehouse.find('.delete-order-button').exists()).toBe(false)
    await (warehouse.vm as any).deleteOrder()
    expect(api.remove).not.toHaveBeenCalled()
  })
  it('同一加工厂不同部位按各分配显示真实单价，不把首行价格当成全厂统一价', async () => {
    const detail = structuredClone(baseDetail)
    const first = detail.products[0]!.processing_items[0]!
    detail.products[0]!.processing_items.push({ ...first, id: 'part-2', part_name: '后脚管', allocations: [{ ...first.allocations[0]!, id: 'allocation-2', unit_price: '0.5000', planned_amount: '50.0000' }] })
    detail.planned_amount = '75.0000'
    const wrapper = await createView(detail)
    const prices = wrapper.get('.order-price-card')
    expect(prices.text()).toContain('75 元')
    const rows = prices.findAll('.el-table__body tbody tr')
    expect(rows).toHaveLength(2)
    expect(rows[0]!.text()).toContain('0.25 元/支')
    expect(rows[1]!.text()).toContain('0.5 元/支')
    expect((wrapper.vm as any).factoryProgressRows).toHaveLength(1)
  })
  it('受限金工投影即使拥有普通权限也不请求可能越界的原单详情', async () => {
    auth.permissions.add('material_issues.view_metalprocessingsource')
    route.query = { view: 'metal' }
    const wrapper = await createView()
    expect(api.fetch).not.toHaveBeenCalled()
    expect(wrapper.find('.order-price-card').exists()).toBe(false)
    expect(wrapper.find('metal-processing-p4-view-stub').attributes('originalorderid')).toBe('order-1')
  })

  it('同时可看两种来源的直接交接原单在当前详情整合操作', async () => {
    auth.permissions.add('material_issues.view_metalprocessingsource')
    const wrapper = await createView()
    expect(api.fetch).toHaveBeenCalledOnce()
    expect(wrapper.find('metal-processing-p4-view-stub').exists()).toBe(true)
    expect(wrapper.find('outsourcing-flow-actions-stub').exists()).toBe(false)
    expect(wrapper.find('.order-record-grid').exists()).toBe(false)
  })

  it('按实交减合格减未喷塑退回显示24，仍保留原分配100', async () => {
    const wrapper = await createView()
    const vm = wrapper.vm as any
    expect(vm.allocationRows[0]).toMatchObject({ allocated_quantity: 100, handoff_quantity: 60, good_quantity: 24, unsprayed_quantity: 12, remaining_quantity: 24 })
    expect(vm.factoryProgressRows[0].remaining_quantity).toBe(24)
    expect(wrapper.text()).toContain('金工直接交接')
    expect(wrapper.text()).toContain('实际交接')
    expect(wrapper.text()).toContain('未喷塑退回')
    expect(wrapper.text()).toContain('不重复执行仓库原料发料')
    expect(vm.allocationStage(vm.allocationRows[0])).toBe('部分回货')
    expect(wrapper.get('[data-testid="original-direct-handoff-note"]').text()).toContain('金工来源权限')
  })

  it('没有仓库发料记录但已直接交接时显示加工中', async () => {
    const detail = structuredClone(baseDetail)
    detail.status = 'PROCESSING'; detail.status_display = '加工中'; detail.returns = []
    detail.direct_handoff_summary[0]!.returned_good_pieces = 0
    detail.direct_handoff_summary[0]!.remaining_return_pieces = 48
    const wrapper = await createView(detail)
    const vm = wrapper.vm as any
    expect(vm.allocationStage(vm.allocationRows[0])).toBe('加工中')
    expect(vm.allocationStageTone(vm.allocationRows[0])).toBe('processing')
    expect(vm.workflowCurrentIndex).toBe(2)
  })

  it('当前交接处理完仍展示后端部分回货状态，不自行宣称已结清', async () => {
    const detail = structuredClone(baseDetail)
    detail.direct_handoff_summary[0]!.returned_good_pieces = 48
    detail.direct_handoff_summary[0]!.remaining_return_pieces = 0
    const wrapper = await createView(detail)
    const vm = wrapper.vm as any
    expect(vm.allocationStage(vm.allocationRows[0])).toBe('当前交接已处理')
    expect(vm.detail.status).toBe('PARTIAL_RETURN')
    expect(wrapper.text()).not.toContain('回货已齐·待结清')
  })

  it('未交接分配不以计划量冒充当前待回数量', async () => {
    const detail = structuredClone(baseDetail)
    detail.direct_handoff_summary = []
    const wrapper = await createView(detail)
    const vm = wrapper.vm as any
    expect(vm.allocationRows[0].remaining_quantity).toBe(0)
    expect(vm.allocationStage(vm.allocationRows[0])).toBe('待交接')
  })

  it('直接交接即使旧can_delete仍为真也不渲染删除且不能调用删除方法', async () => {
    const wrapper = await createView()
    const confirm = vi.spyOn(ElMessageBox, 'confirm')
    expect(wrapper.find('.delete-order-button').exists()).toBe(false)
    await (wrapper.vm as any).deleteOrder()
    expect(confirm).not.toHaveBeenCalled()
    expect(api.remove).not.toHaveBeenCalled()
    expect(api.revoke).not.toHaveBeenCalled()
  })

  it('普通已发料单撤销前重取版本，填写原因后退料并保留已取消详情', async () => {
    route.meta.outsourcingWorkspace = 'warehouse'
    const detail = { ...structuredClone(baseDetail), direct_handoff: false, can_delete: false, can_revoke_dispatched: true, status: 'PROCESSING', status_display: '加工中', returns: [], dispatch: { id: 'dispatch-1', dispatch_date: '2026-09-22', lines: [] } }
    const wrapper = await createView(detail)
    const latest = { ...detail, version: 2 }
    api.fetch.mockResolvedValueOnce({ data: latest, etag: '"order-2"' })
    api.revoke.mockResolvedValue({ data: { ...latest, status: 'CANCELLED', status_display: '已取消', can_revoke_dispatched: false }, etag: '"order-3"' })
    vi.spyOn(ElMessageBox, 'prompt').mockResolvedValue({ value: ' 误发，退回仓库 ', action: 'confirm' } as never)
    await (wrapper.vm as any).deleteOrder()
    expect(api.fetch).toHaveBeenCalledTimes(2)
    expect(api.revoke).toHaveBeenCalledWith('order-1', '误发，退回仓库', expect.any(String), '"order-2"')
    expect(api.remove).not.toHaveBeenCalled()
    expect((wrapper.vm as any).detail.status).toBe('CANCELLED')
    expect(wrapper.text()).toContain('未用原料已退回原批次库存')
    const progressRow = wrapper.find('.order-progress-card .el-table__body tr')
    expect(progressRow.findAll('td').at(-2)?.text()).toBe('—')
    expect(progressRow.findAll('td').at(-1)?.text()).toContain('已作废')
    expect(wrapper.find('.order-progress-card .el-table__footer-wrapper').exists()).toBe(false)
    expect(api.replace).not.toHaveBeenCalled()
  })

  it('普通未发料单仍执行永久删除，不调用已发料退料接口', async () => {
    const detail = { ...structuredClone(baseDetail), direct_handoff: false, can_delete: true, can_revoke_dispatched: false, status: 'PENDING_DISPATCH', returns: [] }
    const wrapper = await createView(detail)
    api.fetch.mockResolvedValueOnce({ data: detail, etag: '"order-2"' })
    vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue('confirm' as never)
    await (wrapper.vm as any).deleteOrder()
    expect(api.remove).toHaveBeenCalledWith('order-1', '"order-2"')
    expect(api.revoke).not.toHaveBeenCalled()
    expect(api.replace).toHaveBeenCalledWith('/workshop/outsourcing')
  })

  it('普通外发详情保留原分配减回货计算、旧流程名和删除按钮', async () => {
    const detail = structuredClone(baseDetail)
    detail.direct_handoff = false
    const wrapper = await createView(detail)
    const vm = wrapper.vm as any
    expect(vm.allocationRows[0].remaining_quantity).toBe(76)
    expect(vm.workflowSteps[1]).toBe('仓库外发')
    expect(wrapper.find('.delete-order-button').exists()).toBe(true)
    expect(wrapper.find('[data-testid="original-direct-handoff-note"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('未喷塑退回')
  })

  it('直接交接备注结清后显示可补登记，流程末步明确为备注结清', async () => {
    const detail = { ...structuredClone(baseDetail), status: 'CLOSED', status_display: '已结清' }
    const wrapper = await createView(detail)
    const vm = wrapper.vm as any
    expect(vm.allocationStage(vm.allocationRows[0])).toBe('已结清 · 可补登记')
    expect(vm.workflowSteps[4]).toBe('备注结清')
    expect(vm.workflowCurrentIndex).toBe(4)
    expect(vm.statusTone('CLOSED')).toBe('cancelled')
  })

  it('直接交接回齐与普通旧流程结清文案分别保持正确', async () => {
    const completed = { ...structuredClone(baseDetail), status: 'COMPLETED', status_display: '已完成' }
    const directVm = (await createView(completed)).vm as any
    expect(directVm.allocationStage(directVm.allocationRows[0])).toBe('已回齐')
    const legacyVm = (await createView({ ...completed, direct_handoff: false })).vm as any
    expect(legacyVm.allocationStage(legacyVm.allocationRows[0])).toBe('已结清')
  })
})
