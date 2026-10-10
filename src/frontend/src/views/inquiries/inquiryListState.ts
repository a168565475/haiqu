import type { InquiryRow } from '@/types/inquiry'

export const filterKeys = ['q', 'status', 'source_code', 'country_code', 'owner_employee_id', 'assignment_status', 'sla_state', 'product_q', 'received_from', 'received_to', 'has_quotation', 'priority', 'amount_min', 'amount_currency'] as const
export const columnChoices = [
  { key: 'country', label: '国家 / 地区' }, { key: 'source', label: '来源' },
  { key: 'priority', label: '优先级' }, { key: 'owner', label: '负责人' },
  { key: 'amount', label: '预估金额' }, { key: 'product', label: '产品' },
  { key: 'received', label: '接收时间' }, { key: 'sla', label: '处理时限' },
  { key: 'status', label: '状态' }, { key: 'reminder', label: '提醒' },
] as const
export const sortChoices = [
  { value: '-received_at', label: '接收时间：最新优先' },
  { value: 'received_at', label: '接收时间：最早优先' },
  { value: 'requested_due_at', label: '要求完成时间：最早优先' },
  { value: '-updated_at', label: '更新时间：最新优先' },
]
export function readListQuery(query: Record<string, unknown>) {
  const scalar = (value: unknown) => typeof value === 'string' ? value : typeof value === 'number' ? String(value) : ''
  const filters = Object.fromEntries(filterKeys.map(key => [key, scalar(query[key])])) as Record<typeof filterKeys[number], string>
  if (!['', 'UNASSIGNED', 'ASSIGNED'].includes(filters.assignment_status)) filters.assignment_status = ''
  if (!['', 'NONE', 'BREACHED', 'DUE_SOON', 'RISK'].includes(filters.sla_state)) filters.sla_state = ''
  if (!/^\d{1,32}(\.\d{1,8})?$/.test(filters.amount_min) || !/^[A-Z]{3}$/.test(filters.amount_currency)) { filters.amount_min = ''; filters.amount_currency = '' }
  if (!['', 'true', 'false'].includes(filters.has_quotation)) filters.has_quotation = ''
  if (!['', 'HIGH', 'MEDIUM', 'LOW', 'UNSET'].includes(filters.priority)) filters.priority = ''
  for (const key of ['received_from', 'received_to'] as const) {
    if (filters[key] && !Number.isFinite(Date.parse(filters[key]))) filters[key] = ''
  }
  const requestedPage = Number(scalar(query.page))
  const requestedSize = Number(scalar(query.page_size))
  return {
    filters,
    page: Number.isSafeInteger(requestedPage) && requestedPage > 0 ? requestedPage : 1,
    pageSize: [20, 50, 100].includes(requestedSize) ? requestedSize : 50,
    ordering: sortChoices.some(item => item.value === query.ordering) ? String(query.ordering) : '-received_at',
    view: query.view === 'board' ? 'board' as const : 'list' as const,
  }
}
export function readColumns(value: string | null): string[] {
  const defaults = columnChoices.map(item => item.key)
  try {
    const parsed: unknown = JSON.parse(value || 'null')
    return Array.isArray(parsed) ? [...new Set(parsed.filter((key): key is typeof defaults[number] => typeof key === 'string' && defaults.includes(key as typeof defaults[number])))] : defaults
  } catch { return defaults }
}
export function formatReceived(value: string) {
  const date = new Date(value)
  if (!Number.isFinite(date.getTime())) return { date: '—', time: '' }
  const parts = new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).formatToParts(date)
  const part = (key: string) => parts.find(item => item.type === key)?.value || ''
  return { date: `${part('year')}-${part('month')}-${part('day')}`, time: `${part('hour')}:${part('minute')}` }
}
export function slaPresentation(sla: InquiryRow['sla_summary']) {
  if (!sla || sla.state === 'NONE') return { label: '—', reminder: '—', tone: 'neutral' as const }
  const breached = sla.state === 'BREACHED'
  const due = sla.state === 'DUE_SOON'
  const seconds = sla.remaining_seconds
  const minutes = typeof seconds === 'number' && Number.isFinite(seconds) ? Math.max(0, Math.ceil(Math.abs(seconds) / 60)) : null
  const duration = minutes === null ? '' : minutes >= 1440 ? `${Math.floor(minutes / 1440)}天${Math.floor(minutes % 1440 / 60)}小时` : minutes >= 60 ? `${Math.floor(minutes / 60)}小时${minutes % 60}分` : `${minutes}分钟`
  return { label: duration ? `${breached ? '超时' : '剩余'} ${duration}` : breached ? '已超时' : due ? '即将超时' : '正常', reminder: breached ? '已超时' : due ? '即将超时' : '正常', tone: breached ? 'danger' as const : due ? 'warning' as const : 'success' as const }
}
export function allRowsAllow(rows: InquiryRow[], action: 'assign' | 'mark_invalid') {
  return rows.length > 0 && rows.every(row => Boolean(row.id && row.etag && row.allowed_actions?.[action]))
}
export function formatEstimatedAmount(row: Pick<InquiryRow, 'product_amount'>) {
  const summary = row.product_amount
  if (!summary || !summary.item_count) return '—'
  if (summary.missing_price_count > 0) return '待补齐'
  if (!summary.totals?.length) return '—'
  const amounts = summary.totals.map(total => {
    if (!/^[A-Z]{3}$/.test(total.currency_code) || !/^\d+(\.\d+)?$/.test(total.amount)) return null
    const [whole = '0', fraction = ''] = total.amount.split('.')
    return `${total.currency_code} ${whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',')}.${fraction.replace(/0+$/, '').padEnd(2, '0')}`
  })
  return amounts.some(amount => amount === null) ? '—' : amounts.join(' / ')
}
export function statusTone(status: string): 'success' | 'warning' | 'danger' | 'info' | 'neutral' {
  if (['QUOTE_ACCEPTED', 'CONVERTED'].includes(status)) return 'success'
  if (['LOST', 'CANCELLED'].includes(status)) return 'danger'
  if (['NEW', 'DRAFT', 'READY_FOR_QUOTE'].includes(status)) return 'warning'
  if (['ANALYZING', 'QUOTING', 'QUOTED', 'FOLLOW_UP'].includes(status)) return 'info'
  return 'neutral'
}
export function priorityTone(priority?: string): 'danger' | 'warning' | 'neutral' {
  return priority === 'HIGH' ? 'danger' : priority === 'MEDIUM' ? 'warning' : 'neutral'
}

