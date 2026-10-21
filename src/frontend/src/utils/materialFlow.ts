import type { BomLine, BomLineInput } from '@/types/bom'

export type SavedPipePlanBasis = Pick<Partial<BomLine>, 'cutting_length_mm' | 'pieces_per_product' | 'pieces_per_bar' | 'raw_values'>

/** 与后端一致的整数换算；预览不使用浮点数舍入。 */
export function pipePlan(length: string, consumption: string, cuts: string, quantity: string, calculationVersion: 2 | 3 = 3) {
  const values = [length, consumption, cuts, quantity].map((value) => value.trim())
  if (values.some((value) => !/^\d+(?:\.0+)?$/.test(value) || value.length > 30)) return null
  const [l, u, k, q] = values.map((value) => BigInt(value.split('.')[0]!)) as [bigint, bigint, bigint, bigint]
  if ([l, u, k, q].some((value) => value <= 0n || value >= 100000000000000n)) return null
  const demand = q * u
  const factor = calculationVersion === 2 ? 101n : 100n
  const roots = (demand * factor + k * 100n - 1n) / (k * 100n)
  const centimeters = (l * k + 50n + 9n) / 10n
  const total = centimeters * roots
  if (demand >= 100000000000000n || roots * k >= 100000000000000n || centimeters >= 1000000000000000000n || total >= 10000000000000000000000n) return null
  const meters = (value: bigint) => `${value / 100n}.${String(value % 100n).padStart(2, '0')}`
  return { total_consumption: String(demand), branch_count: String(roots), tube_cut_length_m: meters(centimeters),
    suggested_purchase_meters: meters(total) }
}

export function pipePlanForBomLine(
  line: Pick<BomLineInput, 'length_value' | 'unit_consumption' | 'tube_cut_piece_count'>,
  quantity: string,
  savedLine?: SavedPipePlanBasis,
) {
  const plan = pipePlan(line.length_value || '', line.unit_consumption || '', line.tube_cut_piece_count || '', quantity)
  if (!plan || !savedLine) return plan
  const unchanged = savedLine.cutting_length_mm != null && savedLine.pieces_per_product != null && savedLine.pieces_per_bar != null
    && Number(line.length_value) === savedLine.cutting_length_mm
    && Number(line.unit_consumption) === savedLine.pieces_per_product
    && Number(line.tube_cut_piece_count) === savedLine.pieces_per_bar
  if (!unchanged) return plan
  // 基准只读接口数据，不随编辑行提交；原参数不变的历史 BOM 继续按原版本显示。
  const version = Number(savedLine.raw_values?.pipe_plan_version ?? 2)
  if (version !== 2 && version !== 3) return null
  return version === 3 ? plan : pipePlan(line.length_value, line.unit_consumption, line.tube_cut_piece_count, quantity, 2)
}
