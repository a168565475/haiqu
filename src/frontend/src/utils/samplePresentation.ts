import type { SampleListItem, SampleListQuery } from '@/types/sample'
import type { SavedView } from '@/types/savedView'

export const sampleSortOptions = [
  { value: '-requested_at', label: '申请时间：从新到旧' },
  { value: 'requested_at', label: '申请时间：从旧到新' },
  { value: 'requested_due_at', label: '期望完成：从早到晚' },
  { value: '-requested_due_at', label: '期望完成：从晚到早' },
  { value: '-updated_at', label: '最近更新优先' },
] as const

export function sampleStatusTone(status: string): 'success' | 'warning' | 'danger' | 'info' | 'neutral' {
  if (['REJECTED', 'APPLICATION_RETURNED'].includes(status)) return 'danger'
  if (['FINISHED', 'MATERIALS_READY', 'CONFIRMED', 'COMPLETED'].includes(status)) return 'success'
  if (['DRAFT', 'CANCELLED'].includes(status)) return 'neutral'
  if (['SHIPPED', 'DELIVERED'].includes(status)) return 'info'
  if (['DIRECTOR_REVIEW', 'MATERIALS_PENDING', 'WAREHOUSE_PENDING', 'PROCUREMENT_PENDING', 'MATERIAL_ISSUE_PENDING', 'MATERIAL_ISSUE_REVIEW', 'PENDING_COMPLETION', 'PENDING', 'PMC_REVIEW', 'METALWORK_PENDING', 'CUTTING_PENDING', 'PRODUCTION_PENDING', 'PREPARING', 'FEEDBACK_PENDING'].includes(status)) return 'warning'
  return 'neutral'
}

export function sampleProductsLabel(row: SampleListItem): string {
  const products = row.products || []
  return products.map(product => product.product_name || '—').join('、') || row.item_summary?.text || '—'
}

function splitLegacyColor(specification: string): { specification: string; color: string } {
  const value = specification.trim()
  const match = value.match(/^(.*?)(?:[;；]\s*)?颜色\s*[:：]\s*(.+)$/u)
  if (!match) return { specification: value, color: '' }
  return {
    specification: (match[1] || '').replace(/[;；]\s*$/u, '').trim(),
    color: (match[2] || '').trim(),
  }
}

export function sampleProductFieldLabel(row: SampleListItem, field: 'specification' | 'category_name' | 'color'): string {
  const values = (row.products || []).map(product => {
    if (field === 'category_name') return product.category_name || '—'
    const parsed = splitLegacyColor(product.specification || '')
    if (field === 'color') return product.color?.trim() || parsed.color || '—'
    return parsed.specification || '—'
  })
  return values.join('；') || '—'
}

export function sampleQuantityLabel(row: SampleListItem): string {
  const products = row.products || []
  if (!products.length || products.some(product => !Number.isFinite(product.total_sample_quantity))) return '—'
  return `${products.reduce((sum, product) => sum + product.total_sample_quantity, 0)} PCS`
}

// 保存视图使用 API 查询字段；兼容旧版曾保存的 q，避免保存后恢复丢失搜索条件。
export function sampleSavedQuery(view: SavedView): Partial<SampleListQuery> {
  const data = view.filter_definition
  const text = (key: string) => typeof data[key] === 'string' ? data[key] as string : ''
  const savedOrder = text('ordering') || view.sort_definition?.[0]
  return {
    search: text('search') || text('q'),
    status: text('status'), sample_type: text('sample_type'),
    owner_employee_id: text('owner_employee_id'), tracking_number: text('tracking_number'),
    requested_from: text('requested_from'), requested_to: text('requested_to'),
    ordering: sampleSortOptions.some(option => option.value === savedOrder) ? savedOrder : '-requested_at',
  }
}

// 使用所选本地日期的完整自然日，不用 UTC 日期字符串截断而漏掉当天记录。
export function sampleDateBounds(range: [Date, Date] | null): Pick<SampleListQuery, 'requested_from' | 'requested_to'> {
  if (!range || range.some(date => !(date instanceof Date) || !Number.isFinite(date.getTime()))) return {}
  const start = new Date(range[0])
  const end = new Date(range[1])
  start.setHours(0, 0, 0, 0)
  end.setHours(23, 59, 59, 999)
  if (start > end) return {}
  return { requested_from: start.toISOString(), requested_to: end.toISOString() }
}
