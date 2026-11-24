import type { ComplaintListItem, ComplaintQuery, ComplaintSlaStatus, ComplaintStatus } from '../../typings/complaint';

export const complaintPageSizes = [20, 50, 100];
const statuses: readonly ComplaintStatus[] = [
  'ACCEPTED',
  'RESPONSIBILITY_CONFIRMATION',
  'SOLUTION_PLANNING',
  'CUSTOMER_CONFIRMATION',
  'CLOSED',
  'CANCELLED'
];
export const complaintSlaOptions: {
  label: string;
  value: ComplaintSlaStatus;
}[] = [
  { label: '正常', value: 'NORMAL' },
  { label: '即将到期', value: 'AT_RISK' },
  { label: '已超时', value: 'OVERDUE' },
  { label: '已结束', value: 'COMPLETED' }
];

function positiveInteger(value: unknown, fallback: number): number {
  if (typeof value !== 'number' && (typeof value !== 'string' || !/^\d+$/.test(value))) return fallback;
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : fallback;
}

function uuid(value: unknown): string | undefined {
  return typeof value === 'string' && /^[\da-f]{8}-[\da-f]{4}-[\da-f]{4}-[\da-f]{4}-[\da-f]{12}$/i.test(value)
    ? value
    : undefined;
}

export function normalizeComplaintQuery(
  query: Readonly<Record<string, unknown>>
): ComplaintQuery & { page: number; page_size: number } {
  const q = typeof query.q === 'string' ? query.q.trim() : '';
  const typeId = uuid(query.complaint_type_item_id);
  const severityId = uuid(query.severity_item_id);
  const ownerId = uuid(query.owner_employee_id);
  const status = statuses.find(value => value === query.status);
  const slaStatus = complaintSlaOptions.find(item => item.value === query.sla_status)?.value;
  const pageSize = positiveInteger(query.page_size, 50);
  return {
    ...(q ? { q } : {}),
    ...(typeId ? { complaint_type_item_id: typeId } : {}),
    ...(severityId ? { severity_item_id: severityId } : {}),
    ...(status ? { status } : {}),
    ...(ownerId ? { owner_employee_id: ownerId } : {}),
    ...(slaStatus ? { sla_status: slaStatus } : {}),
    page: positiveInteger(query.page, 1),
    page_size: complaintPageSizes.includes(pageSize) ? pageSize : 50
  };
}

export function complaintRouteQuery(query: ComplaintQuery): Record<string, string> {
  return Object.fromEntries(
    Object.entries(normalizeComplaintQuery({ ...query })).map(([key, value]) => [key, String(value)])
  );
}

export function formatComplaintDate(value?: string | null): string {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '—';
  const pad = (part: number) => String(part).padStart(2, '0');
  const day = [date.getFullYear(), pad(date.getMonth() + 1), pad(date.getDate())].join('-');
  const time = [date.getHours(), date.getMinutes(), date.getSeconds()].map(pad).join(':');
  return `${day} ${time}`;
}

export function getComplaintSlaText(row: Pick<ComplaintListItem, 'sla_status' | 'target_completion_at'>): string {
  if (row.sla_status === 'COMPLETED') return '已结束';
  const target = formatComplaintDate(row.target_completion_at);
  if (row.sla_status === 'OVERDUE') return `已超时 · ${target}`;
  if (row.sla_status === 'AT_RISK') return `即将到期 · ${target}`;
  return target;
}

export function escapeCsvCell(value: unknown): string {
  const text = String(value ?? '');
  // 引号不能阻止表格软件执行公式；危险开头额外加单引号。
  const safeText = /^[\s\u0000-\u001f]*[=+\-@]/.test(text) || /^[\t\r\n]/.test(text) ? `'${text}` : text;
  return `"${safeText.replaceAll('"', '""')}"`;
}

export function complaintCsv(rows: readonly ComplaintListItem[]): string {
  const headers = ['客诉编号', '客户', '关联订单', '类型', '严重程度', '状态', '负责人', '目标完成', '最近更新'];
  const values = rows.map(row => [
    row.complaint_code,
    row.customer.account_name,
    row.source_order_reference,
    row.complaint_type.display_name,
    row.severity.display_name,
    row.status_label,
    row.owner.display_name,
    row.target_completion_at,
    row.updated_at
  ]);
  return `\ufeff${[headers, ...values].map(cells => cells.map(escapeCsvCell).join(',')).join('\r\n')}`;
}
