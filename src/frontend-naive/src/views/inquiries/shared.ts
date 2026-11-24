import type { InquiryListItem, InquiryQuery, InquiryStatus } from '../../typings/inquiry';

export const inquiryPageSizes = [20, 50, 100];
export const inquirySlaOptions = [
  { label: '即将超时、已超时', value: 'RISK' },
  { label: '即将超时', value: 'DUE_SOON' },
  { label: '已超时', value: 'BREACHED' },
  { label: '无进行中的计时', value: 'NONE' }
] satisfies { label: string; value: InquiryQuery['sla_state'] }[];

const statuses: readonly InquiryStatus[] = [
  'DRAFT',
  'NEW',
  'ANALYZING',
  'READY_FOR_QUOTE',
  'QUOTING',
  'QUOTED',
  'FOLLOW_UP',
  'QUOTE_ACCEPTED',
  'CONVERTED',
  'LOST',
  'CLOSED',
  'CANCELLED'
];
const orderings = ['-received_at', 'received_at', 'requested_due_at', '-updated_at'] as const;
const priorities = ['HIGH', 'MEDIUM', 'LOW', 'UNSET'] as const;
type TagType = 'success' | 'warning' | 'error' | 'info' | 'default';

function text(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}

function positiveInteger(value: unknown, fallback: number): number {
  if (typeof value !== 'number' && (typeof value !== 'string' || !/^\d+$/.test(value))) return fallback;
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : fallback;
}

function isCalendarDate(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const date = new Date(`${value}T00:00:00Z`);
  return Number.isFinite(date.getTime()) && date.toISOString().slice(0, 10) === value;
}

function timestamp(value: unknown): string {
  const candidate = text(value);
  return /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(candidate) &&
    isCalendarDate(candidate.slice(0, 10)) &&
    Number.isFinite(Date.parse(candidate))
    ? candidate
    : '';
}

export function normalizeInquiryQuery(
  query: Readonly<Record<string, unknown>>
): InquiryQuery & { page: number; page_size: number } {
  const q = text(query.q);
  const status = statuses.find(value => value === query.status);
  const sourceCode = text(query.source_code);
  const countryCode = text(query.country_code);
  const ownerId = text(query.owner_employee_id);
  const ownerValid = /^[\da-f]{8}-[\da-f]{4}-[\da-f]{4}-[\da-f]{4}-[\da-f]{12}$/i.test(ownerId);
  const assignment =
    query.assignment_status === 'ASSIGNED' || query.assignment_status === 'UNASSIGNED'
      ? query.assignment_status
      : undefined;
  const sla = inquirySlaOptions.find(item => item.value === query.sla_state)?.value;
  const product = text(query.product_q);
  const receivedFrom = timestamp(query.received_from);
  const receivedTo = timestamp(query.received_to);
  const quoted = query.has_quotation === 'true' || query.has_quotation === 'false' ? query.has_quotation : undefined;
  const priority = priorities.find(value => value === query.priority);
  const amount = text(query.amount_min);
  const currency = text(query.amount_currency);
  const validAmount = /^\d{1,32}(?:\.\d{1,8})?$/.test(amount) && /^[A-Z]{3}$/.test(currency);
  const pageSize = positiveInteger(query.page_size, 50);
  return {
    ...(q ? { q } : {}),
    ...(status ? { status } : {}),
    ...(sourceCode ? { source_code: sourceCode } : {}),
    ...(countryCode ? { country_code: countryCode } : {}),
    ...(ownerValid ? { owner_employee_id: ownerId } : {}),
    ...(assignment ? { assignment_status: assignment } : {}),
    ...(sla ? { sla_state: sla } : {}),
    ...(product ? { product_q: product } : {}),
    ...(receivedFrom ? { received_from: receivedFrom } : {}),
    ...(receivedTo ? { received_to: receivedTo } : {}),
    ...(quoted ? { has_quotation: quoted } : {}),
    ...(priority ? { priority } : {}),
    ...(validAmount ? { amount_min: amount, amount_currency: currency } : {}),
    page: positiveInteger(query.page, 1),
    page_size: inquiryPageSizes.includes(pageSize) ? pageSize : 50,
    ordering: orderings.find(value => value === query.ordering) ?? '-received_at'
  };
}

export function inquiryRouteQuery(query: InquiryQuery): Record<string, string> {
  return Object.fromEntries(
    Object.entries(normalizeInquiryQuery({ ...query })).map(([key, value]) => [key, String(value)])
  );
}

export function parseInquiryAmountFilter(value: string): Pick<InquiryQuery, 'amount_min' | 'amount_currency'> {
  const textValue = value
    .trim()
    .replaceAll(',', '')
    .replace(/\s*以上$/, '');
  if (!textValue) return {};
  const match = /^([A-Za-z]{3})\s+(\d{1,32}(?:\.\d{1,8})?)$/.exec(textValue);
  if (!match) throw new Error('请输入币种和非负金额，例如 USD 10000。');
  return { amount_currency: match[1].toUpperCase(), amount_min: match[2] };
}

export function inquiryDateRangeQuery(
  range: [string, string] | null
): Pick<InquiryQuery, 'received_from' | 'received_to'> {
  if (!range) return {};
  if (!range.every(isCalendarDate) || range[0] > range[1]) throw new Error('请选择有效的开始和结束日期。');
  return { received_from: `${range[0]}T00:00:00+08:00`, received_to: `${range[1]}T23:59:59.999999+08:00` };
}

export function formatInquiryReceived(value: string): { date: string; time: string } {
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return { date: '—', time: '' };
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
  return { date: `${part('year')}-${part('month')}-${part('day')}`, time: `${part('hour')}:${part('minute')}` };
}

export function formatInquiryAmount(summary?: InquiryListItem['product_amount']): string {
  if (!summary?.item_count || (!summary.totals.length && !summary.missing_price_count)) return '—';
  if (summary.missing_price_count > 0) return '待补齐';
  const amounts = summary.totals.map(total => {
    if (!/^[A-Z]{3}$/.test(total.currency_code) || !/^\d+(?:\.\d+)?$/.test(total.amount)) return null;
    // 金额保留十进制字符串，避免 Number 舍入大数与小数。
    const [whole, fraction = ''] = total.amount.split('.');
    return `${total.currency_code} ${whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',')}.${fraction.replace(/0+$/, '').padEnd(2, '0')}`;
  });
  return amounts.some(amount => amount === null) ? '—' : amounts.join(' / ');
}

export function inquirySlaPresentation(sla: Pick<InquiryListItem['sla_summary'], 'state' | 'remaining_seconds'>): {
  label: string;
  reminder: string;
  type: TagType;
} {
  if (sla.state === 'NONE') return { label: '—', reminder: '—', type: 'default' };
  const breached = sla.state === 'BREACHED';
  const due = sla.state === 'DUE_SOON';
  const seconds = sla.remaining_seconds;
  const minutes = typeof seconds === 'number' && Number.isFinite(seconds) ? Math.ceil(Math.abs(seconds) / 60) : null;
  let duration = '';
  if (minutes !== null) {
    if (minutes >= 1440) duration = `${Math.floor(minutes / 1440)}天${Math.floor((minutes % 1440) / 60)}小时`;
    else if (minutes >= 60) duration = `${Math.floor(minutes / 60)}小时${minutes % 60}分`;
    else duration = `${minutes}分钟`;
  }
  const reminder = breached ? '已超时' : due ? '即将超时' : '正常';
  return {
    label: duration ? `${breached ? '超时' : '剩余'} ${duration}` : reminder,
    reminder,
    type: breached ? 'error' : due ? 'warning' : 'success'
  };
}

export function inquiryStatusType(status: InquiryStatus): TagType {
  if (['QUOTE_ACCEPTED', 'CONVERTED'].includes(status)) return 'success';
  if (['LOST', 'CANCELLED'].includes(status)) return 'error';
  if (['NEW', 'DRAFT', 'READY_FOR_QUOTE'].includes(status)) return 'warning';
  if (['ANALYZING', 'QUOTING', 'QUOTED', 'FOLLOW_UP'].includes(status)) return 'info';
  return 'default';
}

export function inquiryHandlingStage(stage: string): string {
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
