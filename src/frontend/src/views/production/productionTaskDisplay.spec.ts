import { describe, expect, it } from 'vitest'
import type { ProductionTaskProduct } from '@/types/productionTask'
import { productLabels, productSpecifications, quantityWithUnits, localAmountTotal } from './productionTaskDisplay'
const product = (overrides: Partial<ProductionTaskProduct>) => ({ product_id: null, product_name: '产品', quantity: 1, unit_id: 'piece', unit_name: '件', local_total_amount: '0.10', ...overrides }) as ProductionTaskProduct

describe('生产任务显示口径', () => {
  it('两个未建档产品分别显示，有货号才附带货号', () => {
    expect(productLabels([product({ product_name: '甲' }), product({ product_name: '乙', item_number: 'B-1' })])).toEqual(['甲', '乙 · B-1'])
  })
  it('按真实单位分组，不能把箱和件相加', () => {
    expect(quantityWithUnits([product({ quantity: 2 }), product({ quantity: 3 }), product({ unit_id: 'box', unit_name: '箱', quantity: 1 })])).toBe('5 件 / 1 箱')
    expect(quantityWithUnits([])).toBe('—')
  })
  it('人民币只累加本币行金额并保留分位，不混用原币金额', () => {
    expect(localAmountTotal([product({ total_amount: '999.00' }), product({ local_total_amount: '0.20' })])).toBe('0.3000')
    expect(localAmountTotal([product({ local_total_amount: '0.1234' }), product({ local_total_amount: '0.0001' })])).toBe('0.1235')
    expect(localAmountTotal([product({ local_total_amount: 'bad' })])).toBe('—')
  })
  it('规格提示包含每个产品的规格颜色材质', () => {
    expect(productSpecifications([product({ customer_product_name: '甲', customer_specification: '大号', customer_color: '红', material: '棉' })])).toBe('甲：规格 大号；颜色 红；材质 棉')
  })
})
