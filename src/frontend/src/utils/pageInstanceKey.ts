const customerReadRoutes = new Set([
  'customer-detail', 'customer-contacts', 'customer-timeline', 'customer-tasks',
  'customer-inquiries', 'customer-quotations', 'customer-samples', 'customer-orders', 'customer-complaints',
])

export function pageInstanceKey(
  route: { name?: unknown; path: string; fullPath: string; params: Record<string, unknown> },
  userId?: string | number,
): string {
  const name = String(route.name || '')
  const customerId = route.params.customerId
  if (customerReadRoutes.has(name) && typeof customerId === 'string' && customerId) {
    return `${userId || ''}:customer-read:${customerId}`
  }
  // 权限页自行消费员工定位参数，清除参数时保留已定位的页码和分配窗口。
  return `${userId || ''}:${name === 'inquiries' || name === 'access-management' ? route.path : route.fullPath}`
}
