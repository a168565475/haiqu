import type {
  CustomerContact,
  CustomerSummary,
  CustomerTask,
  CustomerTimelineEvent
} from '../../typings/customer-detail';

export type OverviewTone = 'default' | 'success' | 'info' | 'warning' | 'error';

export function formatOverviewMoney(value: string | number | null | undefined, currency: string): string {
  if (value === null || value === undefined || !/^[A-Z]{3}$/.test(currency)) return '—';
  const text = String(value);
  if (!/^-?\d+(\.\d+)?$/.test(text)) return '—';
  const [whole = '', fraction] = text.split('.');
  return `${currency} ${whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',')}${fraction ? `.${fraction}` : ''}`;
}

export function calculateCreditUsage(
  rawLimit: string | number | null | undefined,
  rawUsed: string | number | null | undefined
): number | null {
  if (
    rawLimit === null ||
    rawLimit === undefined ||
    rawLimit === '' ||
    rawUsed === null ||
    rawUsed === undefined ||
    rawUsed === ''
  )
    return null;
  const limit = Number(rawLimit);
  const used = Number(rawUsed);
  if (!Number.isFinite(limit) || !Number.isFinite(used) || limit <= 0 || used < 0) return null;
  const ratio = Math.round((used / limit) * 100);
  return Number.isFinite(ratio) ? ratio : null;
}

export function previewContacts(contacts: CustomerContact[]) {
  const primary =
    contacts.find(item => item.is_primary_contact) || contacts.find(item => item.is_key_contact) || contacts[0] || null;
  return { primary, others: contacts.filter(item => item.id !== primary?.id).slice(0, 2) };
}

export function contactMethod(contact: CustomerContact | null, types: string[]): string {
  const methods = contact?.methods.filter(item => types.includes(item.method_type)) || [];
  const method = methods.find(item => item.is_primary) || methods[0];
  // display_value 已按服务端权限处理；只回退 masked_value，不读取潜在原始字段。
  return method?.display_value || method?.masked_value || '—';
}

export function previewTasks(tasks: CustomerTask[]): CustomerTask[] {
  const deadline = (value: string | null) => {
    const time = Date.parse(value || '');
    return Number.isFinite(time) ? time : Infinity;
  };
  return tasks
    .filter(task => ['PENDING', 'IN_PROGRESS'].includes(task.status))
    .sort((left, right) => deadline(left.due_at) - deadline(right.due_at))
    .slice(0, 3);
}

export function timelineCategory(event: Pick<CustomerTimelineEvent, 'source_type' | 'event_type'>): {
  label: string;
  tone: OverviewTone;
} {
  const key = `${event.source_type} ${event.event_type}`.toUpperCase();
  if (key.includes('COMMUNICATION')) return { label: '沟通', tone: 'warning' };
  if (key.includes('QUOTATION')) return { label: '报价', tone: 'success' };
  if (key.includes('SAMPLE')) return { label: '样品', tone: 'info' };
  if (key.includes('TASK')) return { label: '任务', tone: 'info' };
  if (key.includes('INQUIRY')) return { label: '询盘', tone: 'warning' };
  if (key.includes('CONTACT')) return { label: '联系人', tone: 'default' };
  return { label: '系统', tone: 'default' };
}

export function buildCustomerHealthSummary(
  summary: CustomerSummary | null,
  creditUsage: number | null,
  latestInteractionAt?: string | null
): { label: string; tone: OverviewTone; facts: { label: string; meta: string; tone: OverviewTone }[] } {
  const complaints = summary?.counts.open_complaints;
  const overdue = summary?.counts.overdue_tasks;
  const known =
    typeof complaints === 'number' &&
    Number.isInteger(complaints) &&
    complaints >= 0 &&
    typeof overdue === 'number' &&
    Number.isInteger(overdue) &&
    overdue >= 0;
  const risks = known ? complaints + overdue : null;
  const facts: { label: string; meta: string; tone: OverviewTone }[] = [
    {
      label: creditUsage === null ? '信用使用率待确认' : `信用额度使用 ${creditUsage}%`,
      meta: '来自客户业务快照，不代表授信审批',
      tone: creditUsage !== null && creditUsage > 100 ? 'warning' : 'default'
    },
    { label: '应收逾期数据未接入', meta: '—', tone: 'default' },
    {
      label: latestInteractionAt ? '已有最近互动记录' : '暂无最近互动记录',
      meta: latestInteractionAt || '—',
      tone: latestInteractionAt ? 'info' : 'default'
    },
    {
      label:
        risks === null ? '客诉与逾期任务汇总待确认' : risks > 0 ? `待处理风险 ${risks} 项` : '暂无开放客诉或逾期任务',
      meta: risks === null ? '汇总未加载或加载失败' : `开放客诉 ${complaints} · 逾期任务 ${overdue}`,
      tone: risks === null ? 'default' : risks > 0 ? 'warning' : 'success'
    }
  ];
  if ((risks !== null && risks > 0) || (creditUsage !== null && creditUsage > 100))
    return { label: '需关注', tone: 'warning', facts };
  if (risks === null) return { label: '汇总待确认', tone: 'default', facts };
  return { label: '暂无待处理风险', tone: 'success', facts };
}
