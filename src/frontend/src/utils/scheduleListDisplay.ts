import type { ScheduleProduct } from '@/types/productionScheduling'
import type { ScheduleOutsourcingStatus, ScheduleProductStageProgress } from '@/types/workshopReporting'

export const scheduleRiskColors = {
  normal: '#22a06b', attention: '#d6a600', slow: '#f08b24', urgent: '#e04b4b', unknown: '#94a3b8',
}
export type ScheduleRiskLevel = keyof typeof scheduleRiskColors
export const scheduleRiskRank: Record<ScheduleRiskLevel, number> = { unknown: -1, normal: 0, attention: 1, slow: 2, urgent: 3 }

export function scheduleOutsourcingIndicator(status?: ScheduleOutsourcingStatus) {
  const state = status?.state || 'UNKNOWN'
  const color = state === 'NONE' ? '#72a7d1' : scheduleRiskColors[status?.risk === 'none' ? 'unknown' : status?.risk || 'unknown']
  const symbol = state === 'NONE' ? '' : state === 'RETURNED' ? '✓' : status?.risk === 'urgent' ? '!'
    : state === 'SHORTAGE' ? '缺' : state === 'WAITING' ? '待' : state === 'UNKNOWN' ? '?' : '外'
  return { state, color, symbol, description: status?.description || '外发信息暂不可用', records: status?.records || [] }
}

export function scheduleProductSummary(products: ScheduleProduct[]) {
  if (!products.length) return '0 项产品'
  const quantities = new Map<string, { name: string; quantity: number }>()
  for (const product of products) {
    const quantity = Number(product.planned_quantity)
    if (!Number.isFinite(quantity) || quantity < 0 || !product.unit_name) return `${products.length} 项产品 · 数量待补全`
    const key = product.unit_id || product.unit_name
    const current = quantities.get(key) || { name: product.unit_name, quantity: 0 }
    current.quantity += quantity
    quantities.set(key, current)
  }
  return `${products.length} 项产品 · 共 ${[...quantities.values()].map(item => `${item.quantity.toLocaleString('zh-CN')} ${item.name}`).join('、')}`
}

function dateNumber(value: string | null | undefined) {
  if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return null
  const timestamp = Date.parse(`${value}T00:00:00Z`)
  return Number.isFinite(timestamp) && new Date(timestamp).toISOString().slice(0, 10) === value ? timestamp : null
}

export function scheduleStageRisk(product: ScheduleProductStageProgress | undefined, asOfDate?: string): { level: ScheduleRiskLevel; description: string } {
  if (!product || product.status !== 'READY' || product.percentage === null || !Number.isFinite(product.percentage)) {
    return { level: 'unknown', description: product?.status === 'NOT_APPLICABLE' ? '该环节暂无适用工序' : '进度数据暂不可用' }
  }
  if (product.percentage === 100) return { level: 'normal', description: '已完成' }
  const planned = dateNumber(product.planned_date)
  const today = dateNumber(asOfDate)
  if (planned === null || today === null) return { level: 'unknown', description: '计划日期暂不可用' }
  // 采用服务端业务日期，按自然日比较，避免浏览器时区导致预警提前或延后。
  const days = Math.round((planned - today) / 86_400_000)
  const description = days < 0 ? `已逾期 ${-days} 天` : days === 0 ? '计划今日完成' : `距计划日期 ${days} 天`
  let level: ScheduleRiskLevel = 'normal'
  if (days < 0 || (days <= 1 && product.percentage < 90)) level = 'urgent'
  else if (days <= 3 && product.percentage < 70) level = 'slow'
  else if (days <= 7 && product.percentage < 40) level = 'attention'
  return { level, description: `${description} · 当前 ${product.percentage}%` }
}
