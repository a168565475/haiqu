import type { InquiryListItem } from '../../typings/inquiry';
import type { InquiryDetail, InquirySla, InquiryWorkCalendar } from '../../typings/inquiry-detail';

export const inquirySteps = [
  { code: 'NEW', label: '新询盘' },
  { code: 'ASSIGNED', label: '已分配' },
  { code: 'ANALYZING', label: '已首响' },
  { code: 'READY_FOR_QUOTE', label: '需求确认' },
  { code: 'QUOTING', label: '报价中' },
  { code: 'CONVERTED', label: '已转订单' }
];

export function inquiryStepIndex(status: string, hasOwner = false): number {
  // 分配是负责人事实，不新增数据库状态；报价接受仍保留在报价阶段。
  const stage =
    status === 'NEW' && hasOwner
      ? 'ASSIGNED'
      : ['QUOTED', 'FOLLOW_UP', 'QUOTE_ACCEPTED'].includes(status)
        ? 'QUOTING'
        : status;
  return inquirySteps.findIndex(step => step.code === stage);
}

export function safeWebsite(value: unknown): string {
  if (typeof value !== 'string' || !value.trim()) return '';
  try {
    const url = new URL(value.trim());
    return ['http:', 'https:'].includes(url.protocol) && !url.username && !url.password ? url.href : '';
  } catch {
    return '';
  }
}

export function formatInquiryTime(value?: string | null): string {
  if (!value) return '—';
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return '—';
  const parts = new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23'
  }).formatToParts(date);
  const part = (key: string) => parts.find(item => item.type === key)?.value || '';
  return `${part('year')}-${part('month')}-${part('day')} ${part('hour')}:${part('minute')}`;
}

export function formatInquiryNumber(value: string | number | null, minimumDecimals = 0): string {
  if (value === null || value === '') return '—';
  const text = String(value);
  if (!/^\d+(\.\d+)?$/.test(text)) return '—';
  const [whole, fraction = ''] = text.split('.');
  const decimals = fraction.replace(/0+$/, '').padEnd(minimumDecimals, '0');
  return `${whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',')}${decimals ? `.${decimals}` : ''}`;
}

export function formatEstimatedAmount(row: Pick<InquiryListItem, 'product_amount'>): string {
  const summary = row.product_amount;
  if (!summary?.item_count) return '—';
  if (summary.missing_price_count > 0) return '待补齐';
  if (!summary.totals.length) return '—';
  const amounts = summary.totals.map(total => {
    const amount = formatInquiryNumber(total.amount, 2);
    return /^[A-Z]{3}$/.test(total.currency_code) && amount !== '—' ? `${total.currency_code} ${amount}` : null;
  });
  return amounts.some(amount => amount === null) ? '—' : amounts.join(' / ');
}

function validWorkPeriods(periods: unknown): periods is [number, number][] {
  if (!Array.isArray(periods) || periods.length !== 2) return false;
  let previousEnd = -1;
  for (const period of periods) {
    if (!Array.isArray(period) || period.length !== 2 || !period.every(Number.isInteger)) return false;
    const [start, end] = period;
    if (start < 0 || start >= end || end > 1440 || start < previousEnd) return false;
    previousEnd = end;
  }
  return true;
}

export function workMilliseconds(start: number, end: number, calendar?: InquiryWorkCalendar | null): number {
  if (!Number.isFinite(start) || !Number.isFinite(end)) return NaN;
  // 日历来自后端阶段快照；没有快照的旧记录保留连续计时。
  if (!calendar) return end - start;
  if (calendar.mode !== 'ALTERNATING_WEEKS_V1' || calendar.timezone !== 'Asia/Shanghai') return NaN;
  if (end < start) return -workMilliseconds(end, start, calendar);
  const dayLength = 86400000;
  const offset = 8 * 3600000;
  const anchor = Date.parse(`${calendar.rest_saturday}T00:00:00+08:00`);
  if (!Number.isFinite(anchor) || new Date(anchor + offset).getUTCDay() !== 6) return NaN;
  if (!validWorkPeriods(calendar.periods)) return NaN;
  const first = Math.floor((start + offset) / dayLength) * dayLength - offset;
  const last = Math.floor((end + offset) / dayLength) * dayLength - offset;
  if ((last - first) / dayLength > 36600) return NaN;
  let total = 0;
  for (let day = first; day <= last; day += dayLength) {
    const weekday = new Date(day + offset).getUTCDay();
    if (weekday === 0 || (weekday === 6 && Math.floor((day - anchor) / (7 * dayLength)) % 2 === 0)) continue;
    for (const [begin, finish] of calendar.periods) {
      total += Math.max(0, Math.min(end, day + finish * 60000) - Math.max(start, day + begin * 60000));
    }
  }
  return total;
}

export function currentHandlingRecords(records: readonly InquirySla[]): InquirySla[] {
  return records
    .filter(record => record.is_current)
    .sort((left, right) => {
      const leftTime = Date.parse(left.next_deadline_at || '');
      const rightTime = Date.parse(right.next_deadline_at || '');
      return (
        (Number.isFinite(leftTime) ? leftTime : Infinity) - (Number.isFinite(rightTime) ? rightTime : Infinity) ||
        left.id.localeCompare(right.id)
      );
    });
}

export function handlingStageLabel(stage: string): string {
  const labels: Record<string, string> = {
    ASSIGNMENT: '分配负责人',
    FIRST_RESPONSE: '首次回复',
    REQUIREMENT_CONFIRMATION: '需求确认',
    QUOTE_CREATION: '创建报价',
    QUOTE_DELIVERY: '完成并发送报价',
    CUSTOMER_FOLLOW_UP: '报价后跟进',
    POST_ACCEPTANCE: '报价接受后推进',
    SAMPLE_FOLLOW_UP: '样品进度跟进'
  };
  return labels[stage] || '处理阶段';
}

export function handlingTargetLabel(minutes: number): string {
  if (!Number.isFinite(minutes) || minutes <= 0) return '未启用';
  return minutes < 60 ? `${minutes} 分钟` : `${minutes / 60} 个工作小时`;
}

export function handlingStatusLabel(
  status: string,
  completedAt?: string | null,
  deadline?: string | null,
  now?: number
): string {
  if (status === 'RUNNING' && deadline && now !== undefined && Date.parse(deadline) < now && !completedAt)
    return '已超时';
  if (status === 'BREACHED') return completedAt ? '超时完成' : '已超时';
  const labels: Record<string, string> = {
    RUNNING: '进行中',
    MET: '按时完成',
    COMPLETED: '已完成',
    CANCELLED: '已终止',
    PAUSED: '已暂停'
  };
  return labels[status] || '未知状态';
}

export function workCalendarDescription(calendar: InquiryWorkCalendar): string {
  if (!validWorkPeriods(calendar.periods)) return '工作日历不完整';
  const clock = (value: number) =>
    `${String(Math.floor(value / 60)).padStart(2, '0')}:${String(value % 60).padStart(2, '0')}`;
  const periods = calendar.periods.map(([start, end]) => `${clock(start)}—${clock(end)}`).join('、');
  const hours = calendar.periods.reduce((total, [start, end]) => total + end - start, 0) / 60;
  return `工作时段：${periods}，每天 ${Number(hours.toFixed(2))} 小时。`;
}

export function durationText(milliseconds: number): string {
  if (!Number.isFinite(milliseconds)) return '—';
  const minutes = Math.ceil(Math.abs(milliseconds) / 60000);
  return minutes >= 60 ? `${Math.floor(minutes / 60)} 小时 ${minutes % 60} 分钟` : `${minutes} 分钟`;
}

export function slaPresentation(
  sla: InquirySla | undefined,
  now: number,
  status: string
): {
  label: string;
  percentage: number | null;
  overdue: boolean;
} {
  const inactive = ['DRAFT', 'CLOSED', 'CANCELLED', 'LOST', 'CONVERTED'].includes(status);
  if (!sla || inactive)
    return {
      label: inactive && status !== 'DRAFT' ? '当前流程已结束' : '暂无时效记录',
      percentage: null,
      overdue: false
    };
  if (sla.completed_at || !['RUNNING', 'BREACHED'].includes(sla.status)) {
    return { label: handlingStatusLabel(sla.status, sla.completed_at), percentage: null, overdue: false };
  }
  const deadline = Date.parse(sla.next_deadline_at || '');
  const start = Date.parse(sla.started_at);
  if (!Number.isFinite(deadline))
    return {
      label: sla.status === 'BREACHED' ? '已超时' : '未设置截止时间',
      percentage: null,
      overdue: sla.status === 'BREACHED'
    };
  const overdue = sla.status === 'BREACHED' || deadline < now;
  const remaining = workMilliseconds(now, deadline, sla.work_calendar);
  const total = workMilliseconds(start, deadline, sla.work_calendar);
  return {
    label:
      sla.status === 'BREACHED' && deadline > now
        ? '已超时'
        : `${overdue ? '已超时' : '剩余'} ${durationText(remaining)}${sla.work_calendar ? '（工作时间）' : ''}`,
    percentage:
      Number.isFinite(total) && total > 0 ? Math.max(0, Math.min(100, ((total - remaining) / total) * 100)) : null,
    overdue
  };
}

type NextActionDetail = Pick<InquiryDetail, 'status' | 'status_display' | 'customer_contact' | 'owner'>;
type NextStepDetail = NextActionDetail & { linked_sales_orders: readonly { status: string }[] };
type ActionCopy = { title: string; description: string };

function nextInquiryAction(detail: NextActionDetail): string {
  const messages: Record<string, string> = {
    DRAFT: '继续编辑草稿并确认提交',
    CLOSED: '询盘已关闭',
    CANCELLED: '询盘已取消',
    LOST: '询盘已丢失',
    CONVERTED: '在销售订单中跟踪后续进度',
    NEW: '记录与客户的第一次有效响应',
    ANALYZING: '与客户确认需求细节',
    READY_FOR_QUOTE: '创建正式报价',
    QUOTING: '跟进报价并记录客户反馈',
    QUOTED: '跟进报价并记录客户反馈',
    FOLLOW_UP: '继续记录客户沟通',
    QUOTE_ACCEPTED: '创建销售订单或安排样品'
  };
  if (!['DRAFT', 'CLOSED', 'CANCELLED', 'LOST', 'CONVERTED'].includes(detail.status) && !detail.customer_contact)
    return '先补充联系人';
  return messages[detail.status] || detail.status_display;
}

export function inquiryNextActionCopy(detail: NextActionDetail): ActionCopy {
  const stage = inquiryStepIndex(detail.status, Boolean(detail.owner));
  const titles = [
    '完成询盘分配',
    '完成第一次有效响应',
    '与客户确认需求细节',
    '创建正式报价',
    '跟进报价反馈',
    '转入销售订单履约'
  ];
  const descriptions = [
    '确认客户归属、国家与来源，并分配具备对应市场经验的业务员。',
    '通过邮件、电话或 WhatsApp 回复客户，并记录实际沟通内容。',
    '确认产品规格、目标价、交期及包装要求，必要时补充产品资料。',
    '需求信息已经满足报价前置条件，可生成报价草稿并补录单价。',
    '记录客户对价格、交期和贸易条款的反馈；必要时创建新报价版本。',
    '询盘已完成业务衔接，生产、交付与收款在销售订单中继续跟踪。'
  ];
  if (stage > 0 && stage < 5 && !detail.customer_contact)
    return { title: '先补充联系人', description: '当前询盘缺少联系人，请选择客户的有效联系人后继续。' };
  if (stage > 0 && stage < 5 && !detail.owner) return { title: '完成询盘分配', description: descriptions[0] };
  return { title: titles[stage] || nextInquiryAction(detail), description: descriptions[stage] || '' };
}

export function nextStepCopy(detail: NextStepDetail, currentSla?: InquirySla): ActionCopy {
  if (detail.linked_sales_orders.some(order => order.status !== 'CANCELLED')) {
    return { title: '在销售订单中继续处理', description: '询盘计时已结束，订单确认及后续履约按销售订单流程处理。' };
  }
  const descriptions: Record<string, string> = {
    QUOTE_CREATION: '需求已经确认，请创建关联报价。',
    QUOTE_DELIVERY: '完善报价内容并正式发送给客户。',
    CUSTOMER_FOLLOW_UP: '记录实际客户跟进，完成后开始下一轮跟进计时。',
    POST_ACCEPTANCE: '客户已接受报价，请提交样品申请或创建销售订单。',
    SAMPLE_FOLLOW_UP: '跟踪关联样品进度，并记录本次实际跟进。'
  };
  const stage = currentSla?.stage_code;
  return stage && descriptions[stage]
    ? { title: handlingStageLabel(stage), description: descriptions[stage] }
    : inquiryNextActionCopy(detail);
}
