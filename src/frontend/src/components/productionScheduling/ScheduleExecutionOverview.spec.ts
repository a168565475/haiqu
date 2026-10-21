import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ScheduleExecutionOverview from './ScheduleExecutionOverview.vue'
import type { ScheduleProductExecution } from '@/types/scheduleExecution'
import { formatScheduleMoney, formatScheduleQuantity, formatScheduleUnitPrice, groupScheduleOutsourcingOrders } from '@/utils/scheduleExecution'

const navigation = vi.hoisted(() => ({ push: vi.fn() }))
vi.mock('vue-router', () => ({ useRouter: () => navigation }))
const wrappers: ReturnType<typeof mount>[] = []
function fixture(): ScheduleProductExecution {
  return {
    schedule_product_id: 'schedule-product-1', estimated_wage: '1000.00', reported_amount: '350.00',
    estimated_amount_status: 'READY', reported_amount_status: 'READY',
    internal_plans: [{
      category: 'METAL', craft_id: 'craft-1', craft_name: '管材加工', workshop_id: 'workshop-1', workshop_name: '金工车间',
      plan_date: '2026-10-27', milestone: '金工回货日期', planned_quantity: '1000', unit_name: '套',
      estimated_wage: '1000.00', reported_amount: '350.00', estimated_amount_status: 'READY', reported_amount_status: 'READY',
      progress_percent: 80, plan_status: 'IN_PROGRESS', plan_status_display: '进行中', wage_status: 'APPROVED', reason: '',
      scheme_id: 'scheme-1', can_view_wage: true, can_view_reports: true,
    }],
    outsourcing: { allowed: true, planned_amount: '2.00', records: [{
      id: 'allocation-1', order_id: 'order-1', order_kind: 'TUBE', order_number: 'WF-001', craft_name: '喷塑',
      part_name: '椅架腿管', factory_name: '加工厂', planned_quantity: '20000', quantity_unit: '支',
      dispatched_quantity: '15000', dispatched_unit: '支', received_quantity: null, received_unit: '支', shortage_quantity: null,
      unit_price: '0.0001', price_unit: '元/支', planned_amount: '2.00', expected_return_date: '2026-10-27',
      status: 'PROCESSING', status_display: '加工中', detail_access: 'TUBE', reason: '',
    }] },
    material_issues: { allowed: true, records: [{ id: 'issue-1', issue_number: 'LL-001', workshop_name: '金工车间', recipient_name: '员工', line_count: 3, issue_at: '2026-10-20', issued_at: '2026-10-20T01:20:00Z', status: 'ISSUED', status_display: '已出库' }] },
  }
}
function createView(summary: ScheduleProductExecution | null = fixture(), extraProps: Record<string, unknown> = {}) {
  const wrapper = mount(ScheduleExecutionOverview, {
    props: { scheduleId: 'schedule-1', productionTaskId: 'task-1', productLineId: 'product-line-1', summary, loading: false, failed: false, active: true, ...extraProps },
    global: { stubs: { WageSchemeDetailDialog: true } },
  })
  wrappers.push(wrapper)
  return wrapper
}
beforeEach(() => { vi.clearAllMocks() })
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()) })

describe('排产金额字符串展示', () => {
  it('保留大金额精度、两位小数及真实零，缺值不变成零', () => {
    expect(formatScheduleMoney('9007199254740993.15')).toBe('¥9,007,199,254,740,993.15')
    expect(formatScheduleMoney('0')).toBe('¥0.00')
    expect(formatScheduleMoney('9.995')).toBe('¥10.00')
    expect(formatScheduleMoney(null)).toBe('—')
    expect(formatScheduleMoney('not-a-price')).toBe('—')
  })
  it('小单价保持四位有效精度，数量不进行跨单位相加', () => {
    expect(formatScheduleUnitPrice('0.0001')).toBe('¥0.0001')
    expect(formatScheduleUnitPrice('0.8000')).toBe('¥0.8')
    expect(formatScheduleQuantity('9007199254740993.5000', '米')).toBe('9,007,199,254,740,993.5 米')
    expect(formatScheduleQuantity(null, '支')).toBe('—')
  })
})

describe('本产品外发单归并', () => {
  it('一张单多条明细合并一行、工厂去重，部位不再成为表格列', () => {
    const summary = fixture()
    const first = summary.outsourcing.records[0]!
    summary.outsourcing.records.push({ ...first, id: 'allocation-2', part_name: '扶手管', factory_name: '加工厂乙', planned_quantity: '10000', planned_amount: '1.00' })
    summary.outsourcing.records.push({ ...first, id: 'allocation-3', planned_quantity: '5000', planned_amount: '0.50' })
    const originalRecords = structuredClone(summary.outsourcing.records)
    const wrapper = createView(summary)
    const table = wrapper.get('[data-testid="outsourcing-records-table"]')
    expect(table.findAll('tbody tr')).toHaveLength(1)
    expect(table.findAll('th')).toHaveLength(13)
    expect(table.findAll('th').map(header => header.text())).not.toContain('部位')
    expect(wrapper.text()).toContain('本产品外发单')
    expect(wrapper.text()).toContain('共 1 张')
    const row = table.get('[data-record-id="TUBE:order-1"]')
    expect(row.findAll('td')[2]!.text()).toBe('加工厂、加工厂乙')
    expect(row.findAll('td')[2]!.attributes('title')).toBe('加工厂、加工厂乙')
    expect(row.get('[data-field="planned_quantity"]').text()).toBe('35,000 支')
    expect(row.get('[data-field="planned_amount"]').text()).toBe('¥3.50')
    expect(summary.outsourcing.records).toEqual(originalRecords)
    expect(summary.outsourcing.planned_amount).toBe('2.00')
    expect(wrapper.text()).toContain('不代表成品排产数')
  })
  it('不同订单或同ID不同来源各成一行，重复record.id仅计一次', () => {
    const first = fixture().outsourcing.records[0]!
    const rows = groupScheduleOutsourcingOrders([
      first, { ...first },
      { ...first, id: 'allocation-2', order_id: 'order-2' },
      { ...first, id: 'P4:allocation-1', order_kind: 'P4' },
    ])
    expect(rows.map(row => row.id)).toEqual(['TUBE:order-1', 'TUBE:order-2', 'P4:order-1'])
    expect(rows[0]).toMatchObject({ record_count: 1, planned_quantity: '20000', planned_amount: '2.0000' })
  })
  it('四位金额先精确相加再展示两位，不逐行提前舍入', () => {
    const first = fixture().outsourcing.records[0]!
    const [row] = groupScheduleOutsourcingOrders([
      { ...first, planned_amount: '0.0049' },
      { ...first, id: 'allocation-2', planned_amount: '0.0049' },
    ])
    expect(row!.planned_amount).toBe('0.0098')
    expect(formatScheduleMoney(row!.planned_amount)).toBe('¥0.01')
  })
  it('大金额和数量保持整数精度，真实零保持零', () => {
    const first = fixture().outsourcing.records[0]!
    const [large] = groupScheduleOutsourcingOrders([
      { ...first, planned_amount: '9007199254740993.0001', planned_quantity: '9007199254740993' },
      { ...first, id: 'allocation-2', planned_amount: '0.0002', planned_quantity: '1' },
    ])
    expect(large!.planned_amount).toBe('9007199254740993.0003')
    expect(large!.planned_quantity).toBe('9007199254740994')
    const [zero] = groupScheduleOutsourcingOrders([{ ...first, planned_quantity: '0', planned_amount: '0', unit_price: '0' }])
    expect(zero).toMatchObject({ planned_quantity: '0', planned_amount: '0.0000', unit_price: '0', unit_price_status: 'READY' })
    expect(formatScheduleMoney(zero!.planned_amount)).toBe('¥0.00')
  })
  it('任一金额或数量缺失不汇总局部数，不从实发实收新算短少', () => {
    const first = fixture().outsourcing.records[0]!
    const [row] = groupScheduleOutsourcingOrders([
      { ...first, received_quantity: '1000' },
      { ...first, id: 'allocation-2', planned_amount: null, planned_quantity: null, dispatched_quantity: null, received_quantity: '500' },
    ])
    expect(row).toMatchObject({ planned_amount: null, planned_quantity: null, dispatched_quantity: null, received_quantity: '1500', shortage_quantity: null })
    expect(row!.planned_amount_note).toContain('不完整合计')
    expect(row!.quantity_notes.planned_quantity).toContain('不可用')
  })
  it('不同单位和后端已标多种单位都保持未知，不混加或漏掉', () => {
    const first = fixture().outsourcing.records[0]!
    const summary = fixture()
    summary.outsourcing.records = [
      first,
      { ...first, id: 'allocation-2', quantity_unit: '米', dispatched_unit: '多种单位', dispatched_quantity: null },
    ]
    const [row] = groupScheduleOutsourcingOrders(summary.outsourcing.records)
    expect(row).toMatchObject({ planned_quantity: null, quantity_unit: '多种单位', dispatched_quantity: null, dispatched_unit: '多种单位' })
    const wrapper = createView(summary)
    const cells = wrapper.get('[data-record-id="TUBE:order-1"]')
    expect(cells.get('[data-field="planned_quantity"]').text()).toBe('多种单位')
    expect(cells.get('[data-field="dispatched_quantity"]').text()).toBe('多种单位')
  })
  it('等值不同精度单价合并为一个价格，不同有效价格显示多种单价', () => {
    const first = fixture().outsourcing.records[0]!
    const [samePrice] = groupScheduleOutsourcingOrders([
      { ...first, unit_price: '0.8' }, { ...first, id: 'allocation-2', unit_price: '0.8000' },
    ])
    expect(samePrice).toMatchObject({ unit_price: '0.8', unit_price_status: 'READY', price_unit: '元/支' })
    const summary = fixture()
    summary.outsourcing.records.push({ ...first, id: 'allocation-2', unit_price: '1.6' })
    const wrapper = createView(summary)
    expect(wrapper.get('[data-field="unit_price"]').text()).toBe('多种单价')
    expect(wrapper.get('[data-field="unit_price"]').attributes('title')).toContain('不取平均')
  })
  it('计价单位不同也是多种单价；存在缺价优先显示未知', () => {
    const first = fixture().outsourcing.records[0]!
    const [differentUnit] = groupScheduleOutsourcingOrders([
      first, { ...first, id: 'allocation-2', price_unit: '元/米' },
    ])
    expect(differentUnit).toMatchObject({ unit_price: null, unit_price_status: 'MULTIPLE', price_unit: '多种单位' })
    const summary = fixture()
    summary.outsourcing.records.push({ ...first, id: 'allocation-2', unit_price: null })
    summary.outsourcing.records.push({ ...first, id: 'allocation-3', unit_price: '2.0' })
    const wrapper = createView(summary)
    expect(wrapper.get('[data-field="unit_price"]').text()).toBe('—')
    expect(wrapper.get('[data-field="unit_price"]').attributes('title')).toContain('缺少加工单价')
    expect(wrapper.get('[data-testid="outsourcing-records-table"]').text()).toContain('按明细计价')
    expect(wrapper.get('[data-testid="outsourcing-records-table"]').text()).not.toContain('多种单价')
  })
})

describe('排产产品关联信息', () => {
  it('每真实工艺独立显示，报工金额不按报工进度重算', () => {
    const summary = fixture()
    summary.internal_plans.push({ ...summary.internal_plans[0]!, craft_id: 'craft-2', craft_name: '布面打孔', workshop_id: 'workshop-2', scheme_id: 'scheme-2' })
    const wrapper = createView(summary)
    expect(wrapper.findAll('.schedule-execution__table--internal tbody tr')).toHaveLength(2)
    expect(wrapper.get('[data-craft-id="craft-1"]').text()).toContain('80%')
    expect(wrapper.get('[data-craft-id="craft-1"]').text()).toContain('¥350.00')
    expect(wrapper.get('[data-craft-id="craft-1"]').text()).not.toContain('¥800.00')
    expect(wrapper.get('[data-craft-id="craft-1"]').findAll('td')[3]!.text()).toBe('金工回货')
    expect(wrapper.get('[data-craft-id="craft-1"]').findAll('td')[3]!.attributes('title')).toBe('金工回货日期')
    expect(wrapper.get('.schedule-execution__table--outsourcing').text()).toContain('¥0.0001')
    expect(wrapper.get('.schedule-execution__table--materials').text()).toContain('2026-10-20 09:20')
  })
  it('计划与报工入口传递当前行真实范围', async () => {
    const wrapper = createView()
    const links = wrapper.get('[data-craft-id="craft-1"]').findAll('button')
    await links[0]!.trigger('click')
    expect(navigation.push).toHaveBeenLastCalledWith({ path: '/workshop/plans/metalworking', query: { schedule_id: 'schedule-1', schedule_product_id: 'schedule-product-1' } })
    await links[2]!.trigger('click')
    expect(navigation.push).toHaveBeenLastCalledWith({ name: 'work-report-days', query: { schedule_product_id: 'schedule-product-1', workshop_id: 'workshop-1', craft_id: 'craft-1' } })
    await wrapper.get('.schedule-execution__all').trigger('click')
    expect(navigation.push).toHaveBeenLastCalledWith({ name: 'material-issues', query: { production_task_id: 'task-1', product_line_id: 'product-line-1' } })
  })
  it('工价入口打开当前行方案，不创建新工价', async () => {
    const wrapper = createView()
    await wrapper.get('[data-craft-id="craft-1"]').findAll('button')[1]!.trigger('click')
    await flushPromises()
    expect(wrapper.get('wage-scheme-detail-dialog-stub').attributes('schemeid')).toBe('scheme-1')
    expect(wrapper.get('wage-scheme-detail-dialog-stub').attributes('modelvalue')).toBe('true')
    expect(navigation.push).not.toHaveBeenCalled()
  })
  it.each([
    ['TUBE', 'TUBE', '/workshop/outsourcing/tube/order-1'],
    ['P4', 'METAL', '/workshop/outsourcing/rework/order-1'],
    ['REGULAR', 'METAL', { path: '/workshop/outsourcing/order-1', query: { view: 'metal' } }],
  ] as const)('外发 %s 使用正确详情路由', async (kind, access, expected) => {
    const summary = fixture()
    summary.outsourcing.records[0]!.order_kind = kind
    summary.outsourcing.records[0]!.detail_access = access
    const wrapper = createView(summary)
    await wrapper.get('.schedule-execution__table--outsourcing button').trigger('click')
    expect(navigation.push).toHaveBeenLastCalledWith(expected)
  })
  it('无权限区别于暂无记录，并禁用工价及报工入口', () => {
    const summary = fixture()
    summary.outsourcing = { allowed: false, records: [], planned_amount: null }
    summary.material_issues = { allowed: false, records: [] }
    summary.internal_plans[0]!.can_view_reports = false
    summary.internal_plans[0]!.can_view_wage = false
    const wrapper = createView(summary)
    expect(wrapper.text()).toContain('没有查看本产品外发记录的权限')
    expect(wrapper.text()).toContain('没有查看本产品领料记录的权限')
    expect(wrapper.text()).not.toContain('暂无关联外发记录')
    expect(wrapper.find('.schedule-execution__all').exists()).toBe(false)
    expect(wrapper.get('[data-craft-id="craft-1"]').findAll('button')[1]!.attributes('disabled')).toBeDefined()
    expect(wrapper.get('[data-craft-id="craft-1"]').findAll('button')[2]!.attributes('disabled')).toBeDefined()
  })
  it('数量基数不匹配保持预计金额未知，真实报工零保持零', () => {
    const summary = fixture()
    summary.estimated_wage = null
    summary.estimated_amount_status = 'QUANTITY_BASIS_MISMATCH'
    summary.internal_plans[0]!.estimated_wage = null
    summary.internal_plans[0]!.estimated_amount_status = 'QUANTITY_BASIS_MISMATCH'
    summary.internal_plans[0]!.reported_amount = '0.00'
    const wrapper = createView(summary)
    expect(wrapper.get('[data-testid="estimated-amount-reason"]').text()).toContain('排产数量与工价计价基数不同')
    const amounts = wrapper.get('[data-craft-id="craft-1"]').findAll('td.is-money')
    expect(amounts[0]!.text()).toBe('—')
    expect(amounts[1]!.text()).toBe('¥0.00')
  })
  it('加载及失败不显示假空数据，作废排产不提供无效计划跳转', () => {
    expect(createView(null, { loading: true }).text()).toContain('正在加载')
    expect(createView(null, { failed: true }).text()).toContain('重试关联信息')
    expect(createView(null, { failed: true }).text()).not.toContain('暂无关联')
    const wrapper = createView(fixture(), { active: false })
    expect(wrapper.get('[data-craft-id="craft-1"]').findAll('button')[0]!.attributes('disabled')).toBeDefined()
  })
})
