import type { FinishedReceiptOptions, FinishedReceiptPreview, PendingFinishedReceipt } from '@/types/finishedReceipts'
import { validProductionDate } from '@/utils/reporting'

export const receiptUuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
export function positiveReceiptQuantity(value: string): number | null {
  if (!/^\d+$/.test(value)) return null
  const number = Number(value)
  return Number.isSafeInteger(number) && number > 0 ? number : null
}
export function formatReceiptQuantity(value: string, previous: string): string {
  return /^\d*$/.test(value) ? value : previous
}
export function receiptBlocker(preview: FinishedReceiptPreview): string {
  if (!preview.reporting_basis_ready) return '装配工序或有效工价明细未完整设置，请先完善报工依据。'
  if (preview.reported_minimum === 0) return '装配工序尚未全部报工，当前可入库为 0。'
  if (preview.remaining_receivable === 0) return '当前可入库额度已用完，请核对已有入库单和装配报工进度。'
  return ''
}
export function validateFinishedReceipt(
  preview: FinishedReceiptPreview, options: FinishedReceiptOptions,
  values: { quantity: string; perBox: string; date: string; locationId: string },
): string {
  const blocked = receiptBlocker(preview)
  if (blocked) return blocked
  const quantity = positiveReceiptQuantity(values.quantity)
  if (quantity === null) return '入库数量必须为正整数，且不能超过安全整数范围。'
  if (quantity > preview.remaining_receivable) return `剩余可入库 ${preview.remaining_receivable} ${preview.unit_name}，不能超量。`
  if (!validProductionDate(values.date)) return '请选择有效的收货日期。'
  const location = options.locations.find(item => item.id === values.locationId && item.status === 'ACTIVE')
  const zone = options.zones.find(item => item.id === location?.zone && item.warehouse === location?.warehouse_id && item.status === 'ACTIVE')
  const warehouse = options.warehouses.find(item => item.id === location?.warehouse_id && item.status === 'ACTIVE' && item.warehouse_type === 'FINISHED')
  if (!location || !zone || !warehouse) return '请选择有效的成品仓、库区和库位。'
  const pack = values.perBox === '' ? null : positiveReceiptQuantity(values.perBox)
  if (values.perBox !== '' && pack === null) return '每箱数量必须为正整数，或留空。'
  if (pack !== null && location.remaining_box_slots !== null && Math.ceil(quantity / pack) > location.remaining_box_slots) {
    return `库位剩余 ${location.remaining_box_slots} 箱位，本次需要 ${Math.ceil(quantity / pack)} 箱位。`
  }
  return ''
}
export function parsePendingFinishedReceipt(raw: string, planId: string): PendingFinishedReceipt {
  let value: Partial<PendingFinishedReceipt> | null
  try { value = JSON.parse(raw) as Partial<PendingFinishedReceipt> | null }
  catch { throw new Error('原提交记录无法读取，已保留并暂停提交，请联系管理员核对。') }
  const payload = value?.payload
  if (!value || typeof value.etag !== 'string' || !value.etag || !payload
    || typeof payload.request_id !== 'string' || !receiptUuid.test(payload.request_id)
    || payload.schedule_product_id !== planId || typeof payload.location_id !== 'string' || !receiptUuid.test(payload.location_id)
    || typeof payload.receipt_date !== 'string' || !validProductionDate(payload.receipt_date)
    || !Number.isSafeInteger(payload.received_quantity) || payload.received_quantity <= 0
    || !(payload.quantity_per_box === null || Number.isSafeInteger(payload.quantity_per_box) && payload.quantity_per_box > 0)
    || typeof payload.actual_color !== 'string' || payload.actual_color.length > 200
    || typeof payload.remark !== 'string' || payload.remark.length > 3000) {
    throw new Error('原提交记录无法读取，已保留并暂停提交，请联系管理员核对。')
  }
  return value as PendingFinishedReceipt
}
export function receiptFailureIsDefinitive(error: unknown): boolean {
  const response = (error as { response?: { status?: number; data?: { error?: { code?: string } } } })?.response
  return [400, 412, 428].includes(response?.status ?? 0)
    || response?.status === 409 && ['CONFLICT', 'RECEIPT_REQUEST_DELETED'].includes(response.data?.error?.code ?? '')
}
