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
  return `${userId || ''}:${name === 'inquiries' ? route.path : route.fullPath}`
}
