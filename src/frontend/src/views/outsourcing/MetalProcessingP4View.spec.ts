import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { AxiosError } from 'axios'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import MetalProcessingP4View from './MetalProcessingP4View.vue'

const auth = vi.hoisted(() => ({ superuser: true, permissions: new Set<string>() }))
const route = vi.hoisted(() => ({ query: {} as Record<string, string> }))
const router = vi.hoisted(() => ({ push: vi.fn() }))
const api = vi.hoisted(() => ({
  sources: vi.fn(), source: vi.fn(), orders: vi.fn(), options: vi.fn(), legacy: vi.fn(),
  handoff: vi.fn(), returned: vi.fn(), rework: vi.fn(), order: vi.fn(), externalHandoff: vi.fn(),
  goodReturn: vi.fn(), close: vi.fn(), stock: vi.fn(), handoffDetail: vi.fn(), originalGoodReturn: vi.fn(),
  externalOrder: vi.fn(), adjustAllocation: vi.fn(), sourceClosePreview: vi.fn(), sourceCompletion: vi.fn(), sourceClose: vi.fn(),
  originalOrder: vi.fn(), originalClose: vi.fn(), originalCancelPending: vi.fn(),
}))
vi.mock('vue-router', () => ({ useRoute: () => route, useRouter: () => router }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({
  user: { get is_superuser() { return auth.superuser } },
  hasPermission: (permission: string) => auth.permissions.has(permission),
}) }))
vi.mock('@/api/outsourcing', () => ({ fetchOutsourcingOptions: api.options, fetchOutsourcingOrders: api.legacy }))
vi.mock('@/api/metalProcessingP4', () => ({
  fetchP4Sources: api.sources, fetchP4Source: api.source, fetchP4ExternalOrders: api.orders,
  fetchP4Options: api.options, createP4OriginalHandoff: api.handoff, createP4UnsprayedReturn: api.returned,
  createP4Rework: api.rework, createP4ExternalOrder: api.order, confirmP4ExternalHandoff: api.externalHandoff,
  confirmP4GoodReturn: api.goodReturn, closeP4ExternalOrder: api.close, fetchP4SemiStock: api.stock,
  fetchP4Handoff: api.handoffDetail, confirmP4OriginalGoodReturn: api.originalGoodReturn,
  fetchP4ExternalOrder: api.externalOrder, adjustP4ExternalAllocation: api.adjustAllocation,
  fetchP4SourceClosurePreview: api.sourceClosePreview, registerP4SourceCompletion: api.sourceCompletion, closeP4Source: api.sourceClose,
  fetchP4OriginalOrder: api.originalOrder, closeP4OriginalOrder: api.originalClose, cancelP4OriginalPending: api.originalCancelPending,
  newP4RequestId: () => crypto.randomUUID(),
}))

const completedSource = {
  issue_line_id: 'line-1', source_id: 'source-1', issue_number: '领料-1', part_name: '前脚管',
  production_task_id: 'task-1', product_line_id: 'product-1', component_identity: 'part-1',
  issued_pieces: 12, completed_pieces: 12, dispatched_pieces: 0, reserved_pieces: 0,
  available_pieces: 12, remaining_completion_pieces: 0, status: 'OPEN', can_register: false,
  can_close: true, bar_count: 2, meters: '6.10', blockers: [], etag: '"source-1"', original_handoffs: [],
}
const goodContext = {
  etag: '"allocation-return-1"', original_order_id: 'original-order', original_order_number: '原单-001',
  original_order_status: 'PARTIAL_RETURN', allocation_id: 'allocation-1', part_name: '前脚管',
  factory_id: 'factory', factory_name: '喷塑厂', unit: '支', handoff_pieces: 60,
  returned_good_pieces: 24, returned_unsprayed_pieces: 12, remaining_return_pieces: 24,
  can_return: true, blockers: [], good_returns: [{ id: 'receipt-1', return_number: '回货-1', good_pieces: 24,
    zone_name: '半成品A区', received_by_employee_name: '接收人', return_date: '2026-09-22', remark: '',
  }],
}
const handoffDetail = { id: 'handoff-1', handoff_pieces: 12, returned_unsprayed_pieces: 0,
  original_order_id: 'original-order', original_order_number: '原单-001', original_order_status: 'PARTIAL_RETURN',
  source_etag: '"source-1"', remaining_return_pieces: 12, return_blockers: [], good_return_context: goodContext }
const wrappers: ReturnType<typeof mount>[] = []
async function createView(props: { mode?: 'sources' | 'original' | 'rework'; embedded?: boolean; originalOrderId?: string; externalOrderId?: string } = {}) {
  const wrapper = mount(MetalProcessingP4View, {
    props,
    global: { plugins: [ElementPlus], stubs: { AppWindowDialog: { template: '<section><slot/><slot name="footer"/></section>' } } },
  })
  wrappers.push(wrapper)
  await flushPromises()
  return wrapper
}
// 通过组件的方法操作弹窗，断言实际请求及重试结果，避免依赖 Element Plus 下拉定位。
function state(wrapper: ReturnType<typeof mount>): any { return wrapper.vm }

beforeEach(() => {
  vi.resetAllMocks()
  auth.superuser = true
  auth.permissions.clear()
  route.query = {}
  api.sources.mockResolvedValue({ data: [completedSource], meta: { total_pages: 1 } })
  api.source.mockResolvedValue(structuredClone(completedSource))
  api.orders.mockResolvedValue({ data: [], meta: { total_pages: 1 } })
  api.options.mockResolvedValue({
    factories: [{ id: 'factory', name: '喷塑厂', crafts: [{ id: 'craft' }] }],
    crafts: [{ id: 'craft', name: '喷塑', outsourcing_code: 'POWDER_COATING' }],
    receivers: [{ id: 'receiver', name: '接收人' }], semi_finished_zones: [], original_orders: [],
  })
  api.legacy.mockResolvedValue({ data: [], meta: { total_pages: 1 } })
  api.handoffDetail.mockResolvedValue(structuredClone(handoffDetail))
})
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()) })

describe('统一入口内的单据与来源范围', () => {
  it('来源页签嵌入时保留历史来源，且不再加载第二套全量外发单', async () => {
    api.sources.mockResolvedValue({ data: [{ ...completedSource, status: 'CLOSED' }], meta: { total_pages: 1 } })
    const wrapper = await createView({ mode: 'sources', embedded: true })
    expect(api.orders).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('全部来源（含历史）')
    expect(wrapper.find('h1').exists()).toBe(false)
    expect(wrapper.find('.orders-panel').exists()).toBe(false)
  })

  it('原单详情只显示该原单交接，整单收尾拒绝不隐藏合法来源', async () => {
    api.source.mockResolvedValue({ ...completedSource, original_handoffs: [
      { ...handoffDetail, factory_name: '本单加工厂', unsprayed_returns: [] },
      { ...handoffDetail, id: 'other-handoff', original_order_id: 'other-order', factory_name: '其他单加工厂', unsprayed_returns: [] },
    ] })
    api.originalOrder.mockRejectedValue(new Error('整单含不可访问来源'))
    const wrapper = await createView({ mode: 'original', embedded: true, originalOrderId: 'original-order' })
    expect(api.sources).toHaveBeenCalledWith(expect.objectContaining({ original_order_id: 'original-order' }))
    expect(api.orders).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('本单加工厂')
    expect(wrapper.text()).not.toContain('其他单加工厂')
    expect(wrapper.text()).toContain('整单含不可访问来源')
    expect(wrapper.findAll('button').some(button => button.text() === '登记合格回货')).toBe(true)
    expect(wrapper.find('.p4-layout').exists()).toBe(false)
  })

  it('重加工详情按新单和来源ID读取，计划分配不会显示为实际交接', async () => {
    api.externalOrder.mockResolvedValue({ id: 'new-order', order_number: '新单-99', source_id: 'source-1',
      original_return_id: 'return-1', rework_id: 'rework-1', factory_name: '喷塑厂', craft_name: '喷塑',
      allocated_pieces: 20, handoff_pieces: 0, returned_good_pieces: 0, remaining_return_pieces: 0,
      status: 'PENDING_HANDOFF', etag: '"new-order"', handoff: null, good_returns: [], closure: null,
      allocation_history: [],
    })
    const wrapper = await createView({ mode: 'rework', externalOrderId: 'new-order' })
    expect(api.externalOrder).toHaveBeenCalledWith('new-order')
    expect(api.sources).toHaveBeenCalledWith(expect.objectContaining({ source_id: 'source-1' }))
    expect(api.orders).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('新单-99')
    expect(wrapper.text()).toContain('尚未实际交接')
    expect(wrapper.get('[data-testid="unified-rework-detail"]').text()).toContain('实际交接0 支')
    expect(wrapper.find('.p4-layout').exists()).toBe(false)
  })

  it('重加工来源选择只打开匹配记录的录入弹窗，不自动写入', async () => {
    route.query = { source_issue_line_id: 'line-1', source_action: 'rework', rework_id: 'rework-1' }
    api.source.mockResolvedValue({ ...completedSource, original_handoffs: [{ ...handoffDetail,
      unsprayed_returns: [{ id: 'return-1', reworks: [{ id: 'rework-1', remaining_allocatable_pieces: 6 }] }],
    }] })
    const wrapper = await createView({ mode: 'sources', embedded: true })
    expect(state(wrapper).dialog).toBe('order')
    expect(state(wrapper).selectedRework.id).toBe('rework-1')
    expect(api.order).not.toHaveBeenCalled()
    expect(api.handoff).not.toHaveBeenCalled()
  })

  it('再外发补回齐后仍显示结清时冻结的差额', async () => {
    api.externalOrder.mockResolvedValue({ id: 'new-order', order_number: '新单-99', source_id: 'source-1',
      original_return_id: 'return-1', rework_id: 'rework-1', factory_name: '喷塑厂', craft_name: '喷塑',
      allocated_pieces: 5, handoff_pieces: 5, returned_good_pieces: 5, remaining_return_pieces: 0,
      status: 'COMPLETED', etag: '"new-order"',
      handoff: { id: 'new-handoff', handoff_pieces: 5, handoff_date: '2026-09-27' },
      good_returns: [
        { id: 'return-before-close', return_number: '回货-1', return_date: '2026-09-27', good_pieces: 2, post_closure: false },
        { id: 'return-after-close', return_number: '回货-2', return_date: '2026-09-28', good_pieces: 3, post_closure: true },
      ],
      closure: { id: 'closure-1', remark: '保留差额结清', created_at: '2026-09-27T16:00:00+08:00',
        quantity_snapshot: { handoff_pieces: 5, returned_good_pieces: 2, difference_pieces: 3 } },
      allocation_history: [],
    })
    const wrapper = await createView({ mode: 'rework', externalOrderId: 'new-order' })
    const detail = wrapper.get('[data-testid="unified-rework-detail"]')
    expect(detail.get('.metric-grid').text()).toContain('当前待回0 支')
    const closureTab = detail.findAll('[role="tab"]').find(tab => tab.text() === '结清记录')!
    await closureTab.trigger('click')
    await flushPromises()
    const history = detail.get('.source-closure-record')
    expect(history.isVisible()).toBe(true)
    expect(history.text()).toContain('结清时剩余 3 支，历史差额保留。')
  })

  it('失效的来源定位明确报错，不替用户改选其他领料部位', async () => {
    route.query = { source_issue_line_id: 'missing-line' }
    const wrapper = await createView({ mode: 'sources', embedded: true })
    expect(wrapper.text()).toContain('所选金工来源已不可访问')
    expect(api.source).not.toHaveBeenCalled()
    expect(state(wrapper).source).toBeNull()
  })

  it('重加工详情回货成功重取本单和已展开库存，不重载全部外发单', async () => {
    const order = { id: 'new-order', order_number: '新单-99', source_id: 'source-1',
      original_return_id: 'return-1', rework_id: 'rework-1', factory_name: '喷塑厂', craft_name: '喷塑',
      allocated_pieces: 12, handoff_pieces: 12, returned_good_pieces: 0, remaining_return_pieces: 12,
      status: 'PROCESSING', etag: '"new-order"', handoff: { id: 'new-handoff', handoff_pieces: 12, handoff_date: '2026-09-27' }, good_returns: [], closure: null,
      allocation_history: [],
    }
    api.externalOrder.mockResolvedValue(order)
    api.stock.mockResolvedValue({ part_name: '前脚管', available_pieces: 0, zones: [] })
    const wrapper = await createView({ mode: 'rework', externalOrderId: 'new-order' })
    const vm = state(wrapper)
    await vm.showSemiStock(order)
    vm.openNewReturn(order)
    vm.newReturnForm = { pieces: '12', zoneId: 'zone', receiverId: 'receiver', date: '2026-09-27', remark: '' }
    const completed = { ...order, status: 'COMPLETED', returned_good_pieces: 12, remaining_return_pieces: 0 }
    api.goodReturn.mockResolvedValue(completed)
    api.externalOrder.mockResolvedValue(completed)
    api.stock.mockResolvedValue({ part_name: '前脚管', available_pieces: 12, zones: [] })
    await vm.submit()
    expect(api.goodReturn).toHaveBeenCalledWith('new-order', expect.objectContaining({ good_pieces: 12 }), '"new-order"')
    expect(api.externalOrder).toHaveBeenCalledTimes(2)
    expect(api.stock).toHaveBeenCalledTimes(2)
    expect(api.orders).not.toHaveBeenCalled()
    expect(vm.reworkDetail.returned_good_pieces).toBe(12)
    expect(vm.semiStock.available_pieces).toBe(12)
  })
})

describe('管材外发闭环写入边界', () => {
  it('金工全部完成且仍有可外发支数时允许登记原外发', async () => {
    const wrapper = await createView()
    const button = wrapper.findAll('button').find(item => item.text() === '登记原外发')!
    expect(button.attributes('disabled')).toBeUndefined()
  })

  it('只读用户可加载来源，不能看到写入按钮', async () => {
    auth.superuser = false
    auth.permissions.add('material_issues.view_metalprocessingsource')
    api.legacy.mockRejectedValue(new Error('无旧委外查看权限'))
    const wrapper = await createView()
    expect(wrapper.text()).toContain('前脚管')
    expect(wrapper.findAll('button').some(item => item.text() === '登记原外发')).toBe(false)
    expect(api.legacy).not.toHaveBeenCalled()
  })

  it('未喷塑退回带来源版本，网络失败原内容重试复用请求标识', async () => {
    const wrapper = await createView()
    const vm = state(wrapper)
    await vm.openReturn({ id: 'handoff-1', handoff_pieces: 12, returned_unsprayed_pieces: 0 })
    vm.returnForm = { pieces: '6', receiverId: 'receiver', storage: '金工架', date: '2026-09-23', remark: '' }
    api.returned.mockRejectedValueOnce(new Error('网络暂时中断')).mockResolvedValueOnce({ id: 'returned-1' })
    await vm.submit()
    await vm.submit()
    expect(api.returned).toHaveBeenCalledTimes(2)
    const first = api.returned.mock.calls[0]!
    const second = api.returned.mock.calls[1]!
    expect(first[2]).toBe('"source-1"')
    expect(second[1].request_id).toBe(first[1].request_id)
  })

  it('未喷塑退回使用后端扣除原单合格回货后的可退上限', async () => {
    api.handoffDetail.mockResolvedValueOnce({ ...handoffDetail, remaining_return_pieces: 2 })
    const wrapper = await createView()
    const vm = state(wrapper)
    await vm.openReturn({ id: 'handoff-1', handoff_pieces: 12, returned_unsprayed_pieces: 0, remaining_return_pieces: 2 })
    vm.returnForm = { pieces: '6', receiverId: 'receiver', storage: '金工架', date: '2026-09-23', remark: '' }
    await vm.submit()
    expect(api.returned).not.toHaveBeenCalled()
    expect(vm.dialogError).toContain('可退数量')
  })

  it('原单合格回货已经用完可退额时禁用登记退回', async () => {
    api.source.mockResolvedValueOnce({ ...completedSource, original_handoffs: [{
      id: 'handoff-1', handoff_pieces: 12, returned_unsprayed_pieces: 0, remaining_return_pieces: 0,
      unsprayed_returns: [],
    }] })
    const wrapper = await createView()
    const button = wrapper.findAll('button').find(item => item.text() === '登记退回')!
    expect(button.attributes('disabled')).toBeDefined()
  })

  it('原单身份变更后的退回阻断原因在弹窗明确显示', async () => {
    api.handoffDetail.mockResolvedValueOnce({ ...handoffDetail, remaining_return_pieces: 0, return_blockers: ['原外发单身份已变化'] })
    const wrapper = await createView()
    const vm = state(wrapper)
    await vm.openReturn({ id: 'handoff-1', handoff_pieces: 12, returned_unsprayed_pieces: 0,
      remaining_return_pieces: 0, return_blockers: { original_order_id: ['原外发单身份已变化'] },
    })
    expect(vm.dialogError).toContain('原外发单身份已变化')
    vm.returnForm = { pieces: '6', receiverId: 'receiver', storage: '金工架', date: '2026-09-23', remark: '' }
    await vm.submit()
    expect(api.returned).not.toHaveBeenCalled()
    expect(vm.dialogError).toContain('原外发单身份已变化')
  })

  it('写入成功后刷新失败，关闭弹窗并明确保存成功，避免再次发起写入', async () => {
    const wrapper = await createView()
    const vm = state(wrapper)
    await vm.openReturn({ id: 'handoff-1', handoff_pieces: 12, returned_unsprayed_pieces: 0 })
    vm.returnForm = { pieces: '6', receiverId: 'receiver', storage: '金工架', date: '2026-09-23', remark: '' }
    api.returned.mockResolvedValue({ id: 'returned-1' })
    api.sources.mockRejectedValueOnce(new Error('刷新连接中断'))
    await vm.submit()
    await flushPromises()
    expect(vm.dialog).toBeNull()
    expect(wrapper.text()).toContain('操作已保存，但刷新失败')
    await vm.submit()
    expect(api.returned).toHaveBeenCalledTimes(1)
  })

  it('保存尚未响应时关闭弹窗不会清除保存锁或重复请求', async () => {
    const wrapper = await createView()
    const vm = state(wrapper)
    vm.openRework({ id: 'return-1', returned_pieces: 12, remaining_rework_pieces: 12 })
    vm.reworkForm = { pieces: '6', date: '2026-09-23' }
    let finish!: (result: unknown) => void
    api.rework.mockReturnValue(new Promise(resolve => { finish = resolve }))
    const submit = vm.submit()
    vm.resetDialog()
    await vm.submit()
    expect(vm.dialog).toBe('rework')
    expect(vm.saving).toBe(true)
    expect(api.rework).toHaveBeenCalledTimes(1)
    finish({ id: 'rework-1' })
    await submit
  })

  it('创建新外发后进入该新单的统一详情，后续余额由重新读取来源取得', async () => {
    const wrapper = await createView()
    const vm = state(wrapper)
    vm.openOrder({ id: 'rework-1', completed_pieces: 12, remaining_allocatable_pieces: 12 })
    vm.orderForm.pieces = '6'
    api.order.mockResolvedValue({ id: 'order-1' })
    api.source.mockResolvedValueOnce({ ...completedSource, original_handoffs: [{
      id: 'handoff-1', handoff_pieces: 12, returned_unsprayed_pieces: 12,
      unsprayed_returns: [{ id: 'return-1', returned_pieces: 12, remaining_rework_pieces: 0, reworks: [
        { id: 'rework-1', completed_pieces: 12, remaining_allocatable_pieces: 6 },
      ] }],
    }] })
    await vm.submit()
    await flushPromises()
    expect(api.order).toHaveBeenCalledTimes(1)
    expect(router.push).toHaveBeenCalledWith('/workshop/outsourcing/rework/order-1')
    expect(wrapper.emitted('updated')).toHaveLength(1)
  })

  it('结清后追加回货备注留空时不调用写接口', async () => {
    const wrapper = await createView()
    const vm = state(wrapper)
    vm.openNewReturn({ id: 'order-1', status: 'CLOSED', remaining_return_pieces: 6, etag: '"order-1"' })
    vm.newReturnForm = { pieces: '6', zoneId: 'zone', receiverId: 'receiver', date: '2026-09-23', remark: '  ' }
    await vm.submit()
    expect(api.goodReturn).not.toHaveBeenCalled()
    expect(vm.dialogError).toContain('必须填写备注')
  })

  it('快速切换来源时较早返回的旧请求不能覆盖当前选择', async () => {
    const wrapper = await createView()
    const vm = state(wrapper)
    let finishFirst!: (result: unknown) => void
    api.source.mockReturnValueOnce(new Promise(resolve => { finishFirst = resolve }))
      .mockResolvedValueOnce({ ...completedSource, issue_line_id: 'line-3', part_name: '后脚管' })
    const first = vm.selectSource({ issue_line_id: 'line-2' })
    await vm.selectSource({ issue_line_id: 'line-3' })
    finishFirst({ ...completedSource, issue_line_id: 'line-2', part_name: '横管' })
    await first
    expect(vm.source.issue_line_id).toBe('line-3')
  })
})

describe('原外发单正常合格回货', () => {
  async function ready() {
    const wrapper = await createView()
    const vm = state(wrapper)
    // 单次交接仅有 6 支，弹窗必须采用同一分配累计 60 支的权威上下文。
    await vm.openOriginalGoodReturn({ id: 'handoff-1', handoff_pieces: 6, returned_unsprayed_pieces: 0 })
    vm.originalGoodForm = { pieces: '10', zoneId: 'zone', receiverId: 'receiver', date: '2026-09-23', remark: '' }
    await flushPromises()
    return { wrapper, vm }
  }

  it('按原单对应分配显示60/24/12/24，填10预览入10余14且不扣原料', async () => {
    const { wrapper, vm } = await ready()
    const summary = wrapper.get('[data-testid="original-good-return-summary"]').text()
    for (const text of ['实际交接60', '已合格回货24', '未喷塑退回12', '本次可回24']) expect(summary.replaceAll(' ', '')).toContain(text)
    const preview = wrapper.get('[data-testid="original-good-return-preview"]').text().replaceAll(' ', '')
    expect(preview).toContain('本次入半成品10支')
    expect(preview).toContain('回货后可继续回14支')
    expect(preview).toContain('原材料扣除0根/0.00米')
    expect(wrapper.get('.original-good-identity').text()).toContain('原单-001')
    expect(wrapper.get('.original-good-identity').findAll('input,select')).toHaveLength(0)
    expect(wrapper.get('[data-testid="original-good-return-history"]').text()).toContain('累计 24 支')
    expect(vm.originalGoodContext.handoff_pieces).toBe(60)
  })

  it('只提交合格半成品字段，备注可空，使用回货上下文版本并刷新', async () => {
    const { vm } = await ready()
    api.originalGoodReturn.mockResolvedValue({ ...goodContext, returned_good_pieces: 34, remaining_return_pieces: 14 })
    await vm.submit()
    expect(api.originalGoodReturn).toHaveBeenCalledWith('handoff-1', {
      request_id: expect.any(String), good_pieces: 10, zone_id: 'zone', received_by_employee_id: 'receiver',
      return_date: '2026-09-23', remark: '',
    }, '"allocation-return-1"')
    expect(api.sources).toHaveBeenCalledTimes(2)
    expect(vm.dialog).toBeNull()
    api.handoffDetail.mockResolvedValueOnce({ good_return_context: { ...goodContext, returned_good_pieces: 34, remaining_return_pieces: 14 } })
    await vm.openOriginalGoodReturn({ id: 'handoff-1' })
    expect(vm.originalGoodContext.returned_good_pieces).toBe(34)
  })

  it.each(['0', '-1', '1.5', '25'])('拒绝不合法或超上限支数 %s，预览不虚构库存变化', async pieces => {
    const { vm } = await ready()
    vm.originalGoodForm.pieces = pieces
    expect(vm.originalGoodPreview).toBeNull()
    await vm.submit()
    expect(api.originalGoodReturn).not.toHaveBeenCalled()
    expect(vm.dialogError).toMatch(/正整数|超过当前可回数量/)
  })

  it.each(['zoneId', 'receiverId', 'date'])('缺少 %s 时不提交', async field => {
    const { vm } = await ready()
    vm.originalGoodForm[field] = ''
    await vm.submit()
    expect(api.originalGoodReturn).not.toHaveBeenCalled()
  })

  it('使用原单回货权限，未授权不能看到按钮或绕过入口', async () => {
    auth.superuser = false
    api.source.mockResolvedValue({ ...completedSource, original_handoffs: [{ id: 'handoff-1', handoff_pieces: 6, returned_unsprayed_pieces: 0 }] })
    const wrapper = await createView()
    const vm = state(wrapper)
    expect(wrapper.find('[data-testid="original-good-return-button"]').exists()).toBe(false)
    await vm.openOriginalGoodReturn({ id: 'handoff-1' })
    expect(api.handoffDetail).not.toHaveBeenCalled()
    auth.permissions.add('outsourcing.confirm_return_outsourcingorder')
    await vm.openOriginalGoodReturn({ id: 'handoff-1' })
    expect(api.handoffDetail).toHaveBeenCalledWith('handoff-1')
    auth.permissions.clear()
    await vm.submit()
    expect(api.originalGoodReturn).not.toHaveBeenCalled()
    expect(vm.dialogError).toContain('没有执行此操作的权限')
  })

  it('混合来源等后台阻断在弹窗说明，禁用确认并阻止直接提交', async () => {
    api.handoffDetail.mockResolvedValueOnce({ good_return_context: { ...goodContext, can_return: false, blockers: ['同一部位存在混合发料来源，请核对'] } })
    const { wrapper, vm } = await ready()
    expect(wrapper.text()).toContain('混合发料来源')
    expect(wrapper.findAll('button').find(button => button.text() === '确认合格回货')!.attributes('disabled')).toBeDefined()
    await vm.submit()
    expect(api.originalGoodReturn).not.toHaveBeenCalled()
  })

  it('版本已变时保持弹窗提示刷新，不自动重试写入', async () => {
    const { vm } = await ready()
    api.originalGoodReturn.mockRejectedValue(new AxiosError('版本变化', undefined, undefined, undefined, { status: 412, data: { error: { message: '单据已变化' } } } as any))
    await vm.submit()
    expect(vm.dialogError).toContain('刷新最新数据')
    expect(vm.uncertainOutcome).toBe(false)
    expect(api.originalGoodReturn).toHaveBeenCalledTimes(1)
    vm.resetDialog()
    expect(vm.dialog).toBeNull()
  })

  it('网络结果不明时保留原内容和版本，以同一请求重试', async () => {
    const { vm } = await ready()
    api.originalGoodReturn.mockRejectedValueOnce(new Error('连接断开')).mockResolvedValueOnce(goodContext)
    await vm.submit()
    expect(vm.uncertainOutcome).toBe(true)
    vm.resetDialog()
    expect(vm.dialog).toBe('original-good-return')
    await vm.submit()
    expect(api.originalGoodReturn.mock.calls[1]).toEqual(api.originalGoodReturn.mock.calls[0])
  })

  it('关闭后旧上下文响应不能覆盖重新打开的另一条交接', async () => {
    const wrapper = await createView()
    const vm = state(wrapper)
    let finish!: (value: unknown) => void
    api.handoffDetail.mockReturnValueOnce(new Promise(resolve => { finish = resolve }))
    const opening = vm.openOriginalGoodReturn({ id: 'old-handoff' })
    await vm.submit()
    expect(api.originalGoodReturn).not.toHaveBeenCalled()
    vm.resetDialog()
    api.handoffDetail.mockResolvedValueOnce({ good_return_context: { ...goodContext, original_order_id: 'new-original' } })
    await vm.openOriginalGoodReturn({ id: 'new-handoff' })
    finish({ good_return_context: goodContext })
    await opening
    expect(vm.originalGoodContext.original_order_id).toBe('new-original')
  })
})

describe('新外发交接前调整分配', () => {
  const order = {
    id: 'new-order', source_id: 'source-1', rework_id: 'rework-1', order_number: '新单-002',
    factory_name: '宏达喷塑厂', craft_name: '黑色喷塑', allocated_pieces: 8, handoff_pieces: 0,
    status: 'PENDING_HANDOFF', etag: '"order-8"', allocation_history: [],
    allocation_context: { rework_completed_pieces: 24, other_allocated_pieces: 12,
      max_allocatable_pieces: 12, remaining_allocatable_pieces: 4, can_adjust: true, blockers: [],
      part_name: '前脚管', issue_number: '领料-1' },
  }
  async function ready() {
    api.externalOrder.mockResolvedValue(structuredClone(order))
    const wrapper = await createView()
    const vm = state(wrapper)
    await vm.openAllocation(order)
    await flushPromises()
    return { wrapper, vm }
  }

  it('本单可调上限为12而不是空余4，8改10预览总22余2，身份只读', async () => {
    const { wrapper, vm } = await ready()
    vm.allocationForm.pieces = '10'
    await flushPromises()
    expect(vm.allocationPreview).toEqual({ total: 22, remaining: 2 })
    expect(wrapper.get('[data-testid="allocation-summary"]').text().replaceAll(' ', '')).toContain('本单可调上限12支')
    expect(wrapper.get('[data-testid="allocation-preview"]').text()).toContain('22 支')
    expect(wrapper.get('.allocation-dialog .original-good-identity').findAll('input,select')).toHaveLength(0)
    api.adjustAllocation.mockResolvedValue({ ...order, allocated_pieces: 10 })
    await vm.submit()
    expect(api.adjustAllocation).toHaveBeenCalledWith('new-order', { request_id: expect.any(String), allocated_pieces: 10 }, '"order-8"')
    expect(vm.dialog).toBeNull()
    expect(api.orders).toHaveBeenCalledTimes(2)
  })

  it.each(['0', '-1', '1.5', '13'])('非法调整支数%s不发请求，输入保留', async pieces => {
    const { vm } = await ready()
    vm.allocationForm.pieces = pieces
    await vm.submit()
    expect(api.adjustAllocation).not.toHaveBeenCalled()
    expect(vm.allocationForm.pieces).toBe(pieces)
    expect(vm.allocationPreview).toBeNull()
  })

  it('实际已交接时锁定入口并且直接调用提交也不会写入', async () => {
    api.orders.mockResolvedValue({ data: [{ ...order, handoff_pieces: 8 }], meta: {} })
    const { wrapper, vm } = await ready()
    expect(wrapper.get('[data-testid="allocation-button"]').attributes('disabled')).toBeDefined()
    vm.selectedOrder.handoff_pieces = 8
    vm.allocationForm.pieces = '10'
    await vm.submit()
    expect(api.adjustAllocation).not.toHaveBeenCalled()
    expect(vm.dialogError).toContain('已交接')
  })

  it('独立change权限控制，读取新上下文失败不允许保存', async () => {
    auth.superuser = false
    const wrapper = await createView()
    const vm = state(wrapper)
    await vm.openAllocation(order)
    expect(api.externalOrder).not.toHaveBeenCalled()
    auth.permissions.add('material_issues.change_metalprocessingexternalorder')
    api.externalOrder.mockRejectedValue(new Error('分配详情暂不可用'))
    await vm.openAllocation(order)
    await vm.submit()
    expect(api.adjustAllocation).not.toHaveBeenCalled()
    expect(vm.selectedOrder).toBeNull()
  })

  it('412保留原输入待核对，网络未知原请求重试，不借用新版本', async () => {
    const { vm } = await ready()
    vm.allocationForm.pieces = '10'
    api.adjustAllocation.mockRejectedValueOnce(new AxiosError('过期', undefined, undefined, undefined, { status: 412, data: {} } as any))
    await vm.submit()
    expect(vm.allocationForm.pieces).toBe('10')
    expect(vm.dialogError).toContain('刷新最新数据')
    expect(vm.uncertainOutcome).toBe(false)
    api.adjustAllocation.mockRejectedValueOnce(new Error('网络中断')).mockResolvedValueOnce(order)
    await vm.submit()
    vm.resetDialog()
    expect(vm.dialog).toBe('allocation')
    await vm.submit()
    expect(api.adjustAllocation.mock.calls[2]).toEqual(api.adjustAllocation.mock.calls[1])
  })

  it('取消不写入，再打开显示后台修改记录和最新上限', async () => {
    const { wrapper, vm } = await ready()
    vm.allocationForm.pieces = '10'
    vm.resetDialog()
    expect(api.adjustAllocation).not.toHaveBeenCalled()
    api.externalOrder.mockResolvedValueOnce({ ...order, allocated_pieces: 10, allocation_history: [{
      id: 'history-1', before_pieces: 8, after_pieces: 10, actor_name: '张计划员', created_at: '2026-09-23T08:00:00+08:00',
    }] })
    await vm.openAllocation(order)
    await flushPromises()
    expect(vm.allocationForm.pieces).toBe('10')
    expect(wrapper.get('[data-testid="allocation-dialog-history"]').text()).toContain('张计划员')
  })
})

describe('原始金工登记与来源结清', () => {
  const original = { ...completedSource, issued_pieces: 12, completed_pieces: 0, remaining_completion_pieces: 12,
    available_pieces: 0, unfinished_pieces: 12, unallocated_pieces: 0, source_id: null, can_register: true,
    etag: '"source-empty"', completions: [], closure: null }
  async function ready(mode = 'source-completion', overrides = {}) {
    const context = { ...original, ...overrides }
    api.source.mockResolvedValue(context)
    api.sourceClosePreview.mockResolvedValue(context)
    const wrapper = await createView()
    const vm = state(wrapper)
    await vm.openSourceOperation(mode)
    await flushPromises()
    return { wrapper, vm }
  }

  it('无源记录但已出库可首次登记，提交10支沿用读取版本且不提交库存字段', async () => {
    const { wrapper, vm } = await ready()
    expect(wrapper.get('[data-testid="source-completion-summary"]').text()).toContain('12 支')
    vm.sourceCompletionForm = { pieces: '10', date: '2026-09-23' }
    api.sourceCompletion.mockResolvedValue({ ...original, completed_pieces: 10, source_id: 'source-1' })
    await vm.submit()
    expect(api.sourceCompletion).toHaveBeenCalledWith('line-1', { request_id: expect.any(String), good_pieces: 10, completion_date: '2026-09-23' }, '"source-empty"')
    expect(vm.dialog).toBeNull()
  })

  it.each(['0', '-1', '1.5', '13'])('来源登记拒绝%s，保持填写内容', async pieces => {
    const { vm } = await ready()
    vm.sourceCompletionForm = { pieces, date: '2026-09-23' }
    await vm.submit()
    expect(api.sourceCompletion).not.toHaveBeenCalled()
    expect(vm.sourceCompletionForm.pieces).toBe(pieces)
  })

  it('来源结清只提交非空备注，展示未完成2和完成未交10，不混用新单结清接口', async () => {
    const { wrapper, vm } = await ready('source-close', { completed_pieces: 10, unfinished_pieces: 2, unallocated_pieces: 10, available_pieces: 10 })
    const difference = wrapper.get('[data-testid="source-close-difference"]').text()
    expect(difference).toContain('2 支')
    expect(difference).toContain('10 支')
    vm.sourceCloseForm.remark = '   '
    await vm.submit()
    expect(api.sourceClose).not.toHaveBeenCalled()
    vm.sourceCloseForm.remark = ' 本来源到此结束 '
    api.sourceClose.mockResolvedValue({ ...original, status: 'CLOSED' })
    await vm.submit()
    expect(api.sourceClose).toHaveBeenCalledWith('line-1', { request_id: expect.any(String), remark: '本来源到此结束' }, '"source-empty"')
    expect(api.close).not.toHaveBeenCalled()
  })

  it('待外发占用阻止来源结清，保留真实占用提示', async () => {
    const { wrapper, vm } = await ready('source-close', { reserved_pieces: 2, can_close: false, blockers: ['存在待外发占用，请先交接或取消分配。'] })
    expect(wrapper.get('[data-testid="source-close-button"]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('[data-testid="p4-dialog-submit"]').attributes('disabled')).toBeDefined()
    vm.sourceCloseForm.remark = '结束'
    await vm.submit()
    expect(api.sourceClose).not.toHaveBeenCalled()
    expect(vm.dialogError).toContain('待外发占用')
  })

  it('已结清停用登记与结清，显示操作人时间及原差额，原交接记录保留', async () => {
    const { wrapper, vm } = await ready('source-completion', { status: 'CLOSED', can_register: false, can_close: false,
      closure: { remark: '本来源到此结束', quantities: { unfinished_pieces: 2, unallocated_pieces: 10 }, actor_name: '李主管', created_at: '2026-09-23T08:00:00+08:00' },
      completions: [{ id: 'completion-1', good_pieces: 10, completion_date: '2026-09-23', actor_name: '张金工', created_at: '2026-09-23T07:00:00+08:00' }],
    })
    expect(wrapper.get('[data-testid="source-completion-button"]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('[data-testid="source-close-button"]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('[data-testid="source-processing-history"]').text()).toContain('张金工')
    expect(wrapper.get('[data-testid="source-closure-history"]').text()).toContain('李主管')
    vm.sourceCompletionForm = { pieces: '1', date: '2026-09-23' }
    await vm.submit()
    expect(api.sourceCompletion).not.toHaveBeenCalled()
  })

  it('独立权限检查、冻结异常无版本、加载失败均不能产生写入', async () => {
    auth.superuser = false
    const { wrapper, vm } = await ready()
    expect(wrapper.find('[data-testid="source-completion-button"]').exists()).toBe(false)
    expect(vm.dialog).toBeNull()
    auth.permissions.add('material_issues.register_metalprocessingcompletion')
    api.source.mockResolvedValueOnce({ ...original, etag: null, can_register: false, can_close: false, blockers: ['领料冻结资料缺失'] })
    await vm.openSourceOperation('source-completion')
    expect(vm.dialogError).toContain('冻结资料缺失')
    await vm.submit()
    expect(api.sourceCompletion).not.toHaveBeenCalled()
    vm.resetDialog()
    api.source.mockRejectedValueOnce(new Error('详情加载失败'))
    await vm.openSourceOperation('source-completion')
    expect(vm.sourceContext).toBeNull()
    await vm.submit()
    expect(api.sourceCompletion).not.toHaveBeenCalled()
  })

  it('来源网络结果未知重试复用请求；旧上下文返回不能覆盖已关弹窗', async () => {
    const { vm } = await ready('source-close')
    vm.sourceCloseForm.remark = '本来源到此结束'
    api.sourceClose.mockRejectedValueOnce(new Error('网络中断')).mockResolvedValueOnce(original)
    await vm.submit()
    expect(vm.uncertainOutcome).toBe(true)
    await vm.submit()
    expect(api.sourceClose.mock.calls[1]).toEqual(api.sourceClose.mock.calls[0])
    let finish!: (value: unknown) => void
    api.sourceClosePreview.mockReturnValueOnce(new Promise(resolve => { finish = resolve }))
    const opening = vm.openSourceOperation('source-close')
    vm.resetDialog()
    finish(original)
    await opening
    expect(vm.dialog).toBeNull()
    expect(vm.sourceContext).toBeNull()
  })

  it('领料详情直达时按领料ID过滤来源及新外发单，分页保持过滤条件', async () => {
    route.query = { issue_id: 'issue-1' }
    api.sources.mockResolvedValueOnce({ data: [completedSource], meta: { total_pages: 2 } })
      .mockResolvedValueOnce({ data: [], meta: { total_pages: 2 } })
    api.orders.mockResolvedValue({ data: [{ id: 'allowed-order', source_id: 'source-1' }, { id: 'other-order', source_id: 'source-2' }] })
    const vm = state(await createView())
    expect(api.sources).toHaveBeenNthCalledWith(1, { issue_id: 'issue-1', page: 1, page_size: 100 })
    expect(api.sources).toHaveBeenNthCalledWith(2, { issue_id: 'issue-1', page: 2, page_size: 100 })
    expect(vm.visibleOrders.map((row: any) => row.id)).toEqual(['allowed-order'])
  })
})

describe('原单备注结清与后续补登记', () => {
  const quantities = { planned_pieces: 60, cancelled_pending_pieces: 0, effective_planned_pieces: 60,
    pending_handoff_pieces: 0, handoff_pieces: 60, returned_good_pieces: 24, returned_unsprayed_pieces: 24, remaining_return_pieces: 12 }
  const part = { allocation_id: 'allocation-1', product_line_id: 'product-1', part_name: '前脚管',
    factory_name: '宏达喷塑厂', factory_id: 'factory', product_name: '折叠椅', product_number: 'XY-1',
    specification: '圆管 500 mm', can_cancel_pending: false, ...quantities }
  const context = { original_order_id: 'original-order', original_order_number: '原单-001',
    original_order_status: 'PARTIAL_RETURN', etag: '"original-order-3"', parts: [part], totals: quantities,
    can_close: true, blockers: [], closure: null, post_closure_returns: [], pending_cancellations: [] }
  const closure = { id: 'closure-1', remark: '保留12支差额结清', actor_name: '陈主管', actor_employee_id: 'actor-1',
    created_at: '2026-09-23T10:00:00+08:00', quantity_snapshot: { parts: [part], totals: quantities } }
  async function ready(overrides = {}) {
    api.originalOrder.mockResolvedValue({ ...structuredClone(context), ...overrides })
    const wrapper = await createView()
    const vm = state(wrapper)
    await vm.openOriginalOrder(handoffDetail)
    await flushPromises()
    return { wrapper, vm }
  }

  it('整单逐部位显示实交/两类回货/余量，空白原因不结清，合法只提交原因及整单版本', async () => {
    const { wrapper, vm } = await ready()
    expect(wrapper.get('[data-testid="original-order-summary"]').text()).toContain('12 支')
    expect(wrapper.get('[data-testid="original-order-parts"]').text()).toContain('圆管 500 mm')
    vm.originalCloseForm.remark = '  '
    await vm.submit()
    expect(api.originalClose).not.toHaveBeenCalled()
    vm.originalCloseForm.remark = ' 保留实际差额结清 '
    api.originalClose.mockResolvedValue({ ...context, original_order_status: 'CLOSED', can_close: false, closure })
    await vm.submit()
    expect(api.originalClose).toHaveBeenCalledWith('original-order', { request_id: expect.any(String), remark: '保留实际差额结清' }, '"original-order-3"')
    expect(api.sourceClose).not.toHaveBeenCalled()
    expect(api.close).not.toHaveBeenCalled()
  })

  it('只读用户能看整单历史，不能结清，服务权限不借用来源权限', async () => {
    auth.superuser = false
    auth.permissions.add('material_issues.close_metalprocessingsource')
    const { wrapper, vm } = await ready()
    expect(wrapper.find('[data-testid="original-order-dialog"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="p4-dialog-submit"]').exists()).toBe(false)
    vm.originalCloseForm.remark = '结束'
    await vm.submit()
    expect(api.originalClose).not.toHaveBeenCalled()
    expect(vm.dialogError).toContain('没有执行此操作的权限')
  })

  it('有待交接或零实交时阻断结清，不能用备注绕过', async () => {
    const { wrapper, vm } = await ready({ can_close: false, blockers: ['还有6支待交接，请先处理'], totals: { ...quantities, pending_handoff_pieces: 6 } })
    expect(wrapper.get('[data-testid="p4-dialog-submit"]').attributes('disabled')).toBeDefined()
    vm.originalCloseForm.remark = '备注'
    await vm.submit()
    expect(api.originalClose).not.toHaveBeenCalled()
    expect(vm.dialogError).toContain('待交接')
    vm.originalOrderContext = { ...context, can_close: false, blockers: ['尚无实际交接'] }
    await vm.submit()
    expect(api.originalClose).not.toHaveBeenCalled()
  })

  it('已结清当前余量2与结清时差额12分别展示，补登记原因和操作者保留', async () => {
    const { wrapper } = await ready({ original_order_status: 'CLOSED', can_close: false, closure,
      parts: [{ ...part, returned_good_pieces: 34, remaining_return_pieces: 2 }], totals: { ...quantities, returned_good_pieces: 34, remaining_return_pieces: 2 },
      post_closure_returns: [{ id: 'late-1', kind: 'GOOD', part_name: '前脚管', pieces: 10, remark: '加工厂补送', actor_name: '张仓管', created_at: '2026-09-23T11:00:00+08:00' }],
    })
    expect(wrapper.get('[data-testid="original-order-summary"]').text()).toContain('2 支')
    expect(wrapper.get('[data-testid="original-closure-snapshot"]').text()).toContain('结清差额合计 12 支')
    expect(wrapper.get('[data-testid="original-post-closure-history"]').text()).toContain('加工厂补送')
    expect(wrapper.get('[data-testid="original-post-closure-history"]').text()).toContain('张仓管')
    expect(wrapper.find('[data-testid="p4-dialog-submit"]').exists()).toBe(false)
  })

  it('结清后合格补回原因必填，保留原结清快照且不增加回货上限', async () => {
    const wrapper = await createView(); const vm = state(wrapper)
    api.handoffDetail.mockResolvedValueOnce({ ...handoffDetail, good_return_context: {
      ...goodContext, original_order_status: 'CLOSED', post_closure: true, closure, remaining_return_pieces: 12,
    } })
    await vm.openOriginalGoodReturn(handoffDetail)
    vm.originalGoodForm = { pieces: '10', zoneId: 'zone', receiverId: 'receiver', date: '2026-09-23', remark: ' ' }
    await vm.submit()
    expect(api.originalGoodReturn).not.toHaveBeenCalled()
    expect(vm.dialogError).toContain('必须填写原因')
    await flushPromises()
    expect(wrapper.get('[data-testid="good-closure-snapshot"]').text()).toContain('12 支')
    vm.originalGoodForm.remark = '后续补送合格件'
    api.originalGoodReturn.mockResolvedValue(goodContext)
    await vm.submit()
    expect(api.originalGoodReturn.mock.calls[0]![1].remark).toBe('后续补送合格件')
  })

  it('结清后未喷塑补退使用最新handoff上下文及其来源版本，原因必填、仅登记暂存', async () => {
    const wrapper = await createView(); const vm = state(wrapper)
    api.handoffDetail.mockResolvedValueOnce({ ...handoffDetail, source_etag: '"fresh-source"', original_order_status: 'CLOSED', original_order_closure: closure, remaining_return_pieces: 2 })
    await vm.openReturn({ ...handoffDetail, remaining_return_pieces: 999 })
    vm.returnForm = { pieces: '2', receiverId: 'receiver', storage: '金工架', date: '2026-09-23', remark: '' }
    expect(vm.returnPreview).toEqual({ pieces: 2, remaining: 0 })
    await vm.submit()
    expect(api.returned).not.toHaveBeenCalled()
    expect(vm.dialogError).toContain('必须填写原因')
    vm.returnForm.remark = '现场清点补退'
    api.returned.mockResolvedValue({})
    await vm.submit()
    expect(api.returned).toHaveBeenCalledWith('handoff-1', {
      request_id: expect.any(String), returned_pieces: 2, received_by_employee_id: 'receiver', storage_location: '金工架', return_date: '2026-09-23', remark: '现场清点补退',
    }, '"fresh-source"')
  })

  it('回齐后两类追加按钮锁定，打开陈旧行也以最新已完成状态拒绝退回', async () => {
    api.source.mockResolvedValue({ ...completedSource, original_handoffs: [{ ...handoffDetail, original_order_status: 'COMPLETED' }] })
    const wrapper = await createView(); const vm = state(wrapper)
    expect(wrapper.get('[data-testid="original-good-return-button"]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('[data-testid="original-unsprayed-return-button"]').attributes('disabled')).toBeDefined()
    api.handoffDetail.mockResolvedValueOnce({ ...handoffDetail, original_order_status: 'COMPLETED', remaining_return_pieces: 0 })
    await vm.openReturn(handoffDetail)
    vm.returnForm = { pieces: '1', receiverId: 'receiver', storage: '金工架', date: '2026-09-23', remark: '补退' }
    await vm.submit()
    expect(api.returned).not.toHaveBeenCalled()
    expect(vm.dialogError).toContain('可退数量')
  })

  it('取消待交余量必须显式选分配并填原因，原计划18实交12待交6，取消后有效12', async () => {
    const pending = { ...part, planned_pieces: 18, effective_planned_pieces: 18, handoff_pieces: 12, pending_handoff_pieces: 6, can_cancel_pending: true }
    const { wrapper, vm } = await ready({ parts: [pending], can_close: false })
    await vm.openOriginalCancel(pending)
    await flushPromises()
    const summary = wrapper.get('[data-testid="original-cancel-pending-summary"]').text()
    expect(summary).toContain('本次取消待交6 支')
    expect(summary).toContain('取消后有效计划12 支')
    vm.originalCancelForm.remark = '  '
    await vm.submit()
    expect(api.originalCancelPending).not.toHaveBeenCalled()
    vm.originalCancelForm.remark = '剩余无需加工'
    api.originalCancelPending.mockResolvedValue({ ...context, original_order_status: 'COMPLETED' })
    await vm.submit()
    expect(api.originalCancelPending).toHaveBeenCalledWith('original-order', { request_id: expect.any(String), allocation_id: 'allocation-1', remark: '剩余无需加工' }, '"original-order-3"')
  })

  it('取消需独立修改权限；后台待交变为0后不可通过陈旧按钮提交', async () => {
    const pending = { ...part, pending_handoff_pieces: 6, can_cancel_pending: true }
    auth.superuser = false; auth.permissions.add('outsourcing.complete_outsourcingorder')
    const { vm } = await ready({ parts: [pending] })
    await vm.openOriginalCancel(pending)
    expect(vm.dialog).toBe('original-close')
    auth.permissions.add('outsourcing.change_outsourcingorder')
    api.originalOrder.mockResolvedValueOnce({ ...context, parts: [{ ...part, pending_handoff_pieces: 0 }] })
    await vm.openOriginalCancel(pending)
    vm.originalCancelForm.remark = '取消'
    await vm.submit()
    expect(api.originalCancelPending).not.toHaveBeenCalled()
    expect(vm.dialogError).toContain('没有可取消')
  })

  it('原单结清412保留原因与弹窗，未知结果重试复用标识', async () => {
    const { vm } = await ready()
    vm.originalCloseForm.remark = '保留差额'
    api.originalClose.mockRejectedValueOnce(new AxiosError('过期', undefined, undefined, undefined, { status: 412, data: {} } as any))
    await vm.submit()
    expect(vm.originalCloseForm.remark).toBe('保留差额')
    expect(vm.dialogError).toContain('刷新最新数据')
    api.originalClose.mockRejectedValueOnce(new Error('网络断开')).mockResolvedValueOnce(context)
    await vm.submit(); vm.resetDialog()
    expect(vm.dialog).toBe('original-close')
    await vm.submit()
    expect(api.originalClose.mock.calls[2]).toEqual(api.originalClose.mock.calls[1])
  })

  it('加载失败没有上下文不得写入，关闭弹窗后旧退回请求不能覆盖新弹窗', async () => {
    const wrapper = await createView(); const vm = state(wrapper)
    api.originalOrder.mockRejectedValueOnce(new Error('原单详情失败'))
    await vm.openOriginalOrder(handoffDetail)
    await vm.submit()
    expect(api.originalClose).not.toHaveBeenCalled()
    vm.resetDialog()
    let finish!: (value: unknown) => void
    api.handoffDetail.mockReturnValueOnce(new Promise(resolve => { finish = resolve }))
    const opening = vm.openReturn(handoffDetail)
    vm.resetDialog()
    await vm.openSourceOperation('source-completion')
    finish({ ...handoffDetail, source_etag: '"old-late"' })
    await opening
    expect(vm.returnContext).toBeNull()
    expect(vm.dialog).toBe('source-completion')
  })
})

it('分配调整支持后端正整数上限范围，不截断为32位整数', async () => {
  const amount = 2147483648
  api.externalOrder.mockResolvedValue({ id: 'large-order', status: 'PENDING_HANDOFF', handoff_pieces: 0, allocated_pieces: 1, etag: '"large"',
    allocation_context: { rework_completed_pieces: amount, other_allocated_pieces: 0, max_allocatable_pieces: amount, can_adjust: true, blockers: [] } })
  const wrapper = await createView(); const vm = state(wrapper)
  await vm.openAllocation({ id: 'large-order' })
  vm.allocationForm.pieces = String(amount)
  expect(vm.allocationPreview).toEqual({ total: amount, remaining: 0 })
  api.adjustAllocation.mockResolvedValue({})
  await vm.submit()
  expect(api.adjustAllocation.mock.calls[0]![1].allocated_pieces).toBe(amount)
})
