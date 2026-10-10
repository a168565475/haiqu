import { describe, expect, it } from 'vitest'
import { pipePlan } from './materialFlow'

describe('管材 BOM 换算', () => {
  it('每根长度及含余量采购根数都向上取整', () => {
    expect(pipePlan('500', '2', '6', '1000')).toEqual({ total_consumption: '2000', branch_count: '337', tube_cut_length_m: '3.05', suggested_purchase_meters: '1027.85' })
    expect(pipePlan('501', '2', '6', '1000')?.tube_cut_length_m).toBe('3.06')
  })
  it('小数毫米、半支、负数、空值和越界不产生误导性预览', () => {
    for (const value of ['', '0', '-1', 'NaN', 'Infinity', '1.1', '999999999999999']) expect(pipePlan(value, '2', '6', '1000')).toBeNull()
    expect(pipePlan('500', '2', '6.5', '1000')).toBeNull()
    expect(pipePlan('500', '2', '6', '1000.0000')?.branch_count).toBe('337')
  })
})
