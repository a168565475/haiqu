import { apiClient } from '@/utils/request'
import type { FinishedReceiptOptions, FinishedReceiptPayload, FinishedReceiptPreview, FinishedReceiptResult } from '@/types/finishedReceipts'
import { validProductionDate } from '@/utils/reporting'

const base = '/api/v1/assembly-finished-receipts/'
export async function fetchFinishedReceiptPreview(planId: string, signal?: AbortSignal): Promise<FinishedReceiptPreview> {
  const { data } = await apiClient.get<{ data: FinishedReceiptPreview }>(`${base}preview/`, { params: { schedule_product_id: planId }, signal })
  const preview = data.data
  const amounts = preview && [preview.order_quantity, preview.maximum_receivable, preview.received_total, preview.remaining_receivable, preview.order_maximum, preview.reported_minimum]
  if (!preview || preview.schedule_product_id !== planId || typeof preview.etag !== 'string' || !preview.etag
    || !amounts?.every(value => Number.isSafeInteger(value) && value >= 0)
    || !validProductionDate(preview.receipt_date) || typeof preview.actual_color !== 'string'
    || typeof preview.unit_name !== 'string' || !preview.unit_name || typeof preview.reporting_basis_ready !== 'boolean'
    || !Array.isArray(preview.reporting_operations)) throw new Error('入库预览不完整，请重新读取并核对。')
  return preview
}
export async function fetchFinishedReceiptOptions(planId: string, signal?: AbortSignal): Promise<FinishedReceiptOptions> {
  const { data } = await apiClient.get<{ data: FinishedReceiptOptions }>('/api/v1/workshop-mobile/finished-receipt-options/', { params: { schedule_product_id: planId }, signal })
  const options = data.data
  if (!options || !Array.isArray(options.warehouses) || !Array.isArray(options.zones) || !Array.isArray(options.locations)
    || !options.warehouses.every(item => item.id && typeof item.warehouse_type === 'string' && typeof item.status === 'string')
    || !options.zones.every(item => item.id && item.warehouse && typeof item.status === 'string')
    || !options.locations.every(item => item.id && item.zone && item.warehouse_id && typeof item.status === 'string'
      && (item.remaining_box_slots === null || Number.isSafeInteger(item.remaining_box_slots) && item.remaining_box_slots >= 0))) {
    throw new Error('成品库位选项不完整，请重新加载。')
  }
  return options
}
export async function createFinishedReceipt(payload: FinishedReceiptPayload, etag: string): Promise<FinishedReceiptResult> {
  const { data } = await apiClient.post<{ data: FinishedReceiptResult }>(base, payload, { headers: { 'If-Match': etag }, timeout: 30000 })
  const result = data.data
  if (!result?.id || typeof result.receipt_number !== 'string' || !result.receipt_number
    || !['PENDING', 'CONFIRMED'].includes(result.status) || typeof result.replayed !== 'boolean') {
    throw new Error('未收到完整入库结果，请使用原编号核对本次提交。')
  }
  return result
}
