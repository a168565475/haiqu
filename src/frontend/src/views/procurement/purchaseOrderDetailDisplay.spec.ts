import { describe, expect, it } from 'vitest'
import { formatMoney, formatQuantity, formatUnitPrice, quantityTotal } from './purchaseOrderDetailDisplay'

describe('采购详情数量口径', () => {
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
