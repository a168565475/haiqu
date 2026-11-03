import type { CreateReportPayload, ReportBusinessPayload, ReportEntry, ReportingRecordScope, ReportingScheme, ReportingSchemeLine, ReportingScope } from '@/types/reporting'

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
const categories = ['METAL', 'CUTTING', 'SEWING', 'ASSEMBLY']
const quantityScale = 10000n

export function reportingScope(query: Record<string, unknown>): ReportingScope | null {
  const scope = reportingRecordScope(query)
  return scope?.craft_id ? scope as ReportingScope : null
}

export function reportingRecordScope(query: Record<string, unknown>): ReportingRecordScope | null {
  const { schedule_product_id, workshop_id, craft_id, plan_category } = query
  if (![schedule_product_id, workshop_id].every(value => typeof value === 'string' && uuid.test(value))
    || typeof plan_category !== 'string' || !categories.includes(plan_category)
    || (craft_id !== undefined && (typeof craft_id !== 'string' || !uuid.test(craft_id)))) return null
  return { schedule_product_id, workshop_id, plan_category, ...(craft_id ? { craft_id } : {}) } as ReportingRecordScope
}

export function shanghaiToday(now = new Date()): string {
  const values = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(now)
  return ['year', 'month', 'day'].map(type => values.find(part => part.type === type)?.value).join('-')
}

export function validProductionDate(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false
  const date = new Date(`${value}T00:00:00Z`)
  return Number.isFinite(date.getTime()) && date.toISOString().slice(0, 10) === value
}

function scaledDecimal(value: string | null | undefined): bigint | null {
  if (typeof value !== 'string' || value.length > 24 || !/^\d+(?:\.\d{1,4})?$/.test(value)) return null
  const [whole, fraction = ''] = value.split('.')
  return BigInt(whole) * quantityScale + BigInt(fraction.padEnd(4, '0'))
}

function fromScaled(value: bigint): string {
  const fraction = (value % quantityScale).toString().padStart(4, '0').replace(/0+$/, '')
  return `${value / quantityScale}${fraction ? `.${fraction}` : ''}`
}

export function quantityText(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === '') return '—'
  const text = String(value)
  if (!/^\d+(?:\.\d+)?$/.test(text)) return '—'
  const [whole, fraction = ''] = text.split('.')
  const trimmed = fraction.replace(/0+$/, '')
  return `${whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',')}${trimmed ? `.${trimmed}` : ''}`
}

export function remainingQuantity(line: ReportingSchemeLine | undefined): string {
  if (!line) return '—'
  const required = scaledDecimal(line.required_quantity)
  const cumulative = scaledDecimal(line.cumulative_quantity)
  if (required === null || cumulative === null) return '—'
  return quantityText(fromScaled(required > cumulative ? required - cumulative : 0n))
}

export function estimatedLineAmount(line: ReportingSchemeLine | undefined, quantity: string): string {
  const price = scaledDecimal(line?.declared_price)
  if (price === null || !/^\d{1,14}$/.test(quantity)) return '—'
  // 与后端一致：每条报工按四位单价乘次数，四舍五入到分。
  const cents = (price * BigInt(quantity) + 50n) / 100n
  return `${cents / 100n}.${(cents % 100n).toString().padStart(2, '0')}`
}

export interface ReportValidation {
  error: string
  rows: Record<number, Partial<Record<'scheme_line_id' | 'workshop_employee_id' | 'production_line' | 'quantity', string>>>
  completesPlan: boolean
}

export function validateReportEntries(scheme: ReportingScheme, entries: ReportEntry[], employeeIds: Set<string>, assembly: boolean): ReportValidation {
  const result: ReportValidation = { error: '', rows: {}, completesPlan: false }
  const activeLines = scheme.lines.filter(line => line.status === 'ACTIVE')
  if (!activeLines.length) return { ...result, error: '没有可报工工序，请联系主管检查工价方案。' }
  if (activeLines.some(line => (scaledDecimal(line.required_quantity) ?? 0n) <= 0n || scaledDecimal(line.cumulative_quantity) === null)) {
    return { ...result, error: '工序需完成次数或累计信息不完整，请联系主管核对后刷新。' }
  }
  if (!entries.length) return { ...result, error: '请至少填写一道工序的报工。' }
  const totals = new Map<string, bigint>()
  for (const row of entries) {
    const errors: ReportValidation['rows'][number] = {}
    const line = activeLines.find(item => item.id === row.scheme_line_id)
    if (!line) errors.scheme_line_id = '请选择有效工序。'
    if (!employeeIds.has(row.workshop_employee_id)) errors.workshop_employee_id = '请选择本车间员工。'
    if (assembly && ![1, 2, 3].includes(row.production_line ?? 0)) errors.production_line = '请选择装配线。'
    if (!assembly && row.production_line !== null) errors.production_line = '当前车间不填写装配线。'
    if (!/^\d{1,14}$/.test(row.quantity.trim()) || BigInt(row.quantity.trim() || '0') <= 0n) {
      errors.quantity = '请输入大于 0 的整数次数，最多 14 位。'
    }
    else if (line) totals.set(line.work_item_id, (totals.get(line.work_item_id) ?? 0n) + BigInt(row.quantity.trim()) * quantityScale)
    if (Object.keys(errors).length) result.rows[row.key] = errors
  }
  for (const row of entries) {
    const line = activeLines.find(item => item.id === row.scheme_line_id)
    if (!line) continue
    const remaining = scaledDecimal(line.required_quantity)! - scaledDecimal(line.cumulative_quantity)!
    if ((totals.get(line.work_item_id) ?? 0n) > remaining) {
      result.rows[row.key] = { ...result.rows[row.key], quantity: `同一工序本次合计超过剩余次数，最多可报 ${remainingQuantity(line)}。` }
    }
  }
  result.completesPlan = !Object.keys(result.rows).length && activeLines.every(line => (
    scaledDecimal(line.cumulative_quantity)! + (totals.get(line.work_item_id) ?? 0n) >= scaledDecimal(line.required_quantity)!
  ))
  return result
}

export interface ReportAttempt { fingerprint: string; payload: CreateReportPayload }

export function prepareReportAttempt(business: ReportBusinessPayload, previous: ReportAttempt | null, newId: () => string): ReportAttempt {
  const fingerprint = JSON.stringify(business)
  if (previous?.fingerprint === fingerprint) return previous
  return { fingerprint, payload: { ...business, client_request_id: newId() } }
}

export function uncertainSubmission(error: unknown): boolean {
  const status = (error as { response?: { status?: number } })?.response?.status
  return status === undefined || status >= 500 || status === 408
}

export function needsCompletionConfirmation(error: unknown): boolean {
  return Boolean((error as { response?: { data?: { error?: { field_errors?: { confirm_plan_completion?: unknown } } } } })?.response?.data?.error?.field_errors?.confirm_plan_completion)
}

export function reportTime(value: string): string {
  const date = new Date(value)
  return Number.isFinite(date.getTime())
    ? new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }).format(date)
    : '—'
}
