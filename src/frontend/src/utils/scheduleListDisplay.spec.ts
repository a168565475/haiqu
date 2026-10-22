import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ScheduleProduct } from '@/types/productionScheduling'
import type { ScheduleProductStageProgress } from '@/types/workshopReporting'
import { scheduleProductSummary, scheduleStageRisk } from './scheduleListDisplay'

function product(overrides: Partial<ScheduleProduct> = {}): ScheduleProduct {
  return { id: 'p1', product_line_id: 'line-1', line_number: 1, planned_quantity: 100, source_quantity: 100,
    unit_id: 'unit-set', unit_name: '套', image_file_id: null, product: { product_name: '导演椅' },
    material_inbound_date: '2026-10-22', metal_return_date: '2026-10-24', sewing_return_date: '2026-10-28',
    finished_inbound_date: '2026-10-31', crafts: [], ...overrides }
}
function stage(overrides: Partial<ScheduleProductStageProgress> = {}): ScheduleProductStageProgress {
  return { schedule_product_id: 'p1', status: 'READY', percentage: 0, planned_date: '2026-10-31', ...overrides }
}

afterEach(() => { vi.useRealTimers() })

describe('排产产品汇总', () => {
  it('空产品不虚构数量，单产品保留真实单位', () => {
    expect(scheduleProductSummary([])).toBe('0 项产品')
    expect(scheduleProductSummary([product({ planned_quantity: 1200, unit_id: 'unit-box', unit_name: '箱' })])).toBe('1 项产品 · 共 1,200 箱')
  })
  it('按产品行计项，同单位数量合计，颜色变体不去重', () => {
    const items = [product({ product: { product_name: '导演椅', color_name: '酒红色' } }),
      product({ id: 'p2', product_line_id: 'line-2', planned_quantity: 50, product: { product_name: '导演椅', color_name: '蓝色' } })]
    expect(scheduleProductSummary(items)).toBe('2 项产品 · 共 150 套')
  })
  it('多单位分别汇总，不把箱和套相加成套', () => {
    expect(scheduleProductSummary([product(), product({ id: 'p2', planned_quantity: 20, unit_id: 'unit-box', unit_name: '箱' }),
      product({ id: 'p3', planned_quantity: 5 })])).toBe('3 项产品 · 共 105 套、20 箱')
  })
  it.each([Number.NaN, Number.POSITIVE_INFINITY, -1])('数量 %s 无效时不显示部分合计', quantity => {
    expect(scheduleProductSummary([product(), product({ id: 'p2', planned_quantity: quantity })])).toBe('2 项产品 · 数量待补全')
  })
  it('单位缺失时不猜测为套', () => {
    expect(scheduleProductSummary([product({ unit_name: '' })])).toBe('1 项产品 · 数量待补全')
  })
})

describe('工序计划日期预警', () => {
  it.each([
    ['缺少记录', undefined],
    ['进度为空', stage({ percentage: null })],
    ['进度不是有效数字', stage({ percentage: Number.NaN })],
    ['未配置工序', stage({ status: 'NOT_CONFIGURED', percentage: 0 })],
    ['没有适用工序', stage({ status: 'NOT_APPLICABLE', percentage: null })],
  ] as const)('%s 保持未知，不按零进度或正常绿色处理', (_name, metric) => {
    expect(scheduleStageRisk(metric, '2026-10-22').level).toBe('unknown')
  })
  it('真实零进度且离计划日期较远时可以正常显示', () => {
    expect(scheduleStageRisk(stage(), '2026-10-22')).toEqual({ level: 'normal', description: '距计划日期 9 天 · 当前 0%' })
  })
  it.each([
    ['2026-10-30', 0, 'normal'],
    ['2026-10-29', 39.99, 'attention'],
    ['2026-10-29', 40, 'normal'],
    ['2026-10-26', 0, 'attention'],
    ['2026-10-25', 69.99, 'slow'],
    ['2026-10-25', 70, 'normal'],
    ['2026-10-24', 39.99, 'slow'],
    ['2026-10-23', 89.99, 'urgent'],
    ['2026-10-23', 90, 'normal'],
    ['2026-10-22', 89.99, 'urgent'],
    ['2026-10-22', 90, 'normal'],
    ['2026-10-21', 99, 'urgent'],
  ] as const)('计划 %s、进度 %s%% 对应 %s，临近日期优先于较轻预警', (plannedDate, percentage, expected) => {
    expect(scheduleStageRisk(stage({ planned_date: plannedDate, percentage }), '2026-10-22').level).toBe(expected)
  })
  it('采用服务端业务日期跨年计算，不取浏览器当前时间', () => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date('2030-07-01T23:59:59Z'))
    expect(scheduleStageRisk(stage({ planned_date: '2027-01-01', percentage: 80 }), '2026-12-31'))
      .toEqual({ level: 'urgent', description: '距计划日期 1 天 · 当前 80%' })
  })
  it('按日历自然日识别闰年日期和逾期天数', () => {
    expect(scheduleStageRisk(stage({ planned_date: '2028-03-01', percentage: 80 }), '2028-02-28').description)
      .toBe('距计划日期 2 天 · 当前 80%')
    expect(scheduleStageRisk(stage({ planned_date: '2028-02-29', percentage: 99 }), '2028-03-01'))
      .toEqual({ level: 'urgent', description: '已逾期 1 天 · 当前 99%' })
  })
  it.each([null, '', '2026-02-30', '2026-02-29', '2026-13-01', '2026-10-22T00:00:00Z'])('计划日期 %s 缺失或无效时不能假绿', plannedDate => {
    expect(scheduleStageRisk(stage({ planned_date: plannedDate }), '2026-10-22').level).toBe('unknown')
  })
  it.each([undefined, '', '2026-02-30'])('服务端业务日期 %s 不可用时不回退浏览器日期', asOfDate => {
    expect(scheduleStageRisk(stage(), asOfDate).level).toBe('unknown')
  })
  it.each(['2026-10-01', null])('已完成保持绿色，不因计划日期 %s 变为逾期预警', plannedDate => {
    expect(scheduleStageRisk(stage({ planned_date: plannedDate, percentage: 100 }), '2026-10-22'))
      .toEqual({ level: 'normal', description: '已完成' })
  })
})
