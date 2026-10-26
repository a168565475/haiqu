import { describe, expect, it } from 'vitest'
import type { OutsourcingOrderDetail } from '@/types/outsourcing'
import type { TubeOrderDetail } from '@/types/tubeOutsourcing'
import { buildRegularPrintDocument, buildTubePrintDocument } from './outsourcingPrint'

function tube(overrides: Partial<TubeOrderDetail> = {}): TubeOrderDetail {
  return {
    id: 'tube-order', order_number: 'WWJG-REAL', status: 'PROCESSING', task_order_number: 'HT-2026-123',
    product_number: 'CP-1', item_number: 'ITEM-REAL', product_name: '折叠椅', quantity: '1000', planned_quantity: '400',
    color: '红色', specification: '50×50×80', material: '钢', craft_name: '喷塑', category: 'tube', output_unit: '支',
    source_kind: 'RAW_PIPE', created_at: '2026-10-25T18:30:00Z', updated_at: '2026-10-26T04:20:00Z', created_by_name: '制单员工',
    planned_dispatch_date: '2026-10-26', actual_dispatch_date: '2026-10-27', expected_return_date: '2026-10-30', remark: '按原单生产',
    lines: [{ id: 'line-1', factory_name: '加工厂甲', part_name: '前脚管', quantity: '60', pieces_per_product: '2',
      tube_diameter: '22', specification: 'Φ22×0.8', cutting_length_mm: '650', material: 'Q195', raw_color: '本色', spray_color: '黑色亮光' }],
    materials: [{ id: 'material-1', name: '固定螺母', quantity: '12.3400', unit_consumption: '0.5', unit: '个',
      specification: 'M6', material: '碳钢', color: '本色', factory_name: '加工厂乙' }],
    ...overrides,
  } as TubeOrderDetail
}

describe('外发打印数据', () => {
  it('喷塑保留完整真实订单号，区分订单数量、本单数量和冻结单耗', () => {
    const result = buildTubePrintDocument(tube(), 'spray')
    expect(result.title).toBe('HT-2026-123单 嗨趣休闲用品有限公司喷塑计划')
    expect(result.sprayRows[0]).toMatchObject({ orderQuantity: '1000', totalQuantity: '60', unitConsumption: '2', specification: '22', cuttingLength: '650' })
    expect(result.submittedAt).toBe('2026-10-26 02:30:00')
    expect(result.updatedAt).toBe('2026-10-26 12:20:00')
    expect(result.preparedDate).toBe('2026-10-26')
    expect(result.dispatchDate).toBe('2026-10-27')
  })

  it('缺失冻结单耗不按本单数量反算，缺失管径保留完整规格', () => {
    const input = tube()
    delete input.lines[0]!.pieces_per_product
    delete input.lines[0]!.tube_diameter
    const result = buildTubePrintDocument(input, 'spray')
    expect(result.sprayRows[0]).toMatchObject({ unitConsumption: '—', specification: 'Φ22×0.8', totalQuantity: '60' })
  })

  it('管材加工单包含管材和同单五金，保留各自单位与订单量', () => {
    const result = buildTubePrintDocument(tube(), 'processing')
    expect(result.plans[0]).toMatchObject({ plannedQuantity: '400', itemNumber: 'ITEM-REAL', completed: '否' })
    expect(result.materials).toHaveLength(2)
    expect(result.materials[0]).toMatchObject({ name: '前脚管', unit: '支', issueQuantity: '60', unitConsumption: '2', orderQuantity: '1000', material: 'Q195', color: '本色' })
    expect(result.materials[0]!.specification).toBe('Φ22×0.8 × 650mm')
    expect(result.materials[1]).toMatchObject({ name: '固定螺母', unit: '个', issueQuantity: '12.3400', unitConsumption: '0.5', specification: 'M6' })
    expect(result.factoryNames).toBe('加工厂甲、加工厂乙')
  })

  it.each(['CLOSED', 'CANCELLED', 'PENDING_DISPATCH'])('%s 不等同于外发完成', status => {
    expect(buildTubePrintDocument(tube({ status }), 'processing').plans[0]!.completed).toBe('否')
  })

  it('完成单据显示是，裁片沿用套单位', () => {
    const result = buildTubePrintDocument(tube({ status: 'COMPLETED', category: 'cutting', output_unit: '套' }), 'processing')
    expect(result.plans[0]!.completed).toBe('是')
    expect(result.materials[0]!.unit).toBe('套')
    expect(result.materials[0]!.specification).toBe('Φ22×0.8')
  })

  it('普通外发按全部产品和分厂材料打印，不混用排产量与订单量', () => {
    const input = {
      id: 'regular-order', order_number: 'WWJG-9', sales_order_number: 'HT-90', status: 'COMPLETED',
      craft: { name: '车缝' }, factory_names: ['车缝厂'], created_by: { name: '建单人' }, created_at: '2026-10-26T08:00:00+08:00',
      updated_at: '2026-10-26T10:00:00+08:00', delivery_date: '2026-11-01', remark: '',
      products: [
        { id: 'p1', product: { product_name: '椅子', item_number: 'I-1', color_name: '蓝色', specification: '规格一' }, planned_quantity: 100, order_quantity: 500,
          processing_items: [{ id: 'process-1', allocations: [
            { id: 'allocation-1', materials: [{ id: 'm1', name: '面料', specification: '300D', color: '蓝色', material: '涤纶', unit: '米', planned_issue_quantity: '40', unit_consumption: '0.7' }] },
            { id: 'allocation-2', materials: [{ id: 'm2', name: '面料', specification: '300D', color: '蓝色', material: '涤纶', unit: '米', planned_issue_quantity: '20' }] },
          ] }],
        },
        { id: 'p2', product: { product_name: '桌子', item_number: 'I-2' }, planned_quantity: 0, order_quantity: 20, processing_items: [] },
      ],
    } as unknown as OutsourcingOrderDetail
    const result = buildRegularPrintDocument(input)
    expect(result.plans).toHaveLength(2)
    expect(result.plans[0]).toMatchObject({ orderNumber: 'HT-90', itemNumber: 'I-1', plannedQuantity: '100', specification: '规格一' })
    expect(result.plans[1]!.plannedQuantity).toBe('0')
    expect(result.materials.map(row => [row.orderQuantity, row.issueQuantity, row.unitConsumption])).toEqual([['500', '40', '0.7'], ['500', '20', '—']])
    expect(result.materials[0]!.material).toBe('涤纶')
  })

  it('空明细和旧单缺字段仍可阅读，日期不可解析时显示缺值', () => {
    const result = buildTubePrintDocument(tube({ lines: [], materials: [], planned_quantity: undefined, updated_at: undefined, actual_dispatch_date: null, created_at: 'invalid' }), 'processing')
    expect(result.materials).toEqual([])
    expect(result.factoryNames).toBe('—')
    expect(result.submittedAt).toBe('—')
    expect(result.updatedAt).toBe('—')
    expect(result.plans[0]!.plannedQuantity).toBe('—')
    expect(result.dispatchDate).toBe('2026-10-26')
  })
})
