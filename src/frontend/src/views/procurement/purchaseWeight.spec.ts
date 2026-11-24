import { describe, expect, it } from 'vitest'
import { hardwareReferenceCount, isHardwareWeightLine, isWeightPurchaseLine } from './purchaseWeight'

describe('采购重量物料识别', () => {
  it('识别管材 KG 口径', () => {
    expect(isWeightPurchaseLine({ section_type: 'PROFILE', source_unit_text: 'KG' })).toBe(true)
  })

  it('识别五金件重量快照并保持普通 KG 物料为数量口径', () => {
    expect(isHardwareWeightLine({
      section_type: 'ACCESSORY',
      section_title: '五金件',
      source_unit_text: 'KG',
      calculation_snapshot: { measurement_kind: 'HARDWARE_WEIGHT', hardware_weight_mode: 'AUTO', hardware_suggested_weight_kg: '0.04752' },
    })).toBe(true)
    expect(isWeightPurchaseLine({
      section_type: 'ACCESSORY',
      section_title: '五金件',
      source_unit_text: 'KG',
      calculation_snapshot: { measurement_kind: 'HARDWARE_WEIGHT', hardware_weight_mode: 'MANUAL' },
    })).toBe(true)
    expect(isHardwareWeightLine({ source_unit_text: 'KG', measurement_kind: 'HARDWARE_WEIGHT' })).toBe(true)
    expect(isWeightPurchaseLine({ section_type: 'ACCESSORY', source_unit_text: 'KG' })).toBe(false)
  })

  it('不把个单位或普通辅料误识别为重量采购', () => {
    expect(isWeightPurchaseLine({ section_type: 'ACCESSORY', section_title: '五金件', source_unit_text: '个' })).toBe(false)
    expect(isWeightPurchaseLine({ section_type: 'FABRIC', section_title: '辅料类', source_unit_text: 'KG' })).toBe(false)
  })

  it('不凭五金标题或未冻结的模式误判历史KG物料', () => {
    expect(isHardwareWeightLine({ section_title: '五金件', source_unit_text: 'KG' })).toBe(false)
    expect(isHardwareWeightLine({ source_unit_text: 'KG', calculation_snapshot: { hardware_weight_mode: 'AUTO' } })).toBe(false)
  })

  it('参考件数精确向下取整，保留零且拒绝无效单重', () => {
    expect(hardwareReferenceCount('0.3', '0.1')).toBe(3n)
    expect(hardwareReferenceCount('3.96000000', '0.00396000')).toBe(1000n)
    expect(hardwareReferenceCount('3.95999999', '0.00396000')).toBe(999n)
    expect(hardwareReferenceCount('0', '0.00396000')).toBe(0n)
    expect(hardwareReferenceCount('3.96', '0')).toBeNull()
    expect(hardwareReferenceCount('1.234567891', '0.00396000')).toBeNull()
  })
})

