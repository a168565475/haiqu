import type {
  MilestoneItem,
  SalesFunnelItem,
  SlaItem,
  TeamLoadItem,
  TeamPerformanceItem,
} from '@/types/workbench'

function addDays(reference: Date, days: number): Date {
  const value = new Date(reference)
  value.setDate(value.getDate() + days)
  return value
}

export function workbenchReferenceDate(): Date {
  const configured = import.meta.env.VITE_WORKBENCH_REFERENCE_DATE
  if (configured) {
    const parsed = new Date(`${configured}T12:00:00`)
    if (!Number.isNaN(parsed.getTime())) return parsed
  }
  return new Date()
}

export function formatMonthDay(value: Date): string {
  return `${String(value.getMonth() + 1).padStart(2, '0')}-${String(value.getDate()).padStart(2, '0')}`
}

export const salesDemoCounts = {
  pendingInquiryReplies: 8,
  pendingQuotationFeedback: 6,
  pendingSampleFeedback: 4,
}

export const managerDemoMetrics = {
  monthlySales: '$1.02M',
  marginRate: '21.7%',
  newInquiries: '173',
  quotationTimeliness: '88.7%',
}

export const salesFunnelDemo: SalesFunnelItem[] = [
  { label: '新询盘', value: '$386,000', ratio: 100, color: '#1478db' },
  { label: '需求确认', value: '$248,000', ratio: 80, color: '#3f8fe8' },
  { label: '报价中', value: '$186,400', ratio: 56, color: '#68a5ea' },
  { label: '样品中', value: '$92,800', ratio: 34, color: '#df7900' },
  { label: '预计成交', value: '$61,200', ratio: 22, color: '#008a33' },
]

export function createMilestoneDemo(reference = workbenchReferenceDate()): MilestoneItem[] {
  return [
    { title: 'ORD-2026-0088 · 产前样确认', customer: '今天 15:30', date: formatMonthDay(addDays(reference, 0)), status: '等待客户' },
    { title: 'ORD-2026-0076 · 验货计划确认', customer: '明天 10:00', date: formatMonthDay(addDays(reference, 1)), status: '待协同' },
    { title: 'ORD-2026-0062 · 竞货前订舱', customer: '8 月 24 日', date: formatMonthDay(addDays(reference, 3)), status: '临近' },
    { title: 'ORD-2026-0057 · 余款与单证', customer: '8 月 25 日', date: formatMonthDay(addDays(reference, 4)), status: '风险' },
  ]
}

export const teamPerformanceDemo: TeamPerformanceItem[] = [
  { rank: 1, name: '业务员 A', amount: '$286,400', margin: '24.8%', inquiries: 38, followUp: '96%', status: '领先', tone: 'success' },
  { rank: 2, name: '业务员 B', amount: '$243,800', margin: '22.1%', inquiries: 42, followUp: '91%', status: '正常', tone: 'neutral' },
  { rank: 3, name: '业务员 C', amount: '$198,600', margin: '20.5%', inquiries: 35, followUp: '88%', status: '关注', tone: 'warning' },
  { rank: 4, name: '业务员 D', amount: '$164,200', margin: '18.9%', inquiries: 27, followUp: '84%', status: '关注', tone: 'warning' },
  { rank: 5, name: '业务员 E', amount: '$126,900', margin: '17.2%', inquiries: 31, followUp: '76%', status: '风险', tone: 'danger' },
]

export const teamLoadDemo: TeamLoadItem[] = [
  { name: '业务员 A', current: 12, overdue: 3, ratio: 78, tone: 'warning' },
  { name: '业务员 B', current: 9, overdue: 1, ratio: 62, tone: 'normal' },
  { name: '业务员 C', current: 16, overdue: 5, ratio: 93, tone: 'danger' },
  { name: '业务员 D', current: 7, overdue: 0, ratio: 48, tone: 'normal' },
  { name: '业务员 E', current: 11, overdue: 2, ratio: 71, tone: 'warning' },
]

export const slaDemo: SlaItem[] = [
  { label: '首响及时率', value: '92.4%', note: '目标 ≥ 95%', badge: '临界', tone: 'warning' },
  { label: '报价 48h 完成率', value: '88.7%', note: '较上周 -3.2%', badge: '下降', tone: 'warning' },
  { label: '样品签收后反馈', value: '81.5%', note: '6 项超过 3 天', badge: '风险', tone: 'danger' },
  { label: '任务按时完成率', value: '89.6%', note: '业务员 C 需关注', badge: '关注', tone: 'warning' },
]
