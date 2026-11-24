export function formatMoney(value: string | null): string {
  if (!value || !/^-?\d+(\.\d+)?$/.test(value)) return '—';
  const [integer, fraction = '00'] = value.split('.');
  return `CNY ${integer.replace(/\B(?=(\d{3})+(?!\d))/g, ',')}.${fraction.padEnd(2, '0')}`;
}

export function formatDate(value: string | null): string {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '—';
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return value;
  return [
    date.getFullYear(),
    String(date.getMonth() + 1).padStart(2, '0'),
    String(date.getDate()).padStart(2, '0')
  ].join('-');
}

export function getFollowUpStatus(
  value: string | null,
  now = new Date()
): { label: string; type: 'default' | 'error' | 'warning' } {
  if (!value) return { label: '未安排', type: 'default' };
  const target = new Date(value);
  if (Number.isNaN(target.getTime())) return { label: '未安排', type: 'default' };
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const day = new Date(target.getFullYear(), target.getMonth(), target.getDate()).getTime();
  if (day < today) return { label: '已逾期', type: 'error' };
  return { label: day === today ? '今日跟进' : '待跟进', type: 'warning' };
}
