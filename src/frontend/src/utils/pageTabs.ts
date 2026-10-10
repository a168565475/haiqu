export const MAX_PAGE_TABS = 5

export interface PageTab {
  id: string
  title: string
  fullPath: string
  // 工作台没有手动关闭按钮，但仍参与超出上限后的先开先移除。
  pinned?: boolean
}

export interface PageTabRoute {
  name?: unknown
  path: string
  fullPath: string
  params: Record<string, unknown>
  query?: Record<string, unknown>
  meta?: {
    layout?: unknown
    headerTitle?: unknown
    breadcrumbs?: ReadonlyArray<{ label: string }>
  }
}

const customerReadRoutes = new Set([
  'customer-detail', 'customer-contacts', 'customer-timeline', 'customer-tasks',
  'customer-inquiries', 'customer-quotations', 'customer-samples', 'customer-orders', 'customer-complaints',
])

// 这些参数决定新建来源、业务对象或编辑模式。列表的分页、筛选和内部切换不增加页签。
const businessQueryKeys: Record<string, readonly string[]> = {
  'inquiry-create': ['customer_id'],
  'sales-order-create': ['source', 'quotationVersionId'],
  'bom-create': ['method', 'production_task_product_id'],
  'production-task-create': ['sales_order_id', 'delivery_batch_id'],
  'sample-new': ['editApplication', 'sourceType', 'sourceId', 'customer_id'],
  'purchase-order-create-details': ['source_type', 'source_id', 'bom_id'],
  'assembly-finished-receipt': ['schedule_product_id'],
  'internal-semi-receipt': ['schedule_product_id', 'plan_category'],
  'material-issue-new': ['production_task_id', 'product_line_id', 'schedule_product_id', 'plan_category'],
  'wage-scheme-new': ['schedule_product_id', 'workshop_id', 'craft_id'],
  'work-report-new': ['schedule_product_id', 'workshop_id', 'craft_id'],
  'workshop-outsourcing-new': ['source_issue_line_id', 'schedule_product_id', 'craft_id'],
  'workshop-outsourcing-detail': ['view'],
  'quotation-preview': ['version'],
  suppliers: ['create', 'edit'],
  'wage-schemes': ['detail'],
}

const genericTitles = new Set(['新建', '新增', '编辑', '详情', '查看', '查看明细', '填写明细', '预览', '变更'])

function identityText(value: unknown): string {
  if (typeof value === 'string') return value.trim()
  if (typeof value === 'number' && Number.isFinite(value)) return String(value)
  if (Array.isArray(value)) return JSON.stringify(value.filter(item => typeof item === 'string'))
  return ''
}

function sortedIdentityEntries(values: Record<string, unknown>, keys: readonly string[]): [string, string][] {
  return [...keys].sort().flatMap(key => {
    const value = identityText(values[key])
    return value ? [[key, value] as [string, string]] : []
  })
}

function pageTitle(route: PageTabRoute, name: string, customerRead: boolean): string {
  if (name === 'home') return '工作台'
  const breadcrumbs = route.meta?.breadcrumbs || []
  const finalLabel = breadcrumbs.at(-1)?.label.trim() || ''
  const parentLabel = breadcrumbs.at(-2)?.label.trim() || ''
  const headerLabel = typeof route.meta?.headerTitle === 'string'
    ? route.meta.headerTitle.split('/').at(-1)?.trim() || ''
    : ''
  const title = customerRead ? '客户详情' : genericTitles.has(finalLabel) && parentLabel
    ? `${parentLabel}${finalLabel}`
    : finalLabel || headerLabel || '业务页面'
  return title
}

export function createPageTab(route: PageTabRoute): PageTab | null {
  const name = typeof route.name === 'string' ? route.name : ''
  if (!name || route.meta?.layout !== 'erp' || !route.fullPath.startsWith('/') || route.fullPath.startsWith('//')) return null
  const customerRead = customerReadRoutes.has(name) && !!identityText(route.params.customerId)
  const params = sortedIdentityEntries(route.params, customerRead ? ['customerId'] : Object.keys(route.params))
  const query = sortedIdentityEntries(route.query || {}, businessQueryKeys[name] || [])
  return {
    id: JSON.stringify([customerRead ? 'customer-read' : name, params, query]),
    title: pageTitle(route, name, customerRead),
    fullPath: route.fullPath,
    ...(name === 'home' ? { pinned: true } : {}),
  }
}

export function upsertPageTab(tabs: readonly PageTab[], tab: PageTab): PageTab[] {
  const existingIndex = tabs.findIndex(item => item.id === tab.id)
  const nextTabs = [...tabs]
  if (existingIndex < 0) nextTabs.push(tab)
  else nextTabs[existingIndex] = tab
  return nextTabs.slice(-MAX_PAGE_TABS)
}

export function removePageTab(tabs: readonly PageTab[], id: string): PageTab[] {
  return tabs.filter(tab => tab.id !== id)
}
