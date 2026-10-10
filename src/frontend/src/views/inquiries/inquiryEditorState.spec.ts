import { describe, expect, it } from 'vitest'
import type { InquiryItem } from '@/types/inquiry'
import { blankProduct, decimalUnits, productAmount, quantitySummary, validateAttachment, validateProducts } from './inquiryEditorState'
const item = (overrides: Partial<InquiryItem> = {}): InquiryItem => ({ product_description: '露营床', specification: '', color: '', material: '', quantity: '2000', unit_code: 'PCS', target_unit_price: '100', target_currency_code: 'USD', expected_date: null, product_match_status: 'PENDING', notes: '', ...overrides })
describe('新建询盘边界', () => {
  it('精确合计产品金额及不同单位的数量', () => {
    expect(productAmount([item()]).totals).toEqual([{ currency_code: 'USD', amount: '200000.00000000' }])
    expect(productAmount([item({ quantity: '99999999999999.9999', target_unit_price: '99999999999999.9999' })]).totals[0]?.amount).toBe('9999999999999999980000000000.00000001')
    expect(quantitySummary([item(), item({ quantity: '0.0001', unit_code: 'SET' })])).toBe('2,000 PCS / 0.0001 SET')
  })
  it('零价有效，缺价不作为零，币种分别合计', () => {
    expect(productAmount([item({ target_unit_price: '0' })]).missing_price_count).toBe(0)
    expect(productAmount([item({ target_unit_price: null })]).missing_price_count).toBe(1)
    expect(productAmount([item(), item({ target_currency_code: 'CNY' })]).totals).toHaveLength(2)
  })
  it('拒绝非数字、负数、超出字段精度和零数量', () => {
    for (const invalid of ['NaN', '1e9', '-1', '100000000000000', '0.00001']) expect(decimalUnits(invalid)).toBeNull()
    expect(validateProducts([item({ quantity: '0' })])).toContain('数量')
    expect(validateProducts([item({ target_currency_code: '' })])).toContain('币种')
    expect(validateProducts([item({ target_unit_price: '0' })])).toBe('')
    expect(decimalUnits('0', 2, 16)).toBe(0n)
  })
  it('草稿可忽略初始空行，但不能丢失部分填写内容', () => {
    const blank = item({ product_description: '', quantity: '1', target_unit_price: null, target_currency_code: '' })
    expect(blankProduct(blank)).toBe(true)
    expect(blankProduct({ ...blank, specification: '已填写规格' })).toBe(false)
    expect(blankProduct({ ...blank, color: '黑色' })).toBe(false)
    expect(blankProduct({ ...blank, material: '铝合金' })).toBe(false)
    expect(blankProduct({ ...blank, id: 'existing' })).toBe(false)
    expect(validateProducts([])).toBe('')
  })
  it('附件格式、空文件和大小限制', () => {
    expect(validateAttachment({ name: '规格.XLSX', size: 20 })).toBe('')
    expect(validateAttachment({ name: 'a.exe', size: 20 })).not.toBe('')
    expect(validateAttachment({ name: 'a.pdf', size: 0 })).not.toBe('')
    expect(validateAttachment({ name: 'a.pdf', size: 10 * 1024 * 1024 + 1 })).not.toBe('')
  })
})
