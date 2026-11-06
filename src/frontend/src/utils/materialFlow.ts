import type { BomLine, BomLineInput, PurchaseAllowanceRule } from '@/types/bom'

type SourcePipePurchase = Pick<BomLineInput, 'source_purchase_allowance_percent' | 'source_raw_bar_length_m'> & {
  purchase_allowance_mode?: string
  purchase_allowance_rule?: string
}
export type SavedPipePlanBasis = Pick<Partial<BomLine>, 'cutting_length_mm' | 'pieces_per_product' | 'pieces_per_bar' | 'raw_values'> & SourcePipePurchase

export const purchaseAllowanceOptions: Array<{ value: PurchaseAllowanceRule; label: string }> = [
  { value: 'NONE', label: '不加余量' },
  { value: 'PLUS_5', label: '+5 根' },
  { value: 'PLUS_8', label: '+8 根' },
  { value: 'PERCENT_0_5', label: '+0.5%' },
  { value: 'PERCENT_1', label: '+1%' },
]

export function defaultPurchaseAllowanceRule(baseRoots: bigint): PurchaseAllowanceRule {
  return baseRoots <= 500n ? 'PLUS_5' : baseRoots <= 1000n ? 'PLUS_8' : 'PERCENT_1'
}

interface PipePlan {
  total_consumption: string
  branch_count: string
  tube_cut_length_m: string
  suggested_purchase_meters: string
  base_purchase_bar_count?: string
  purchase_allowance_bar_count?: string
  purchase_allowance_rule?: PurchaseAllowanceRule
}

function scaledDecimal(value: string, places: number) {
  const text = value.trim()
  if (!/^\d+(?:\.\d+)?$/.test(text) || text.length > 100) return null
  const [whole, fraction = ''] = text.split('.')
  if (/[^0]/.test(fraction.slice(places))) return null
  return BigInt(whole!) * 10n ** BigInt(places) + BigInt(fraction.slice(0, places).padEnd(places, '0'))
}

/** 与后端一致的整数换算；预览不使用浮点数舍入。 */
export function pipePlan(length: string, consumption: string, cuts: string, quantity: string, calculationVersion: 2 | 3 | 4 = 3, source: SourcePipePurchase = {}): PipePlan | null {
  const values = [length, consumption, cuts, quantity].map((value) => value.trim())
  if (values.some((value) => !/^\d+(?:\.0+)?$/.test(value) || value.length > 30)) return null
  const [l, u, k, q] = values.map((value) => BigInt(value.split('.')[0]!)) as [bigint, bigint, bigint, bigint]
  if ([l, u, k, q].some((value) => value <= 0n || value >= 100000000000000n)) return null
  const demand = q * u
  const baseRoots = (demand + k - 1n) / k
  const usesPurchaseAllowance = calculationVersion === 4 || Boolean(source.purchase_allowance_mode)
  let allowanceRule: PurchaseAllowanceRule | undefined
  let allowanceRoots = 0n
  if (usesPurchaseAllowance) {
    if (source.purchase_allowance_mode && !['AUTO', 'MANUAL'].includes(source.purchase_allowance_mode)) return null
    if (source.purchase_allowance_mode === 'MANUAL') {
      if (!purchaseAllowanceOptions.some(option => option.value === source.purchase_allowance_rule)) return null
      allowanceRule = source.purchase_allowance_rule as PurchaseAllowanceRule
    } else allowanceRule = defaultPurchaseAllowanceRule(baseRoots)
    allowanceRoots = allowanceRule === 'PLUS_5' ? 5n : allowanceRule === 'PLUS_8' ? 8n
      : allowanceRule === 'PERCENT_0_5' ? (baseRoots + 199n) / 200n
      : allowanceRule === 'PERCENT_1' ? (baseRoots + 99n) / 100n : 0n
  }
  let percent = calculationVersion === 2 ? 10000n : 0n
  if (!usesPurchaseAllowance && source.source_purchase_allowance_percent) {
    const supplied = scaledDecimal(source.source_purchase_allowance_percent, 4)
    if (supplied === null || supplied > 1000000n) return null
    percent = supplied
  }
  const factor = 1000000n + percent
  const roots = usesPurchaseAllowance ? baseRoots + allowanceRoots : (demand * factor + k * 1000000n - 1n) / (k * 1000000n)
  let centimeters = (l * k + 50n + 9n) / 10n
  if (source.source_raw_bar_length_m) {
    const supplied = scaledDecimal(source.source_raw_bar_length_m, 2)
    if (supplied === null || supplied <= 0n || supplied * 10n < l * k) return null
    centimeters = supplied
  }
  const total = centimeters * roots
  if (demand >= 100000000000000n || roots * k >= 100000000000000n || centimeters >= 1000000000000000000n || total >= 10000000000000000000000n) return null
  const meters = (value: bigint) => `${value / 100n}.${String(value % 100n).padStart(2, '0')}`
  return { total_consumption: String(demand), branch_count: String(roots), tube_cut_length_m: meters(centimeters),
    suggested_purchase_meters: meters(total),
    ...(usesPurchaseAllowance ? { base_purchase_bar_count: String(baseRoots), purchase_allowance_bar_count: String(allowanceRoots), purchase_allowance_rule: allowanceRule } : {}) }
}

export function pipePlanForBomLine(
  line: Pick<BomLineInput, 'length_value' | 'unit_consumption' | 'tube_cut_piece_count'> & SourcePipePurchase,
  quantity: string,
  savedLine?: SavedPipePlanBasis,
) {
  const source = {
    source_purchase_allowance_percent: line.source_purchase_allowance_percent ?? savedLine?.source_purchase_allowance_percent ?? savedLine?.raw_values?.source_purchase_allowance_percent,
    source_raw_bar_length_m: line.source_raw_bar_length_m ?? savedLine?.source_raw_bar_length_m ?? savedLine?.raw_values?.source_raw_bar_length_m,
    purchase_allowance_rule: line.purchase_allowance_rule ?? savedLine?.purchase_allowance_rule ?? savedLine?.raw_values?.purchase_allowance_rule,
    purchase_allowance_mode: line.purchase_allowance_mode ?? savedLine?.purchase_allowance_mode ?? savedLine?.raw_values?.purchase_allowance_mode,
  }
  const version = Number(savedLine?.raw_values?.pipe_plan_version ?? 2)
  const plan = pipePlan(line.length_value || '', line.unit_consumption || '', line.tube_cut_piece_count || '', quantity, version === 4 ? 4 : 3, source)
  if (!plan || !savedLine) return plan
  if (source.purchase_allowance_mode || version === 4) return plan
  const unchanged = savedLine.cutting_length_mm != null && savedLine.pieces_per_product != null && savedLine.pieces_per_bar != null
    && Number(line.length_value) === savedLine.cutting_length_mm
    && Number(line.unit_consumption) === savedLine.pieces_per_product
    && Number(line.tube_cut_piece_count) === savedLine.pieces_per_bar
  if (!unchanged) return plan
  // 基准只读接口数据，不随编辑行提交；原参数不变的历史 BOM 继续按原版本显示。
  if (version !== 2 && version !== 3) return null
  return version === 3 ? plan : pipePlan(line.length_value, line.unit_consumption, line.tube_cut_piece_count, quantity, 2, source)
}
