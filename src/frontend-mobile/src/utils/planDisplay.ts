import type { MobilePlan } from '@/types/mobilePlan'

export function displayQuantity(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === '') return '—'
  return String(value).replace(/(\.\d*?[1-9])0+$/, '$1').replace(/\.0+$/, '')
}
export function planQuery(plan: MobilePlan): Record<string, string> {
  return {
    schedule_product_id: plan.schedule_product_id,
    production_task_id: plan.production_task_id,
    product_line_id: plan.product_line_id,
    plan_category: plan.plan_category,
    workshop_id: plan.workshop.id,
  }
}
export function progressLabel(plan: MobilePlan): string {
  if (!plan.progress) return '进度不可查看'
  if (plan.progress.percentage !== null) return `${displayQuantity(plan.progress.percentage)}%`
  return plan.progress.status === 'NOT_CONFIGURED' ? '待配置工序' : '暂无进度'
}
