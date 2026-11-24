/** 根米预览用整数运算；最终数量仍由后端重新计算。 */
export function pipeMeters(roots: string | number | null | undefined, length: string | null | undefined): string {
  const count = String(roots ?? '').trim()
  if (!/^\d{1,14}$/.test(count) || !/^\d{1,14}(?:\.\d{1,3})?$/.test(length || '')) return ''
  const [whole = '0', fraction = ''] = length!.split('.')
  const total = BigInt(count) * (BigInt(whole) * 1000n + BigInt(fraction.padEnd(3, '0')))
  return `${total / 1000n}.${String(total % 1000n).padStart(3, '0')}`.replace(/0$/, '')
}

export function pipeRootError(roots: unknown): string {
  if (!/^\d{1,14}$/.test(String(roots ?? '')) || BigInt(String(roots)) <= 0n) return '管材根数必须为正整数。'
  return ''
}

interface WeighedPipeReceipt {
  measurement_kind?: string
  purchase_order_line_id: string | null
  received_weight_kg?: string | null
  received_bar_count?: number | null
  bar_weight_kg?: string | null
  production_task_number_snapshot?: string
  calculation_snapshot?: Record<string, unknown>
}

export function weighedProductionPipe<T extends WeighedPipeReceipt>(
  line: T, productionTaskNumber = line.production_task_number_snapshot,
): line is T & { received_weight_kg: string; received_bar_count: number } {
  const unitWeight = line.bar_weight_kg ?? ''
  return line.measurement_kind === 'PIPE' && !!line.purchase_order_line_id && line.received_weight_kg != null
    && (line.received_bar_count ?? 0) > 0 && /^\d{1,14}(?:\.\d{1,4})?$/.test(unitWeight) && Number(unitWeight) > 0
    && (!!productionTaskNumber || line.calculation_snapshot?.receipt_root_rounding === 'FLOOR')
}

/** 米制采购按冻结原长整根收退，非整数倍不做近似换算。 */
export function pipeRootsFromMeters(meters: string, length: string | null | undefined): string {
  if (!/^\d{1,14}(?:\.\d{1,4})?$/.test(meters) || !/^\d{1,14}(?:\.\d{1,3})?$/.test(length || '')) return ''
  const scaled = (value: string) => {
    const [whole = '0', fraction = ''] = value.split('.')
    return BigInt(whole) * 10000n + BigInt(fraction.padEnd(4, '0'))
  }
  const amount = scaled(meters), perRoot = scaled(length!)
  if (perRoot <= 0n || amount % perRoot !== 0n) return ''
  const roots = amount / perRoot
  return roots > 99999999999999n ? '' : String(roots)
}

/** 根据标准单重向上估算，仓库可另外填写实收/实退根数。 */
export function pipeRootsFromWeight(weight: string, unitWeight: string | null | undefined): string {
  const scaled = (value: string) => {
    if (!/^\d{1,14}(?:\.\d{1,4})?$/.test(value)) return null
    const [whole = '0', fraction = ''] = value.split('.')
    return BigInt(whole) * 10000n + BigInt(fraction.padEnd(4, '0'))
  }
  const amount = scaled(weight), perRoot = scaled(unitWeight || '')
  if (amount === null || perRoot === null || perRoot <= 0n) return ''
  const roots = (amount + perRoot - 1n) / perRoot
  return roots > 99999999999999n ? '' : String(roots)
}

/** 打样缺料米数先向上取整为整根，再按采购填写的单根标准重量预算 KG。 */
export function samplePipeSuggestedWeight(meters: string | null | undefined, length: string | null | undefined, weight: string | null | undefined): string {
  if (!/^\d{1,14}(?:\.\d{1,4})?$/.test(meters || '') || !/^\d{1,14}(?:\.\d{1,3})?$/.test(length || '')
    || !/^\d{1,14}(?:\.\d{1,4})?$/.test(weight || '')) return ''
  const scaled = (value: string) => {
    const [whole = '0', fraction = ''] = value.split('.')
    return BigInt(whole) * 10000n + BigInt(fraction.padEnd(4, '0'))
  }
  const required = scaled(meters!), perLength = scaled(length!), perWeight = scaled(weight!)
  if (required <= 0n || perLength <= 0n || perWeight <= 0n) return ''
  const total = ((required + perLength - 1n) / perLength) * perWeight
  const fraction = (total % 10000n).toString().padStart(4, '0').replace(/0+$/, '')
  return `${total / 10000n}${fraction ? `.${fraction}` : ''}`
}
