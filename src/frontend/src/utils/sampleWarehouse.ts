import type { SampleSupplyResult, SampleWarehouseDraft } from '@/types/sampleWarehouse'

// 十进制字符串运算避免 0.3 - 0.1 出现浮点尾数，与接口 Decimal(18,4) 一致。
export function sampleSupplyResult(required: string, supply: string): SampleSupplyResult {
  const pending = { valid: false, gap: null, result: 'pending', message: '请填写本次可供数量。' } as const
  if (!supply.trim()) return pending
  const invalid = (message: string): SampleSupplyResult => ({ valid: false, gap: null, result: 'invalid', message })
  if (!/^\d{1,14}(\.\d{1,4})?$/.test(required.trim()) || !/^\d{1,14}(\.\d{1,4})?$/.test(supply.trim())) return invalid('数量格式不正确，最多 14 位整数、4 位小数。')
  const needParts = required.trim().split('.')
  const supplyParts = supply.trim().split('.')
  const scale = Math.max(needParts[1]?.length || 0, supplyParts[1]?.length || 0)
  const integer = (parts: string[]) => BigInt(parts[0]! + (parts[1] || '').padEnd(scale, '0'))
  const need = integer(needParts), available = integer(supplyParts)
  if (need <= 0n) return invalid('需求数量必须大于 0。')
  if (available > need) return invalid('本次可供数量不能超过需求数量。')
  const difference = need - available
  let gap = difference.toString().padStart(scale + 1, '0')
  if (scale) gap = `${gap.slice(0, -scale)}.${gap.slice(-scale)}`.replace(/\.?0+$/, '')
  return { valid: true, gap, result: difference === 0n ? 'full' : available === 0n ? 'none' : 'partial' }
}

export function validateSampleWarehouse(draft: SampleWarehouseDraft): string {
  if (draft.notes.length > 2000) return '仓库备注不能超过 2000 字。'
  if (!draft.lines.length) return '尚无可核对的材料需求。'
  for (const [index, line] of draft.lines.entries()) {
    if (line.category === 'tube' && line.supplyQuantity.trim() && !/^\d+(?:\.0+)?$/.test(line.supplyQuantity.trim())) return `第 ${index + 1} 项材料：管材可供数量按整数支填写。`
    const result = sampleSupplyResult(line.quantity, line.supplyQuantity)
    if (!result.valid) return `第 ${index + 1} 项材料：${result.message}`
  }
  return ''
}

export function sampleShortageLines(draft: SampleWarehouseDraft) {
  return draft.lines.flatMap(line => {
    const result = sampleSupplyResult(line.quantity, line.supplyQuantity)
    return result.valid && result.gap !== '0' ? [{ ...line, shortageQuantity: result.gap }] : []
  })
}
