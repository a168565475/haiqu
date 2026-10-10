/** 与后端一致的整数换算；预览不使用浮点数舍入。 */
export function pipePlan(length: string, consumption: string, cuts: string, quantity: string) {
  const values = [length, consumption, cuts, quantity].map((value) => value.trim())
  if (values.some((value) => !/^\d+(?:\.0+)?$/.test(value) || value.length > 30)) return null
  const [l, u, k, q] = values.map((value) => BigInt(value.split('.')[0]!)) as [bigint, bigint, bigint, bigint]
  if ([l, u, k, q].some((value) => value <= 0n || value >= 100000000000000n)) return null
  const demand = q * u
  const roots = (demand * 101n + k * 100n - 1n) / (k * 100n)
  const centimeters = (l * k + 50n + 9n) / 10n
  const total = centimeters * roots
  if (demand >= 100000000000000n || roots * k >= 100000000000000n || centimeters >= 1000000000000000000n || total >= 10000000000000000000000n) return null
  const meters = (value: bigint) => `${value / 100n}.${String(value % 100n).padStart(2, '0')}`
  return { total_consumption: String(demand), branch_count: String(roots), tube_cut_length_m: meters(centimeters),
    suggested_purchase_meters: meters(total) }
}
