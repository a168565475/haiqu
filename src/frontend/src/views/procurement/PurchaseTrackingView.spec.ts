import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'
import ElementPlus, { ElSelect, ElTooltip } from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '@/api/purchaseTracking'
import type { PurchaseTrackingArrival, PurchaseTrackingCoverage, PurchaseTrackingRow } from '@/types/purchaseTracking'
import PurchaseTrackingView from './PurchaseTrackingView.vue'
import PurchaseTrackingPolicyDialog from './PurchaseTrackingPolicyDialog.vue'

const auth = vi.hoisted(() => ({ permissions: ['procurement.view_purchaseorder'] }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ user: { is_superuser: false }, hasPermission: (permission: string) => auth.permissions.includes(permission), managementCan: (permission: string) => auth.permissions.includes(permission) }) }))
vi.mock('@/api/purchaseTracking', () => ({ fetchPurchaseTrackingArrivals: vi.fn(), fetchPurchaseTrackingCoverage: vi.fn(), fetchPurchaseTrackingFilterOptions: vi.fn(), fetchPurchaseTrackingPolicy: vi.fn(), updatePurchaseTrackingPolicy: vi.fn() }))

const common = (): PurchaseTrackingRow => ({ row_key: 'arrival:line-1', production_task_id: 'task-1', task_number: 'SC-1', product_line_id: 'product-1', product_name: '测试产品', material_name: '管材', specification: '20×20', unit: '米', purchase_group_id: 'group-1', source_bom_line_id: 'bom-line-1', source_reliable: true, verification_notes: [], is_history: false, risks: [{ code: 'OVERDUE', label: '逾期2天', level: 'danger', rank: 30 }], actions: [{ kind: 'view_order', label: '查看批次', path: '/purchase-orders/order-1/details' }], action_blocked_reason: '', evaluated_at: '2026-11-05T01:00:00Z' })
const arrival = (overrides: Partial<PurchaseTrackingArrival> = {}): PurchaseTrackingArrival => ({ ...common(), material_selection_snapshot: {}, material_attributes_snapshot: {}, part_name: '', material: '', raw_material: '', purchase_order_id: 'order-1', purchase_order_line_id: 'line-1', purchase_order_no: 'CG-1', batch_number: 1, publication_status: '已确认 · 未发布', supplier_name: '测试供应商', ordered_quantity: '600.0000', received_quantity: '360.0000', accepted_quantity: '280.0000', pending_quality_quantity: '80.0000', unreceived_quantity: '240.0000', return_quantity: '0.0000', return_pending: false, delivery_date: '2026-11-03', days_remaining: -2, ordered_root_count: null, received_root_count: null, unreceived_root_count: null, root_count_note: '', ...overrides })
const coverage = (overrides: Partial<PurchaseTrackingCoverage> = {}): PurchaseTrackingCoverage => ({ ...common(), bom_created_at: null, bom_confirmed_at: null, bom_purchase_due_at: null, latest_purchase_date: null, purchase_days_remaining: null, material_category_key: null, order_delivery_date: null, material_attributes_snapshot: {}, material_selection_snapshot: {}, part_name: '', material: '', raw_material: '', row_key: 'coverage:product-1:bom-line-1', required_quantity: '2000.0000', purchased_quantity: '0.0000', remaining_quantity: '2000.0000', scheduled: true, material_inbound_date: '2026-11-06', group_status: '总单未建', purchase_group_id: null, required_root_count: null, purchased_root_count: null, remaining_root_count: null, root_count_note: '', risks: [{ code: 'SCHEDULED_UNPURCHASED', label: '已排产未采购', level: 'danger', rank: 30 }], actions: [], action_blocked_reason: '当前账号仅有查看权限。', ...overrides })
const page = <T,>(rows: T[], total = rows.length, current = 1) => ({ data: rows, meta: { page: current, page_size: 20, total, total_pages: Math.ceil(total / 20) } })
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(done => { resolve = done }); return { promise, resolve } }
let wrapper: VueWrapper | undefined
let router: Router
async function open(path = '/purchase-tracking') {
  router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/purchase-tracking', name: 'purchase-tracking', component: PurchaseTrackingView },
    { path: '/purchase-alerts', name: 'purchase-alerts', component: PurchaseTrackingView },
    { path: '/purchase-orders/:id/details', name: 'purchase-order-detail', component: { template: '<div />' } },
    { path: '/purchase-groups/:id', name: 'purchase-group-detail', component: { template: '<div />' } },
    { path: '/:pathMatch(.*)*', name: 'not-found', component: { template: '<div />' } },
  ] })
  await router.push(path)
  wrapper = mount(PurchaseTrackingView, { global: { plugins: [router, ElementPlus] } })
  await flushPromises()
}

beforeEach(() => {
  vi.clearAllMocks()
  auth.permissions = ['procurement.view_purchaseorder']
  vi.mocked(api.fetchPurchaseTrackingArrivals).mockResolvedValue(page([arrival()]))
  vi.mocked(api.fetchPurchaseTrackingCoverage).mockResolvedValue(page([coverage()]))
  vi.mocked(api.fetchPurchaseTrackingFilterOptions).mockResolvedValue({ production_tasks: [{ id: 'task-1', task_number: 'SC-1', order_number: 'XS-1' }] })
})
afterEach(() => { wrapper?.unmount(); wrapper = undefined })

describe('采购跟踪与采购提醒独立列表', () => {
  it('到货跟踪按采购页面骨架渲染，所有信息单列且不展开', async () => {
    await open()
    expect(wrapper!.get('h1').text()).toBe('采购跟踪')
    expect(wrapper!.find('[data-tab]').exists()).toBe(false)
    const headers = wrapper!.get('thead').text()
    for (const label of ['生产订单号', '产品', '订单号', '供应商', '材料', '规格', '采购数量', '实际收货', '合格数量', '待检数量', '未到数量', '采购交期', '交期状态']) expect(headers).toContain(label)
    expect(wrapper!.get('tbody').text()).toContain('360 米')
    expect(wrapper!.get('tbody').text()).toContain('280 米')
    expect(wrapper!.get('tbody').text()).toContain('80 米')
    expect(wrapper!.get('tbody').text()).toContain('240 米')
    expect(wrapper!.find('small').exists()).toBe(false)
    expect(wrapper!.find('details, tbody [aria-expanded], .el-drawer').exists()).toBe(false)
  })

  it('跟踪生产订单号加粗并跨采购单连续合并，保留订单和供应商合并', async () => {
    vi.mocked(api.fetchPurchaseTrackingArrivals).mockResolvedValue(page([
      arrival(),
      arrival({ row_key: 'arrival:line-2', purchase_order_line_id: 'line-2' }),
      arrival({ row_key: 'arrival:line-3', purchase_order_id: 'order-2', purchase_order_no: 'CG-2', supplier_name: '供应商二' }),
      arrival({ row_key: 'arrival:line-4', production_task_id: 'task-2', task_number: 'SC-2', purchase_order_no: 'CG-3' }),
      arrival({ row_key: 'arrival:line-5', production_task_id: 'task-3', task_number: 'SC-1', purchase_order_no: 'CG-4' }),
    ], 25, 2))
    await open('/purchase-tracking?page=2')
    const rows = wrapper!.findAll('.el-table__body tbody tr')
    const firstCells = rows[0]!.findAll('td')
    expect(firstCells[0]!.get('.tracking-strong').text()).toBe('SC-1')
    expect(firstCells[0]!.attributes('rowspan')).toBe('3')
    expect(firstCells[2]!.attributes('rowspan')).toBe('2')
    expect(firstCells[3]!.attributes('rowspan')).toBe('2')
    expect(rows[1]!.text()).not.toContain('SC-1')
    expect(rows[2]!.text()).not.toContain('SC-1')
    expect(rows[2]!.text()).toContain('CG-2')
    expect(rows[3]!.findAll('td')[0]!.attributes('rowspan')).toBe('1')
    expect(rows[4]!.findAll('td')[0]!.attributes('rowspan')).toBe('1')
    expect(rows[4]!.findAll('td')[0]!.text()).toBe('SC-1')
  })

  it('规格悬停展示采购冻结属性，正文保持单行规格', async () => {
    vi.mocked(api.fetchPurchaseTrackingArrivals).mockResolvedValue(page([arrival({
      material_selection_snapshot: { schema_version: 1, catalog_id: 'catalog-1', catalog_version: 'v1', category_key: 'TUBE', template_key: 'TUBE', name: '方管', scope: 'BASE', processing_state: 'RAW', processing_stage: '原材料', display_name: '方管', unit_id: 'unit-1', unit_name: '米', attributes: { thickness: '1.5 mm', material: '冻结Q235' } },
      material_attributes_snapshot: { fields: [{ key: 'material', label: '材质', value: '旧快照材质' }] },
      material: '不应覆盖冻结属性',
    })]))
    await open()
    const trigger = wrapper!.get('[data-testid="arrival-specification"]')
    expect(trigger.text()).toBe('20×20')
    expect(trigger.attributes('tabindex')).toBe('0')
    await wrapper!.findAll('tbody td').find(cell => cell.find('[data-testid="arrival-specification"]').exists())!.trigger('mouseenter')
    await vi.waitFor(() => expect(document.body.textContent).toContain('冻结Q235'))
    expect(document.body.textContent).toContain('1.5 mm')
    expect(document.body.textContent).not.toContain('不应覆盖冻结属性')
    expect(document.body.textContent).not.toContain('旧快照材质')
    expect(wrapper!.get('tbody').text()).not.toContain('1.5 mm')
  })

  it('交期和交期状态与操作连续固定右侧，材料列自适应剩余宽度', async () => {
    await open()
    const columns = wrapper!.findAllComponents({ name: 'ElTableColumn' })
    expect(columns.slice(-3).map(column => [column.props('label'), column.props('fixed'), String(column.props('width'))])).toEqual([
      ['采购交期', 'right', '112'], ['交期状态', 'right', '150'], ['操作', 'right', '144'],
    ])
    expect(columns.find(column => column.props('label') === '材料')!.props('minWidth')).toBe('150')
  })

  it.each([
    { code: 'NEAR_DUE', label: '5天后到期', level: 'warning', days: 5, type: 'warning', effect: 'light' },
    { code: 'NEAR_DUE', label: '3天后到期', level: 'warning', days: 3, type: 'warning', effect: 'light' },
    { code: 'NEAR_DUE', label: '2天后到期', level: 'warning', days: 2, type: 'warning', effect: 'light' },
    { code: 'NEAR_DUE', label: '1天后到期', level: 'warning', days: 1, type: 'warning', effect: 'dark' },
    { code: 'DUE_TODAY', label: '今天到期', level: 'warning', days: 0, type: 'danger', effect: 'dark' },
    { code: 'OVERDUE', label: '逾期2天', level: 'danger', days: -2, type: 'danger', effect: 'dark' },
    { code: 'DELIVERY_UNKNOWN', label: '交期待核对', level: 'warning', days: null, type: 'warning', effect: 'light' },
    { code: 'OUTSIDE_WINDOW', label: '未到提醒时间', level: 'info', days: 6, type: 'info', effect: 'light' },
    { code: 'ENDED', label: '已结束', level: 'info', days: -2, type: 'info', effect: 'light' },
  ] as const)('交期状态用 Tag 展示 $label，按紧急程度加深', async item => {
    vi.mocked(api.fetchPurchaseTrackingArrivals).mockResolvedValue(page([arrival({ days_remaining: item.days, risks: [{ code: item.code, label: item.label, level: item.level, rank: 20 }] })]))
    await open()
    const state = wrapper!.get('[data-testid="arrival-delivery-status"]')
    expect(state.text()).toBe(item.label)
    expect(state.classes()).toContain('el-tag')
    expect(state.classes()).toContain(`el-tag--${item.type}`)
    expect(state.classes()).toContain(`el-tag--${item.effect}`)
  })

  it('混合风险优先显示交期倒计时，保留退货和核对内容', async () => {
    vi.mocked(api.fetchPurchaseTrackingArrivals).mockResolvedValue(page([arrival({
      days_remaining: 1,
      return_pending: true,
      verification_notes: ['收货记录待核对'],
      risks: [
        { code: 'RETURN_PENDING', label: '退货待处理', level: 'warning', rank: 75 },
        { code: 'NEAR_DUE', label: '1 天后到期', level: 'warning', rank: 60 },
      ],
    })]))
    await open()
    const state = wrapper!.get('[data-testid="arrival-delivery-status"]')
    expect(state.text()).toBe('1 天后到期、退货待处理、收货记录待核对')
    expect(state.attributes('title')).toBe(state.text())
    expect(state.classes()).toContain('el-tag--dark')
  })

  it('采购提醒是独立页面，只显示未采购量', async () => {
    await open('/purchase-alerts')
    expect(wrapper!.get('h1').text()).toBe('采购提醒')
    expect(wrapper!.find('[data-tab]').exists()).toBe(false)
    expect(wrapper!.get('thead').text()).toContain('待采购')
    expect(wrapper!.get('tbody').text()).toContain('总单未建')
    expect(api.fetchPurchaseTrackingCoverage).toHaveBeenCalled()
    expect(api.fetchPurchaseTrackingArrivals).not.toHaveBeenCalled()
  })

  it('采购提醒显示最晚采购日和时间风险筛选，保留后端紧急顺序', async () => {
    vi.mocked(api.fetchPurchaseTrackingCoverage).mockResolvedValue(page([
      coverage({ task_number: '紧急订单', latest_purchase_date: '2026-11-04', risks: [{ code: 'PURCHASE_OVERDUE', label: '采购已逾期2天', level: 'danger', rank: 110 }] }),
      coverage({ row_key: 'coverage:task-2:line-2', production_task_id: 'task-2', task_number: '稍后订单', latest_purchase_date: '2026-11-10' }),
    ]))
    await open('/purchase-alerts')
    expect(wrapper!.get('thead').text()).toContain('最晚采购日')
    expect(wrapper!.get('tbody').text()).toContain('2026-11-04')
    expect(wrapper!.get('tbody tr').text()).toContain('紧急订单')
    wrapper!.findAllComponents(ElSelect)[1]!.vm.$emit('update:modelValue', 'BOM_PURCHASE_TIMEOUT')
    await flushPromises()
    expect(api.fetchPurchaseTrackingCoverage).toHaveBeenLastCalledWith(expect.objectContaining({ risk: 'BOM_PURCHASE_TIMEOUT' }), expect.any(AbortSignal))
  })

  it.each([
    { code: 'PURCHASE_UPCOMING', label: '还剩5天采购', level: 'info', days: 5, type: 'warning', effect: 'light' },
    { code: 'PURCHASE_UPCOMING', label: '还剩2天采购', level: 'info', days: 2, type: 'warning', effect: 'light' },
    { code: 'PURCHASE_UPCOMING', label: '还剩1天采购', level: 'info', days: 1, type: 'warning', effect: 'dark' },
    { code: 'PURCHASE_DUE_TODAY', label: '今天最晚采购', level: 'danger', days: 0, type: 'danger', effect: 'dark' },
    { code: 'PURCHASE_OVERDUE', label: '已超最晚采购日2天', level: 'danger', days: -2, type: 'danger', effect: 'dark' },
    { code: 'SCHEDULE_DATE_UNKNOWN', label: '排产入库日期待核对', level: 'warning', days: null, type: 'warning', effect: 'dark' },
    { code: 'ORDER_DELIVERY_UNKNOWN', label: '订单交期待核对', level: 'warning', days: null, type: 'warning', effect: 'dark' },
    { code: 'BOM_CONFIRMATION_UNKNOWN', label: 'BOM确认时间待核对', level: 'warning', days: null, type: 'warning', effect: 'dark' },
    { code: 'PURCHASE_RULE_UNKNOWN', label: '采购提醒规则待设置', level: 'warning', days: null, type: 'warning', effect: 'dark' },
    { code: 'BOM_PURCHASE_TIMEOUT', label: 'BOM确认后已超采购期限', level: 'warning', days: null, type: 'warning', effect: 'light' },
    { code: 'PENDING_PURCHASE', label: '普通待采购', level: 'info', days: null, type: 'info', effect: 'light' },
    { code: 'ENDED', label: '已结束', level: 'info', days: -2, type: 'info', effect: 'light' },
  ] as const)('采购提醒用 Tag 展示 $label，依据实际期限风险加深', async item => {
    vi.mocked(api.fetchPurchaseTrackingCoverage).mockResolvedValue(page([coverage({
      purchase_days_remaining: item.days,
      risks: [{ code: item.code, label: item.label, level: item.level, rank: 40 }],
    })]))
    await open('/purchase-alerts')
    const state = wrapper!.get('[data-testid="coverage-purchase-status"]')
    expect(state.text()).toBe(item.label)
    expect(state.classes()).toContain(`el-tag--${item.type}`)
    expect(state.classes()).toContain(`el-tag--${item.effect}`)
  })

  it('采购倒计时优先于BOM超时文字，但保留完整原因', async () => {
    vi.mocked(api.fetchPurchaseTrackingCoverage).mockResolvedValue(page([coverage({
      latest_purchase_date: '2026-11-07', purchase_days_remaining: 1,
      risks: [
        { code: 'BOM_PURCHASE_TIMEOUT', label: 'BOM确认后已超采购期限', level: 'warning', rank: 90 },
        { code: 'PURCHASE_UPCOMING', label: '还剩1天采购', level: 'info', rank: 40 },
      ],
    })]))
    await open('/purchase-alerts')
    const state = wrapper!.get('[data-testid="coverage-purchase-status"]')
    expect(state.text()).toBe('还剩1天采购、BOM确认后已超采购期限')
    expect(state.attributes('title')).toBe(state.text())
    expect(state.classes()).toContain('el-tag--dark')
  })

  it('缺日期在对应列明显标注，缺失原因不会被未来采购日覆盖', async () => {
    vi.mocked(api.fetchPurchaseTrackingCoverage).mockResolvedValue(page([coverage({
      order_delivery_date: null, material_inbound_date: null, latest_purchase_date: null,
      risks: [
        { code: 'SCHEDULE_DATE_UNKNOWN', label: '排产入库日期待核对', level: 'warning', rank: 95 },
        { code: 'ORDER_DELIVERY_UNKNOWN', label: '订单交期待核对', level: 'warning', rank: 95 },
      ],
    }), coverage({
      row_key: 'coverage:other:line-2', production_task_id: 'task-2',
      latest_purchase_date: '2026-11-07', purchase_days_remaining: 1,
      risks: [
        { code: 'BOM_CONFIRMATION_UNKNOWN', label: 'BOM确认时间待核对', level: 'warning', rank: 95 },
        { code: 'PURCHASE_UPCOMING', label: '还剩1天采购', level: 'info', rank: 40 },
      ],
    })]))
    await open('/purchase-alerts')
    for (const id of ['coverage-order-date-missing', 'coverage-schedule-date-missing', 'coverage-purchase-date-missing']) {
      const missing = wrapper!.get(`[data-testid="${id}"]`)
      expect(missing.classes()).toContain('el-tag--warning')
      expect(missing.classes()).toContain('el-tag--dark')
    }
    const secondState = wrapper!.findAll('[data-testid="coverage-purchase-status"]')[1]!
    expect(secondState.text()).toBe('BOM确认时间待核对、还剩1天采购')
    expect(secondState.attributes('title')).toBe(secondState.text())
  })

  it('未排产不误报缺排产日期，规则缺失保留待核对说明', async () => {
    vi.mocked(api.fetchPurchaseTrackingCoverage).mockResolvedValue(page([coverage({
      scheduled: false, order_delivery_date: '2026-11-20', material_inbound_date: null,
      risks: [{ code: 'PENDING_PURCHASE', label: '普通待采购', level: 'info', rank: 20 }],
    }), coverage({
      row_key: 'coverage:other:line-2', production_task_id: 'task-2',
      material_inbound_date: '2026-11-09', latest_purchase_date: null,
      risks: [{ code: 'PURCHASE_RULE_UNKNOWN', label: '采购提醒规则待设置', level: 'warning', rank: 95 }],
    })]))
    await open('/purchase-alerts')
    expect(wrapper!.find('[data-testid="coverage-schedule-date-missing"]').exists()).toBe(false)
    expect(wrapper!.findAll('[data-testid="coverage-purchase-date-missing"]')).toHaveLength(1)
    const unknown = wrapper!.get('[data-testid="coverage-purchase-date-missing"]')
    expect(unknown.text()).toBe('待核对')
    expect(unknown.attributes('title')).toBe('采购提醒规则待设置')
    expect(wrapper!.get('tbody tr').text()).toContain('未排产')
  })

  it('提醒设置只对有管理权限的采购提醒页显示，未打开不读取规则', async () => {
    await open('/purchase-alerts')
    expect(wrapper!.find('[data-testid="open-tracking-policy"]').exists()).toBe(false)
    wrapper!.unmount(); wrapper = undefined
    auth.permissions.push('access_control.manage_notifications')
    await open('/purchase-tracking')
    expect(wrapper!.find('[data-testid="open-tracking-policy"]').exists()).toBe(false)
    await router.push('/purchase-alerts'); await flushPromises()
    expect(wrapper!.find('[data-testid="open-tracking-policy"]').exists()).toBe(true)
    expect(api.fetchPurchaseTrackingPolicy).not.toHaveBeenCalled()
  })

  it('设置成功后重新读取提醒清单，离开提醒页后不保留打开状态', async () => {
    auth.permissions.push('access_control.manage_notifications')
    vi.mocked(api.fetchPurchaseTrackingPolicy).mockResolvedValue({ bom_timeout_days: 2, category_lead_days: {}, categories: [], etag: 'v1', can_manage: true })
    await open('/purchase-alerts')
    await wrapper!.get('[data-testid="open-tracking-policy"]').trigger('click'); await flushPromises()
    const dialog = wrapper!.findComponent(PurchaseTrackingPolicyDialog)
    expect(dialog.props('modelValue')).toBe(true)
    dialog.vm.$emit('saved'); await flushPromises()
    expect(api.fetchPurchaseTrackingCoverage).toHaveBeenCalledTimes(2)
    await router.push('/purchase-tracking'); await flushPromises()
    await router.push('/purchase-alerts'); await flushPromises()
    expect(wrapper!.findComponent(PurchaseTrackingPolicyDialog).props('modelValue')).toBe(false)
  })

  it('采购提醒按任务合并单元格，不跨任务或跨分页合并', async () => {
    vi.mocked(api.fetchPurchaseTrackingCoverage).mockResolvedValue(page([
      coverage(),
      coverage({ row_key: 'coverage:product-2:line-2', product_line_id: 'product-2' }),
      coverage({ row_key: 'coverage:other:line-3', production_task_id: 'task-2', task_number: 'SC-2' }),
    ], 21))
    await open('/purchase-alerts?page=2')
    const rows = wrapper!.findAll('.el-table__body tbody tr')
    expect(wrapper!.get('thead').text()).toContain('生产订单号')
    expect(rows[0]!.findAll('td')[0]!.get('.tracking-strong').text()).toBe('SC-1')
    expect(rows[0]!.findAll('td')[0]!.attributes('rowspan')).toBe('2')
    expect(rows[1]!.text()).not.toContain('SC-1')
    expect(rows[2]!.findAll('td')[0]!.text()).toBe('SC-2')
    expect(rows[2]!.findAll('td')[0]!.attributes('rowspan')).toBe('1')
  })

  it('品名悬停复用采购属性，BOM创建时间和订单交期独立展示', async () => {
    vi.mocked(api.fetchPurchaseTrackingCoverage).mockResolvedValue(page([coverage({
      bom_created_at: '2026-11-01T09:20:30+08:00', order_delivery_date: '2026-12-15',
      material_attributes_snapshot: { fields: [{ key: 'thickness', label: '厚度', value: '1.5 mm' }, { key: 'material', label: '材质', value: 'Q235' }] },
    })]))
    await open('/purchase-alerts')
    const headers = wrapper!.get('thead').text()
    expect(headers).toContain('品名')
    expect(headers).not.toContain('BOM材料')
    expect(headers).toContain('BOM创建时间')
    expect(headers).toContain('订单交期')
    expect(wrapper!.get('tbody').text()).toContain('2026-11-01')
    expect(wrapper!.get('tbody').text()).toContain('2026-12-15')
    const tooltip = wrapper!.findAllComponents(ElTooltip).find(item => item.props('virtualTriggering'))!
    expect(tooltip.exists()).toBe(true)
    await wrapper!.findAll('tbody td').find(cell => cell.find('[data-testid="coverage-material-name"]').exists())!.trigger('mouseenter')
    await vi.waitFor(() => expect(document.body.textContent).toContain('1.5 mm'))
    expect(document.body.textContent).toContain('Q235')
    expect(wrapper!.get('tbody').text()).not.toContain('1.5 mm')
  })

  it.each([
    { path: '/purchase-tracking', name: '材料', quantity: '实际收货', prefix: 'arrival' },
    { path: '/purchase-alerts', name: '品名', quantity: '待采购', prefix: 'coverage' },
  ])('$path 从品名、规格及数量显示完整属性，浮层锚定当前可见单元格', async item => {
    const snapshot = { fields: [{ key: 'thickness', label: '厚度', value: '1.5 mm' }, { key: 'material', label: '材质', value: 'Q235' }] }
    vi.mocked(api.fetchPurchaseTrackingArrivals).mockResolvedValue(page([
      arrival({ material_attributes_snapshot: snapshot }),
      arrival({ row_key: 'arrival:line-2', material_attributes_snapshot: { fields: [{ key: 'thickness', label: '厚度', value: '2.0 mm' }] } }),
    ]))
    vi.mocked(api.fetchPurchaseTrackingCoverage).mockResolvedValue(page([
      coverage({ material_attributes_snapshot: snapshot }),
      coverage({ row_key: 'coverage:line-2', material_attributes_snapshot: { fields: [{ key: 'thickness', label: '厚度', value: '2.0 mm' }] } }),
    ]))
    await open(item.path)
    const tooltip = wrapper!.findAllComponents(ElTooltip).find(instance => instance.props('virtualTriggering'))!
    expect(tooltip.props('visible')).toBe(false)
    expect(tooltip.props('teleported')).toBe(true)
    const headers = wrapper!.findAll('thead th').map(header => header.text())
    const cells = wrapper!.get('tbody tr').findAll('td')
    for (const label of [item.name, '规格', item.quantity]) {
      const cell = cells[headers.indexOf(label)]!
      await cell.trigger('mouseenter')
      expect(tooltip.props('visible')).toBe(true)
      expect(tooltip.props('virtualRef')).toBe(cell.element)
      await vi.waitFor(() => expect(document.body.querySelector('.purchase-tracking-material-tooltip')?.textContent).toContain('1.5 mm'))
      expect(document.body.querySelector('.purchase-tracking-material-tooltip')?.textContent).toContain('Q235')
      const column = wrapper!.findAllComponents({ name: 'ElTableColumn' }).find(instance => instance.props('label') === label)!
      expect(column.props('showOverflowTooltip')).not.toBe(true)
    }
    const nextCell = wrapper!.findAll('tbody tr')[1]!.findAll('td').find(cell => cell.find(`[data-testid="${item.prefix}-specification"]`).exists())!
    await nextCell.trigger('mouseenter')
    expect(tooltip.props('virtualRef')).toBe(nextCell.element)
    await vi.waitFor(() => expect(document.body.querySelector('.purchase-tracking-material-tooltip')?.textContent).toContain('2.0 mm'))
    expect(document.body.querySelector('.purchase-tracking-material-tooltip')?.textContent).not.toContain('1.5 mm')
    // 合并列仅验证事件过滤，避免 jsdom 缺少 Range 布局测量而触发组件库的截断提示。
    wrapper!.findComponent({ name: 'ElTable' }).vm.$emit('cell-mouse-enter', common(), { label: '生产订单号' }, cells[0]!.element)
    await flushPromises()
    expect(tooltip.props('visible')).toBe(false)
    await nextCell.trigger('mouseenter')
    await nextCell.trigger('mouseleave')
    expect(tooltip.props('visible')).toBe(false)
  })

  it.each([
    { path: '/purchase-tracking', prefix: 'arrival' },
    { path: '/purchase-alerts', prefix: 'coverage' },
  ])('$path 保留键盘属性入口，滚动和刷新关闭旧属性', async item => {
    await open(item.path)
    const tooltip = wrapper!.findAllComponents(ElTooltip).find(instance => instance.props('virtualTriggering'))!
    for (const suffix of ['material-name', 'specification']) {
      const trigger = wrapper!.get(`[data-testid="${item.prefix}-${suffix}"]`)
      await trigger.trigger('focus')
      expect(tooltip.props('visible')).toBe(true)
      expect(tooltip.props('virtualRef')).toBe(trigger.element)
      await trigger.trigger('keydown', { key: 'Escape' })
      expect(tooltip.props('visible')).toBe(false)
      await trigger.trigger('focus')
      await trigger.trigger('blur')
      expect(tooltip.props('visible')).toBe(false)
    }
    const trigger = wrapper!.get(`[data-testid="${item.prefix}-specification"]`)
    await trigger.trigger('focus')
    await wrapper!.get('.erp-list-table-frame').trigger('scroll')
    expect(tooltip.props('visible')).toBe(false)
    await trigger.trigger('focus')
    await wrapper!.get('[data-testid="refresh-tracking"]').trigger('click')
    await flushPromises()
    expect(tooltip.props('visible')).toBe(false)
  })

  it('旧的 coverage 深链接仍能显示采购提醒内容', async () => {
    await open('/purchase-tracking?tab=coverage&production_task_id=task-1')
    await flushPromises()
    expect(wrapper!.get('h1').text()).toBe('采购提醒')
  })

  it('交期页按订单号、供应商和交期保持独立列', async () => {
    await open()
    const row = wrapper!.get('tbody tr')
    const cells = row.findAll('td').map(cell => cell.text())
    expect(cells[2]).toBe('CG-1')
    expect(cells[3]).toBe('测试供应商')
    expect(cells[13]).toBe('2026-11-03')
  })

  it('筛选和分页都提交到接口，不在页面内假筛选', async () => {
    vi.mocked(api.fetchPurchaseTrackingArrivals).mockResolvedValue(page([arrival()], 41))
    await open('/purchase-tracking?page=2')
    expect(api.fetchPurchaseTrackingArrivals).toHaveBeenLastCalledWith(expect.objectContaining({ page: 2 }), expect.any(AbortSignal))
    wrapper!.findAllComponents(ElSelect)[1]!.vm.$emit('update:modelValue', 'RETURN_PENDING')
    await flushPromises()
    expect(api.fetchPurchaseTrackingArrivals).toHaveBeenLastCalledWith(expect.objectContaining({ page: 1, risk: 'RETURN_PENDING' }), expect.any(AbortSignal))
  })

  it('快速切换独立页面时，迟到的旧请求不能覆盖新列表', async () => {
    const pending = deferred<ReturnType<typeof page<PurchaseTrackingArrival>>>()
    vi.mocked(api.fetchPurchaseTrackingArrivals).mockReturnValueOnce(pending.promise)
    await open()
    await router.push('/purchase-alerts')
    await flushPromises()
    pending.resolve(page([arrival({ material_name: '迟到的旧材料' })]))
    await flushPromises()
    expect(wrapper!.get('tbody').text()).toContain('总单未建')
    expect(wrapper!.get('tbody').text()).not.toContain('迟到的旧材料')
  })

  it('加载失败清空旧数据并允许重试', async () => {
    await open()
    vi.mocked(api.fetchPurchaseTrackingArrivals).mockRejectedValueOnce({ response: { status: 503, data: { error: { message: '服务暂不可用' } } } })
    await wrapper!.get('[data-testid="refresh-tracking"]').trigger('click'); await flushPromises()
    expect(wrapper!.text()).toContain('服务暂不可用')
    expect(wrapper!.find('tbody tr[data-row-key]').exists()).toBe(false)
    vi.mocked(api.fetchPurchaseTrackingArrivals).mockResolvedValueOnce(page([]))
    await wrapper!.get('[data-testid="retry-tracking"]').trigger('click'); await flushPromises()
    expect(wrapper!.text()).toContain('暂无未到齐批次')
  })

  it('只允许跳转到真实本地动作', async () => {
    vi.mocked(api.fetchPurchaseTrackingArrivals).mockResolvedValue(page([arrival({ actions: [
      { kind: 'view_order', label: '外链', path: '//evil.test/path' },
      { kind: 'view_order', label: '未知页', path: '/not-a-real-page' },
      { kind: 'view_order', label: '查看批次', path: '/purchase-orders/order-1/details' },
    ] })]))
    await open()
    expect(wrapper!.get('tbody').text()).not.toContain('外链')
    expect(wrapper!.get('tbody').text()).not.toContain('未知页')
    await wrapper!.get('tbody button').trigger('click'); await flushPromises()
    expect(router.currentRoute.value.name).toBe('purchase-order-detail')
  })

  it('无采购查看权限不请求列表和筛选选项', async () => {
    auth.permissions = []
    await open()
    expect(wrapper!.text()).toContain('无权查看采购跟踪')
    expect(api.fetchPurchaseTrackingArrivals).not.toHaveBeenCalled()
    expect(api.fetchPurchaseTrackingFilterOptions).not.toHaveBeenCalled()
  })

  it('筛选选项失败不阻塞列表，并提供重试', async () => {
    vi.mocked(api.fetchPurchaseTrackingFilterOptions).mockRejectedValueOnce(new Error('offline'))
    await open()
    expect(wrapper!.text()).toContain('生产订单筛选选项加载失败')
    expect(wrapper!.find('tbody tr').exists()).toBe(true)
    const retry = wrapper!.findAll('button').find(button => button.text() === '重试选项')!
    await retry.trigger('click'); await flushPromises()
    expect(api.fetchPurchaseTrackingFilterOptions).toHaveBeenCalledTimes(2)
  })

  it('深链接定位后可清除定位条件', async () => {
    const rowKey = 'arrival:line-1'
    await open(`/purchase-tracking?production_task_id=task-1&row_key=${rowKey}`)
    expect(api.fetchPurchaseTrackingArrivals).toHaveBeenLastCalledWith(expect.objectContaining({ row_key: rowKey, production_task_id: 'task-1' }), expect.any(AbortSignal))
    expect(wrapper!.get('[data-testid="clear-tracking-location"]')).toBeTruthy()
    await wrapper!.get('[data-testid="clear-tracking-location"]').trigger('click'); await flushPromises()
    expect(router.currentRoute.value.query.row_key).toBeUndefined()
  })
})

