/**
 * 采购端重量口径。
 *
 * 管材重量沿用 PROFILE + KG；五金件重量由 BOM 采购快照标记，不能仅凭
 * KG 判断，否则会把普通按 KG 的物料误当成五金重量采购。
 */
export interface PurchaseWeightSourceLike {
  section_type?: string | null
  section_type_snapshot?: string | null
  section_title?: string | null
  section_title_snapshot?: string | null
  source_unit_text?: string | null
  measurement_kind?: string | null
  suggested_purchase_weight_kg?: string | null
  actual_purchase_weight_kg?: string | null
  calculation_snapshot?: Record<string, unknown> | null
}

export function isKilogramUnit(value: unknown): boolean {
  return ['KG', '千克', '公斤'].includes(String(value || '').trim().toUpperCase())
}

export function isHardwareWeightLine(line: PurchaseWeightSourceLike): boolean {
  if (!isKilogramUnit(line.source_unit_text)) return false
  const section = line.section_type || line.section_type_snapshot
  if (section === 'PROFILE') return false
  if (line.measurement_kind === 'HARDWARE_WEIGHT') return true
  return line.calculation_snapshot?.measurement_kind === 'HARDWARE_WEIGHT'
}

/** 参考件数使用定点整数除法向下取整，不参与 KG 计价。 */
export function hardwareReferenceCount(weight: unknown, unitWeight: unknown): bigint | null {
  const scaled = (value: unknown): bigint | null => {
    const text = String(value ?? '').trim()
    if (!/^\d{1,18}(\.\d{1,8})?$/.test(text)) return null
    const [whole = '0', fraction = ''] = text.split('.')
    return BigInt(whole) * 100000000n + BigInt(fraction.padEnd(8, '0'))
  }
  const kg = scaled(weight)
  const singleWeight = scaled(unitWeight)
  if (kg === null || singleWeight === null || singleWeight <= 0n) return null
  return kg / singleWeight
}

export function isWeightPurchaseLine(line: PurchaseWeightSourceLike): boolean {
  if (!isKilogramUnit(line.source_unit_text)) return false
  const section = line.section_type || line.section_type_snapshot
  return section === 'PROFILE' || isHardwareWeightLine(line)
}

