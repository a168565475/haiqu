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
    ['支', '套'].includes(row.unit) || ['SEMI_PIPE', 'SEMI_PIPE_PIECES'].includes(row.conversion_snapshot?.kind || '')
    || row.conversion_snapshot?.integer_required === true
  )
  if (integerSemi && amount % 10000n) return '半成品支数和套数必须为正整数。'
  if (row.line_type === 'RAW' && row.conversion_snapshot?.kind === 'PIPE') {
    const pipeError = issuePipePlan(value, row).error
    if (pipeError) return pipeError
  }
  const maximum = decimalUnits(row.max_issue_quantity)
  if (maximum === null || amount > maximum) return '申请数量超过当前可领上限。'
  return ''
}

export function issueSelectedQuantityError(value: string, row: MaterialRequirement,
  requirements: MaterialRequirement[], selected: Record<string, string>) {
  const error = issueQuantityError(value, row)
  if (error) return error
  const component = row.conversion_snapshot?.component_identity
  if (row.line_type !== 'SEMI' || row.stock_mode !== 'PUBLIC_V2' || !component) return ''
  const remaining = decimalUnits(row.component_order_remaining ?? row.order_remaining)
  if (remaining === null) return '半成品部位额度缺失，请刷新后重试。'
  const requested = requirements.filter(item => item.line_type === 'SEMI'
    && item.stock_mode === 'PUBLIC_V2' && item.unit === row.unit
    && item.conversion_snapshot?.component_identity === component)
    .reduce((total, item) => {
      const amount = decimalUnits(selected[item.requirement_id] || '0')
      return total + (amount !== null && amount > 0n ? amount : 0n)
    }, 0n)
  return requested > remaining ? '同一部位的半成品合计申请数量超过订单剩余额度。' : ''
}
