import type { CustomerDetail, CustomerSummary, CustomerTimelineEvent } from '@/types/customer'

export type OverviewTone = 'success' | 'info' | 'warning' | 'danger' | 'neutral'

export interface CustomerHealthFact {
  label: string
  meta: string
  tone: OverviewTone
}

export interface CustomerHealthSummary {
  label: string
  tone: OverviewTone
  facts: CustomerHealthFact[]
}

export function formatOverviewMoney(
  value: string | number | null | undefined,
  currency = 'USD',
): string {
  if (value === null || value === undefined || value === '') return '—'
  const amount = Number(value)
  if (!Number.isFinite(amount)) return '—'
  return `${currency || 'USD'} ${amount.toLocaleString('en-US', { maximumFractionDigits: 2 })}`
}

export function formatOverviewDateTime(value: string | null | undefined): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  const parts = new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).formatToParts(date)
  const valueOf = (type: Intl.DateTimeFormatPartTypes) => parts.find((part) => part.type === type)?.value || ''
  return `${valueOf('year')}-${valueOf('month')}-${valueOf('day')} ${valueOf('hour')}:${valueOf('minute')}`
}

export function formatTimelineDate(value: string | null | undefined): { date: string; time: string } {
  const formatted = formatOverviewDateTime(value)
  if (formatted === '—') return { date: '—', time: '' }
  return { date: formatted.slice(5, 10), time: formatted.slice(11) }
}

export function calculateCreditUsage(customer: CustomerDetail): number | null {
  const rawLimit = customer.business_snapshot?.credit_limit
  const rawUsed = customer.business_snapshot?.credit_used
  if (rawLimit === null || rawLimit === undefined || rawUsed === null || rawUsed === undefined) return null
  const limit = Number(rawLimit)
  const used = Number(rawUsed)
  if (!Number.isFinite(limit) || !Number.isFinite(used) || limit <= 0 || used < 0) return null
  return Math.min(100, Math.round((used / limit) * 100))
}

export function timelineCategory(event: CustomerTimelineEvent): {
  label: string
  tone: OverviewTone
} {
  const key = `${event.source_type} ${event.event_type}`.toUpperCase()
  if (key.includes('COMMUNICATION')) return { label: '沟通', tone: 'warning' }
  if (key.includes('QUOTATION')) return { label: '报价', tone: 'success' }
  if (key.includes('SAMPLE')) return { label: '样品', tone: 'info' }
  if (key.includes('TASK')) return { label: '任务', tone: 'info' }
  if (key.includes('INQUIRY')) return { label: '询盘', tone: 'warning' }
  if (key.includes('CONTACT')) return { label: '联系人', tone: 'neutral' }
  return { label: '系统', tone: 'neutral' }
}

export function buildCustomerHealthSummary(
  customer: CustomerDetail,
  summary: CustomerSummary | null,
  latestInteractionAt?: string | null,
): CustomerHealthSummary {
  const currency = customer.business_snapshot?.currency_code || 'USD'
  const usage = calculateCreditUsage(customer)
  const openComplaints = summary?.counts.open_complaints ?? 0
  const overdueTasks = summary?.counts.overdue_tasks ?? 0
  const riskCount = openComplaints + overdueTasks
  const recentAt = latestInteractionAt || customer.last_contact_at

  const facts: CustomerHealthFact[] = [
    usage === null
      ? { label: '信用额度数据未接入', meta: '—', tone: 'neutral' }
      : {
          label: `信用额度使用 ${usage}%`,
          meta: `已用 ${formatOverviewMoney(customer.business_snapshot?.credit_used, currency)} / ${formatOverviewMoney(customer.business_snapshot?.credit_limit, currency).replace(`${currency} `, '')}`,
          tone: 'info',
        },
    { label: '应收逾期数据未接入', meta: '—', tone: 'neutral' },
    recentAt
      ? { label: '已有最近互动记录', meta: formatOverviewDateTime(recentAt), tone: 'success' }
      : { label: '暂无最近互动记录', meta: '—', tone: 'neutral' },
    riskCount > 0
      ? {
          label: `待处理风险 ${riskCount} 项`,
          meta: `开放客诉 ${openComplaints} · 逾期任务 ${overdueTasks}`,
          tone: 'warning',
        }
      : { label: '暂无开放客诉或逾期任务', meta: '来自客户汇总', tone: 'success' },
  ]

  if (riskCount > 0) return { label: '需关注', tone: 'warning', facts }
  if (usage === null) return { label: '数据待完善', tone: 'neutral', facts }
  return { label: '整体正常', tone: 'success', facts }
}
