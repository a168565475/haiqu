import { describe, expect, it } from 'vitest'
import { notificationRoute } from './notificationTarget'

const id = '12345678-1234-1234-1234-123456789abc'
const target = { object_id: id, target_key: 'bom-detail', route_name: 'bom-preview', params: { bomId: id } }
describe('通知命名路由白名单', () => {
  it('使用route_name而非语义target_key', () => {
    expect(notificationRoute('BOM_CONFIRMED', target)).toEqual({ name: 'bom-preview', params: { bomId: id } })
  })
  it('任务BOM聚合使用任务UUID并进入BOM列表，旧单BOM预览继续兼容', () => {
    expect(notificationRoute('PRODUCTION_TASK_BOMS_CONFIRMED', {
      object_id: id, target_key: 'task-boms', route_name: 'boms', params: {},
    })).toEqual({ name: 'boms', params: {} })
    expect(() => notificationRoute('PRODUCTION_TASK_BOMS_CONFIRMED', target)).toThrow()
    expect(() => notificationRoute('PRODUCTION_TASK_BOMS_CONFIRMED', {
      ...target, route_name: 'boms', params: { bomId: id },
    })).toThrow()
  })
  it.each([
    { ...target, route_name: 'https://evil.test/' },
    { ...target, route_name: 'settings-access' },
    { ...target, params: { bomId: '//evil.test' } },
    { ...target, params: { bomId: id, url: 'https://evil.test' } },
    { ...target, object_id: '事件编号' },
  ])('拒绝外部URL、任意路由和非法参数 %#', value => {
    expect(() => notificationRoute('BOM_CONFIRMED', value)).toThrow()
  })
  it('未知事件、尚未就绪半成品事件不可跳转', () => {
    expect(() => notificationRoute('UNKNOWN', target)).toThrow()
    expect(() => notificationRoute('SEMI_FINISHED_RECEIPT_SUBMITTED', target)).toThrow()
    expect(() => notificationRoute('__proto__', target)).toThrow()
  })
  it('入库成功指向真实记录列表，装配事件由前端固定构造记录页签', () => {
    const semi = { ...target, route_name: 'semi-receipt-records', params: {} }
    expect(notificationRoute('INTERNAL_SEMI_RECEIPT_CONFIRMED', semi)).toEqual({ name: semi.route_name, params: {} })
    const assembly = { ...target, route_name: 'finished-goods-inventory', params: {} }
    expect(notificationRoute('ASSEMBLY_FINISHED_RECEIPT_CONFIRMED', assembly)).toEqual({ name: assembly.route_name, params: {}, query: { tab: 'records' } })
    expect(() => notificationRoute('INTERNAL_SEMI_RECEIPT_CONFIRMED', { ...semi, params: { receiptId: id } })).toThrow()
    expect(() => notificationRoute('ASSEMBLY_FINISHED_RECEIPT_CONFIRMED', { ...assembly, params: { receiptId: id } })).toThrow()
    expect(() => notificationRoute('ASSEMBLY_FINISHED_RECEIPT_CONFIRMED', { ...assembly, object_id: 'not-a-uuid' })).toThrow()
    expect(() => notificationRoute('ASSEMBLY_FINISHED_RECEIPT_CONFIRMED', semi)).toThrow()
  })
  it('出库成功只接受真实出库详情；所有消息输入均不得附加query', () => {
    const outbound = { ...target, route_name: 'finished-goods-outbound-detail', params: { outboundId: id } }
    expect(notificationRoute('FINISHED_GOODS_OUTBOUND_CONFIRMED', outbound)).toEqual({ name: outbound.route_name, params: { outboundId: id } })
    expect(() => notificationRoute('FINISHED_GOODS_OUTBOUND_CONFIRMED', { ...outbound, params: { receiptId: id } })).toThrow()
    const forgedBom = { ...target, query: { tab: 'records' } }
    const forgedAssembly = { ...target, route_name: 'finished-goods-inventory', params: {}, query: { tab: 'records' } }
    expect(() => notificationRoute('BOM_CONFIRMED', forgedBom)).toThrow()
    expect(() => notificationRoute('ASSEMBLY_FINISHED_RECEIPT_CONFIRMED', forgedAssembly)).toThrow()
  })
  it.each([
    ['SAMPLE_EFFECTIVE', 'sample-detail'], ['SAMPLE_RETURNED', 'sample-detail'],
    ['SAMPLE_REQUIREMENTS_COMPLETED', 'sample-material-detail'], ['SAMPLE_MATERIALS_SUBMITTED', 'sample-warehouse-review'],
    ['SAMPLE_MATERIAL_SHORTAGE', 'sample-material-detail'], ['SAMPLE_MATERIALS_AVAILABLE', 'sample-material-issue'],
    ['SAMPLE_MATERIAL_ISSUE_SUBMITTED', 'sample-material-issue-confirm'], ['SAMPLE_MATERIAL_ISSUED', 'sample-detail'],
    ['SAMPLE_PRODUCTION_READY', 'sample-detail'],
  ])('打样事件%s只进入已登记的真实样品页面', (code, route) => {
    const sampleId = 'abcdef12-1234-1234-1234-123456789abc'
    expect(notificationRoute(code!, { ...target, route_name: route!, params: { sampleId } })).toEqual({ name: route, params: { sampleId } })
    expect(() => notificationRoute(code!, { ...target, route_name: 'material-issue-detail', params: { issueId: id } })).toThrow()
  })
  it('两类委外分别进入真实对象页面，拒绝混传路由', () => {
    const regular = { ...target, route_name: 'warehouse-outsourcing-detail', params: { orderId: id } }
    const tube = { ...regular, route_name: 'warehouse-outsourcing-tube-detail', params: { id } }
    expect(notificationRoute('OUTSOURCING_ORDER_CREATED', regular).name).toBe(regular.route_name)
    expect(notificationRoute('TUBE_OUTSOURCING_ORDER_CREATED', tube).name).toBe(tube.route_name)
    expect(() => notificationRoute('OUTSOURCING_ORDER_CREATED', tube)).toThrow()
    expect(() => notificationRoute('TUBE_OUTSOURCING_ORDER_CREATED', regular)).toThrow()
  })
  it('旧委外通知兼容仓库入口，车间直交及旧管材参数严格保留对应对象', () => {
    expect(notificationRoute('OUTSOURCING_ORDER_CREATED', {
      ...target, route_name: 'workshop-outsourcing-detail', params: { orderId: id },
    })).toEqual({ name: 'warehouse-outsourcing-detail', params: { orderId: id } })
    for (const params of [{ id }, { orderId: id }] as Record<string, string>[]) {
      expect(notificationRoute('TUBE_OUTSOURCING_ORDER_CREATED', {
        ...target, route_name: 'workshop-outsourcing-tube-detail', params,
      })).toEqual({ name: 'workshop-outsourcing-tube-detail', params: { id } })
    }
    for (const params of [{ orderId: id }, { id, orderId: id }, { id, url: 'https://evil.test' }] as Record<string, string>[]) {
      expect(() => notificationRoute('TUBE_OUTSOURCING_ORDER_CREATED', {
        ...target, route_name: 'warehouse-outsourcing-tube-detail', params,
      })).toThrow()
    }
    const forgedTube = {
      ...target, route_name: 'workshop-outsourcing-tube-detail', params: { id }, query: { source: 'RAW_PIPE' },
    }
    expect(() => notificationRoute('TUBE_OUTSOURCING_ORDER_CREATED', forgedTube)).toThrow()
  })
  it('更正及损耗使用各自固定目标，删除知悉拒绝任何伪造目标', () => {
    expect(notificationRoute('WORK_REPORT_CORRECTED', { ...target, route_name: 'work-report-day-detail', params: { productionDate: '2026-10-21' } }).name).toBe('work-report-day-detail')
    expect(notificationRoute('OUTSOURCING_LOSS_RECORDED', { ...target, route_name: 'workshop-outsourcing-detail', params: { orderId: id } }).name).toBe('workshop-outsourcing-detail')
    for (const params of [{ id }, { orderId: id }] as Record<string, string>[]) {
      expect(notificationRoute('TUBE_OUTSOURCING_SHORTAGE_RECORDED', { ...target, route_name: 'workshop-outsourcing-tube-detail', params }))
        .toEqual({ name: 'workshop-outsourcing-tube-detail', params: { id } })
    }
    expect(() => notificationRoute('WORK_REPORT_DELETED', target)).toThrow()
  })
  it('检验目标参数允许采购单UUID而非到货UUID；日期路由严格校验', () => {
    expect(notificationRoute('MATERIAL_INSPECTION_CONFIRMED', { ...target, route_name: 'purchase-order-detail', params: { id } }).name).toBe('purchase-order-detail')
    const report = { ...target, route_name: 'work-report-day-detail', params: { productionDate: '2026-10-21' } }
    expect(notificationRoute('WORK_REPORT_SAVED', report).params.productionDate).toBe('2026-10-21')
    expect(() => notificationRoute('WORK_REPORT_SAVED', { ...report, params: { productionDate: '2026-02-30' } })).toThrow()
    expect(notificationRoute('MATERIAL_RECEIPT_RECORDED', { ...target, route_name: 'material-quality-confirmation', params: {} }).params).toEqual({})
  })
})
