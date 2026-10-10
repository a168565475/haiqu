import type { InquiryDetail, InquirySla } from '@/types/inquiry'
import { workMilliseconds, handlingStatusLabel } from './inquiryWorktime'

export const inquirySteps = [
  { code: 'NEW', label: '新询盘' }, { code: 'ASSIGNED', label: '已分配' },
  { code: 'ANALYZING', label: '已首响' }, { code: 'READY_FOR_QUOTE', label: '需求确认' },
  { code: 'QUOTING', label: '报价中' }, { code: 'CONVERTED', label: '已转订单' },
]
export function inquiryStepIndex(status: string, hasOwner = false) {
  // 分配是负责人事实，不新增数据库状态；报价接受仍保留在报价阶段。
  const stage = status === 'NEW' && hasOwner ? 'ASSIGNED'
    : ['QUOTED', 'FOLLOW_UP', 'QUOTE_ACCEPTED'].includes(status) ? 'QUOTING' : status
  return inquirySteps.findIndex(step => step.code === stage)
}
export function safeWebsite(value: unknown) {
  if (typeof value !== 'string' || !value.trim()) return ''
  try {
    const url = new URL(value.trim())
    return ['http:', 'https:'].includes(url.protocol) && !url.username && !url.password ? url.href : ''
  } catch { return '' }
}
export function formatInquiryTime(value?: string | null) {
  if (!value) return '—'
  const date = new Date(value)
  if (!Number.isFinite(date.getTime())) return '—'
  return new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }).format(date).replaceAll('/', '-')
}
export function formatInquiryNumber(value: string | number | null, minimumDecimals = 0) {
  if (value === null || value === '') return '—'
  const text = String(value)
  if (!/^\d+(\.\d+)?$/.test(text)) return '—'
  const [whole = '0', fraction = ''] = text.split('.')
  const decimals = fraction.replace(/0+$/, '').padEnd(minimumDecimals, '0')
  return `${whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',')}${decimals ? `.${decimals}` : ''}`
}
export function durationText(milliseconds: number) {
  if (!Number.isFinite(milliseconds)) return '—'
  const minutes = Math.max(0, Math.ceil(Math.abs(milliseconds) / 60000))
  return minutes >= 60 ? `${Math.floor(minutes / 60)} 小时 ${minutes % 60} 分钟` : `${minutes} 分钟`
}
export function slaPresentation(sla: InquirySla | undefined, now: number, status: string) {
  const inactive = ['DRAFT', 'CLOSED', 'CANCELLED', 'LOST', 'CONVERTED'].includes(status)
  if (!sla || inactive) return { label: inactive && status !== 'DRAFT' ? '当前流程已结束' : '暂无时效记录', percentage: null, overdue: false }
  if (sla.completed_at || !['RUNNING', 'BREACHED'].includes(sla.status)) return { label: handlingStatusLabel(sla.status, sla.completed_at), percentage: null, overdue: false }
  const deadline = Date.parse(sla.next_deadline_at || '')
  const start = Date.parse(sla.started_at)
  if (!Number.isFinite(deadline)) return { label: sla.status === 'BREACHED' ? '已超时' : '未设置截止时间', percentage: null, overdue: sla.status === 'BREACHED' }
  const overdue = sla.status === 'BREACHED' || deadline < now
  const remaining = workMilliseconds(now, deadline, sla.work_calendar)
  const total = workMilliseconds(start, deadline, sla.work_calendar)
  return {
    label: sla.status === 'BREACHED' && deadline > now ? '已超时' : `${overdue ? '已超时' : '剩余'} ${durationText(remaining)}${sla.work_calendar ? '（工作时间）' : ''}`,
    percentage: Number.isFinite(total) && total > 0 ? Math.max(0, Math.min(100, (total - remaining) / total * 100)) : null,
    overdue,
  }
}
export function nextInquiryAction(detail: Pick<InquiryDetail, 'status' | 'status_display' | 'customer_contact'>) {
  const messages: Record<string, string> = {
    DRAFT: '继续编辑草稿并确认提交', CLOSED: '询盘已关闭', CANCELLED: '询盘已取消', LOST: '询盘已丢失',
    CONVERTED: '在销售订单中跟踪后续进度', NEW: '记录与客户的第一次有效响应', ANALYZING: '与客户确认需求细节',
    READY_FOR_QUOTE: '创建正式报价', QUOTING: '跟进报价并记录客户反馈', QUOTED: '跟进报价并记录客户反馈',
    FOLLOW_UP: '继续记录客户沟通', QUOTE_ACCEPTED: '创建销售订单或安排样品',
  }
  if (!['DRAFT', 'CLOSED', 'CANCELLED', 'LOST', 'CONVERTED'].includes(detail.status) && !detail.customer_contact) return '先补充联系人'
  return messages[detail.status] || detail.status_display
}

export function inquiryNextActionCopy(detail: Pick<InquiryDetail, 'status' | 'status_display' | 'customer_contact' | 'owner'>) {
  const stage = inquiryStepIndex(detail.status, !!detail.owner)
  const titles = ['完成询盘分配', '完成第一次有效响应', '与客户确认需求细节', '创建正式报价', '跟进报价反馈', '转入销售订单履约']
  const descriptions = [
    '确认客户归属、国家与来源，并分配具备对应市场经验的业务员。',
    '通过邮件、电话或 WhatsApp 回复客户，并记录实际沟通内容。',
    '确认产品规格、目标价、交期及包装要求，必要时补充产品资料。',
    '需求信息已经满足报价前置条件，可生成报价草稿并补录单价。',
    '记录客户对价格、交期和贸易条款的反馈；必要时创建新报价版本。',
    '询盘已完成业务衔接，生产、交付与收款在销售订单中继续跟踪。',
  ]
  if (stage > 0 && stage < 5 && !detail.customer_contact) return { title: '先补充联系人', description: '当前询盘缺少联系人，请选择客户的有效联系人后继续。' }
  if (stage > 0 && stage < 5 && !detail.owner) return { title: '完成询盘分配', description: descriptions[0] }
  return { title: titles[stage] || nextInquiryAction(detail), description: descriptions[stage] || '' }
}
