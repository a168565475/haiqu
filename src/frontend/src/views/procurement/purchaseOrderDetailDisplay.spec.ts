import { describe, expect, it } from 'vitest'
import { formatMoney, formatQuantity, formatUnitPrice, purchaseQuantityText, quantityTotal } from './purchaseOrderDetailDisplay'

describe('采购详情数量口径', () => {
  it('管材直接显示快照根数，缺根数时不把米数冒充根数', () => {
    expect(purchaseQuantityText('2706.8000', '米', '3.35', 808)).toBe('808 根')
    expect(purchaseQuantityText('0.0000', '米', '3.35', 0)).toBe('0 根')
    expect(purchaseQuantityText('2706.8000', '米', '3.35', null)).toBe('根数未记录')
    expect(purchaseQuantityText('10.5000', '米', null, null)).toBe('10.5 米')
  })
  it('小数合计保持精度，不同单位不相加', () => {
    expect(quantityTotal([{ source_unit_text: '米' }, { source_unit_text: '米' }], ['0.1', '0.2'])).toBe('0.3 米')
    expect(quantityTotal([{ source_unit_text: '米' }, { source_unit_text: '支' }], ['2', '3'])).toBe('—')
    expect(quantityTotal([{ source_unit_text: '米' }], [null])).toBe('—')
  })
  it('缺少或异常数据不伪装成零，金额四舍五入', () => {
    expect(formatQuantity(null)).toBe('—')
    expect(formatQuantity('bad')).toBe('—')
    expect(formatQuantity('0.0000')).toBe('0')
    expect(formatQuantity('90071992547409.2500')).toBe('90,071,992,547,409.25')
    expect(formatMoney('1.0050')).toBe('1.01')
    expect(formatMoney('5386.0000')).toBe('5,386.00')
    expect(formatUnitPrice('0.0040')).toBe('0.004')
    expect(formatUnitPrice('2.5000')).toBe('2.50')
  })
})
