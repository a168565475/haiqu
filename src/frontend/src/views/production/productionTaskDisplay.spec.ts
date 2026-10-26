import { describe, expect, it } from 'vitest'
import type { ProductionTaskProduct } from '@/types/productionTask'
import { productLabels, productSpecifications, quantityWithUnits, localAmountTotal, isTaskReadyForScheduling } from './productionTaskDisplay'
const product = (overrides: Partial<ProductionTaskProduct>) => ({ product_id: null, product_name: '产品', quantity: 1, unit_id: 'piece', unit_name: '件', local_total_amount: '0.10', ...overrides }) as ProductionTaskProduct

describe('生产任务显示口径', () => {
  it('只有已接单、全部 BOM 已确认且已完成采购时才允许进入排产', () => {
    const ready = { status: 'READY', bom_status: 'VERIFIED', purchase_status: 'ORDER_COMPLETED' } as const
    expect(isTaskReadyForScheduling(ready)).toBe(true)
    for (const bom_status of ['NOT_CREATED', 'PARTIAL', 'PENDING_CONFIRMATION', undefined] as const) {
      expect(isTaskReadyForScheduling({ ...ready, bom_status })).toBe(false)
    }
    for (const purchase_status of ['NOT_STARTED', 'REQUEST_FULLY_ALLOCATED', 'ORDER_DRAFT', 'ORDER_SUBMITTED', 'ORDER_PURCHASING', undefined] as const) {
      expect(isTaskReadyForScheduling({ ...ready, purchase_status })).toBe(false)
    }
    expect(isTaskReadyForScheduling({ ...ready, status: 'IN_PRODUCTION' })).toBe(false)
    expect(isTaskReadyForScheduling(null)).toBe(false)
  })
  it('两个未建档产品分别显示，有货号才附带货号', () => {
    expect(productLabels([product({ product_name: '甲' }), product({ product_name: '乙', item_number: 'B-1' })])).toEqual(['甲', '乙 · B-1'])
  })
  it('按真实单位分组，不能把箱和件相加', () => {
    expect(quantityWithUnits([product({ quantity: 2 }), product({ quantity: 3 }), product({ unit_id: 'box', unit_name: '箱', quantity: 1 })])).toBe('5 件 / 1 箱')
    expect(quantityWithUnits([])).toBe('—')
  })
  it('人民币只累加本币行金额，显示去除尾零，不混用原币金额', () => {
    expect(localAmountTotal([product({ total_amount: '999.00' }), product({ local_total_amount: '0.20' })])).toBe('0.3')
    expect(localAmountTotal([product({ local_total_amount: '0.1234' }), product({ local_total_amount: '0.0001' })])).toBe('0.1235')
    expect(localAmountTotal([product({ local_total_amount: 'bad' })])).toBe('—')
  })
  it.each([
    { name: '整数省略全零小数', amounts: ['1200.0000', '34.0000'], expected: '1,234' },
    { name: '零金额不带小数或负号', amounts: ['0.0000', '-0.0000'], expected: '0' },
    { name: '负整数省略全零小数', amounts: ['-1234.0000'], expected: '-1,234' },
    { name: '正负小数精确抵消', amounts: ['1250.4321', '-1250.4321'], expected: '0' },
    { name: '小数相加进位后显示整数', amounts: ['0.9999', '0.0001'], expected: '1' },
    { name: '负数的小数去除尾零', amounts: ['-12.3400'], expected: '-12.34' },
    { name: '大整数进位不丢精度', amounts: ['9007199254740993.9999', '0.0001'], expected: '9,007,199,254,740,994' },
    { name: '大整数的非零小数精确保留四位', amounts: ['9007199254740993.1234', '0.0001'], expected: '9,007,199,254,740,993.1235' },
  ])('金额格式：$name', ({ amounts, expected }) => {
    expect(localAmountTotal(amounts.map(local_total_amount => product({ local_total_amount })))).toBe(expected)
  })
  it('规格提示包含每个产品的规格颜色材质', () => {
    expect(productSpecifications([product({ customer_product_name: '甲', customer_specification: '大号', customer_color: '红', material: '棉' })])).toBe('甲：规格 大号；颜色 红；材质 棉')
  })
})
