import type { CustomerListQuery, CustomerOrdering, CustomerActivityStatus } from '@/typings/customer';

export const customerTabs = [
  'overview',
  'contacts',
  'timeline',
  'tasks',
  'inquiries',
  'quotations',
  'samples',
  'orders',
  'complaints'
] as const;
export type CustomerTab = (typeof customerTabs)[number];

export function customerTab(value: unknown): CustomerTab {
  return typeof value === 'string' && customerTabs.includes(value as CustomerTab) ? (value as CustomerTab) : 'overview';
}

export function customerListReturnPath(value: unknown): string {
  if (typeof value !== 'string' || !value.startsWith('/customers') || /[\\\u0000-\u001f]/.test(value))
    return '/customers';
  try {
    const url = new URL(value, 'http://local.invalid');
    if (url.origin !== 'http://local.invalid' || url.pathname !== '/customers') return '/customers';
    if (/[\\\u0000-\u001f]/.test(decodeURIComponent(value))) return '/customers';
    return url.pathname + url.search + url.hash;
  } catch {
    return '/customers';
  }
}

export function customerListQuery(values: Record<string, unknown>): CustomerListQuery {
  const page = typeof values.page === 'string' && /^\d+$/.test(values.page) ? Number(values.page) : 1;
  const pageSize = typeof values.page_size === 'string' ? Number(values.page_size) : 10;
  const orders: CustomerOrdering[] = ['account_name', '-account_name', '-updated_at'];
  const states: CustomerActivityStatus[] = ['INSUFFICIENT_DATA', 'ACTIVE', 'FOLLOW_UP', 'HIGH_RISK', 'DORMANT'];
  const result: CustomerListQuery = {
    page: Number.isSafeInteger(page) && page > 0 ? page : 1,
    page_size: [10, 20, 50, 100].includes(pageSize) ? pageSize : 10,
    ordering: orders.includes(values.ordering as CustomerOrdering)
      ? (values.ordering as CustomerOrdering)
      : '-updated_at'
  };
  for (const key of ['q', 'country_code', 'customer_grade'] as const) {
    if (typeof values[key] === 'string' && values[key].trim()) result[key] = values[key].trim();
  }
  if (states.includes(values.activity_status as CustomerActivityStatus))
    result.activity_status = values.activity_status as CustomerActivityStatus;
  return result;
}

export function customerListRouteQuery(query: CustomerListQuery): Record<string, string> {
  return Object.fromEntries(
    Object.entries(query)
      .filter(([, value]) => value !== undefined && value !== '')
      .map(([key, value]) => [key, String(value)])
  );
}
