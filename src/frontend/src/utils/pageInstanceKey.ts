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
  // 这些页面自行处理查询参数，地址变化时保留筛选、页码或分配窗口。
  return `${userId || ''}:${name === 'inquiries' || name === 'access-management' || name === 'employee-list' || name === 'complaints' || name === 'finished-goods-inventory' ? route.path : route.fullPath}`
}
