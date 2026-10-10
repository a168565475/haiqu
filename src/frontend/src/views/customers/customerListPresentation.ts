import type { CustomerActivitySummary } from '@/types/customer'

export type CustomerTagTone = 'success' | 'info' | 'warning' | 'danger' | 'neutral'

export interface DerivedStatusTag {
  label: string
  tone: CustomerTagTone
  title?: string
}

export function formatCustomerGradeCell(itemCode?: string): string {
  if (!itemCode) return '—'
  return /^[A-Z]$/.test(itemCode) ? `${itemCode}级` : itemCode
}

export function formatCustomerListDate(value: string | null): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  const parts = new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(date)
  const year = parts.find((item) => item.type === 'year')?.value
  const month = parts.find((item) => item.type === 'month')?.value
  const day = parts.find((item) => item.type === 'day')?.value
  return year && month && day ? `${year}-${month}-${day}` : '—'
}

export function getFollowUpStatus(value: string | null, now = new Date()): DerivedStatusTag {
  if (!value) return { label: '未安排', tone: 'neutral' }
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return { label: '未安排', tone: 'neutral', title: '跟进时间格式异常' }

  const today = new Date(now)
  today.setHours(0, 0, 0, 0)
  const targetDay = new Date(date)
  targetDay.setHours(0, 0, 0, 0)

  if (targetDay.getTime() < today.getTime()) return { label: '已逾期', tone: 'danger' }
  if (targetDay.getTime() === today.getTime()) return { label: '今日跟进', tone: 'warning' }
  return { label: '待跟进', tone: 'warning' }
}

export function getRiskStatus(activity: CustomerActivitySummary | null): DerivedStatusTag | null {
  if (activity?.activity_status !== 'HIGH_RISK') return null
  return {
    label: '高风险',
    tone: 'danger',
    title: activity.reason || '客户活动状态已标记为高风险',
  }
}
