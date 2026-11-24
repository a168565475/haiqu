import { decimalUnits } from './outsourcingQuantities'
import { pipeMeters } from './pipeQuantities'
import type { MaterialRequirement } from '@/types/materialIssue'

export function issueQuantityText(value: unknown): string {
  const text = String(value ?? '')
  return text.includes('.') ? text.replace(/0+$/, '').replace(/\.$/, '') : text
}

export function issueMeterText(value: unknown): string {
  const [whole, fraction = ''] = String(value ?? '').split('.')
  return whole ? `${whole}.${fraction.slice(0, 2).padEnd(2, '0')}` : '—'
}

export function issueOrderOverages(rows: MaterialRequirement[], selected: Record<string, string>) {
  const totals = new Map<string, { row: MaterialRequirement; requested: bigint; remaining: bigint }>()
  for (const row of rows) {
    const requested = decimalUnits(selected[row.requirement_id])
    if (!requested || row.product_order_remaining === null) continue
    // 旧半成品只有库存余额。公共半成品的不同工艺行共享同一部位的订单用量。
    if (row.line_type === 'SEMI' && row.stock_mode !== 'PUBLIC_V2') continue
    const component = row.line_type === 'SEMI' && row.conversion_snapshot?.component_identity
    const key = component ? `${component}:${row.unit}` : row.requirement_id
    const remaining = decimalUnits(row.product_order_remaining ?? row.component_order_remaining ?? row.order_remaining)
    if (remaining === null) throw new Error('领料需求数量无效')
    const total = totals.get(key)
    if (total) total.requested += requested
    else totals.set(key, { row, requested, remaining })
  }
  const format = (amount: bigint) => issueQuantityText(`${amount / 10000n}.${String(amount % 10000n).padStart(4, '0')}`)
  return [...totals.values()].filter(item => item.requested > item.remaining).map(({ row, requested, remaining }) => {
    const part = row.conversion_snapshot?.public_bom_snapshot?.line?.part_name || row.conversion_snapshot?.part_name || row.part_names?.join('、')
    const name = [...new Set([row.material_name, part, row.specification, row.line_type === 'RAW' ? row.color : ''].filter(Boolean))].join(' · ')
    return `${name}\n剩余需求 ${format(remaining)} ${row.unit}，本次领 ${format(requested)} ${row.unit}，超出 ${format(requested - remaining)} ${row.unit}`
  })
}

export function issuePipePlan(value: string, row: MaterialRequirement) {
  const input = decimalUnits(value)
  const cuts = BigInt(row.conversion_snapshot?.pieces_per_bar || 0)
  if (cuts <= 0n) {
    return { error: '管材换算规则缺失，请联系管理员核对每根切割支数。', bars: '—', meters: '—' }
  }
  if (input === null || input <= 0n || input % 10000n || input / 10000n % cuts) {
    return { error: `申请支数必须为 ${cuts} 的正整数倍（每根可切 ${cuts} 支）。`, bars: '—', meters: '—' }
  }
  const bars = String(input / 10000n / cuts)
  return { error: '', bars, meters: pipeMeters(bars, row.conversion_snapshot?.raw_bar_length_m) }
}

export function issueQuantityError(value: string, row: MaterialRequirement) {
  const amount = decimalUnits(value)
  if (amount === null || amount <= 0n) return '请输入大于零的数量，最多四位小数。'
  const integerSemi = row.line_type === 'SEMI' && (
    ['支', '套', '片'].includes(row.unit) || Boolean(row.component_kind) || ['SEMI_PIPE', 'SEMI_PIPE_PIECES'].includes(row.conversion_snapshot?.kind || '')
    || row.conversion_snapshot?.integer_required === true
  )
  if (integerSemi && amount % 10000n) return row.component_kind ? '裁片和部位数量必须为正整数。' : '半成品支数和套数必须为正整数。'
  if (row.line_type === 'RAW' && row.conversion_snapshot?.kind === 'PIPE') {
    const pipeError = issuePipePlan(value, row).error
    if (pipeError) return pipeError
  }
  const maximum = decimalUnits(row.source_kind === 'CUTTING_DIRECT' ? row.direct_available_quantity : row.max_issue_quantity)
  if (maximum === null || amount > maximum) return '申请数量超过当前可领上限。'
  return ''
}

export function issueSelectedQuantityError(value: string, row: MaterialRequirement,
  requirements: MaterialRequirement[], selected: Record<string, string>) {
  const error = issueQuantityError(value, row)
  if (error) return error
  if (row.source_kind === 'CUTTING_DIRECT') return ''
  if (!row.stock_item_id) return ''
  const isPipe = row.line_type === 'RAW' && row.conversion_snapshot?.kind === 'PIPE'
  const cuts = isPipe ? BigInt(row.conversion_snapshot?.pieces_per_bar || 0) : 1n
  const maximum = decimalUnits(row.max_issue_quantity)
  if (maximum === null || cuts <= 0n) return '可用库存或换算规则缺失，请刷新后重试。'
  const identity = row.stock_mode === 'PUBLIC_V2' ? row.conversion_snapshot?.public_identity?.identity_key : undefined
  const requested = requirements.filter(item => item.source_kind !== 'CUTTING_DIRECT' && item.line_type === row.line_type
    // 公共物料档案可有多种规格，合计必须使用服务端返回的实物库存身份。
    && (identity && item.conversion_snapshot?.public_identity?.identity_key
      ? item.conversion_snapshot.public_identity.identity_key === identity
      : item.stock_item_id === row.stock_item_id) && item.unit === row.unit
    && item.stock_mode === row.stock_mode
    && (!isPipe || item.conversion_snapshot?.raw_bar_length_m === row.conversion_snapshot?.raw_bar_length_m))
    .reduce((total, item) => {
      const amount = decimalUnits(item.requirement_id === row.requirement_id ? value : selected[item.requirement_id] || '0')
      const itemCuts = isPipe ? BigInt(item.conversion_snapshot?.pieces_per_bar || 0) : 1n
      return total + (amount !== null && amount > 0n && itemCuts > 0n ? amount / itemCuts : 0n)
    }, 0n)
  return requested > maximum / cuts ? '相同物料的合计申请数量超过扣除占用后的可用库存。' : ''
}
