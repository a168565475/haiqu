import { apiClient } from '@/utils/request'
import type { SemiReceiptCategory, SemiReceiptPayload, SemiReceiptPreview, SemiReceiptResult } from '@/types/semiReceipts'
import { semiPreviewWhole, semiReceiptUuid } from '@/utils/semiReceipts'
import { validProductionDate } from '@/utils/reporting'

const base = '/api/v1/semi-finished-receipts/'
export async function fetchSemiReceiptPreview(planId: string, category: SemiReceiptCategory, signal?: AbortSignal): Promise<SemiReceiptPreview> {
  const { data } = await apiClient.get<{ data: SemiReceiptPreview }>(`${base}preview/`, { params: { schedule_product_id: planId, plan_category: category }, signal, timeout: 15000 })
  const preview = data.data
  if (!preview || preview.schedule_product_id !== planId || preview.plan_category !== category
    || typeof preview.etag !== 'string' || !preview.etag || !validProductionDate(preview.receipt_date)
    || !Array.isArray(preview.excluded) || !preview.excluded.every(item => typeof item === 'string')
    || !Array.isArray(preview.zones) || !preview.zones.every(zone => zone && semiReceiptUuid.test(zone.id) && typeof zone.warehouse === 'string' && typeof zone.name === 'string')
    || !Array.isArray(preview.lines) || !preview.lines.every(line => line && semiReceiptUuid.test(line.bom_line_id) && line.attributes
      && line.attributes.unit_name === (category === 'METAL' ? '支' : '套') && semiPreviewWhole(line.can_receive) !== null && typeof line.received === 'string')
    || new Set(preview.lines.map(line => line.bom_line_id)).size !== preview.lines.length) throw new Error('半成品入库预览不完整或来源已变化，请刷新核对。')
  if (category === 'METAL' && (!preview.metal_processing || !Array.isArray(preview.metal_processing.blockers) || !Array.isArray(preview.metal_processing.future_blockers)
    || preview.lines.some(line => !line.metal_processing || typeof line.metal_processing.basis_ready !== 'boolean' || !Array.isArray(line.metal_processing.blockers)
      || !Array.isArray(line.metal_processing.future_blockers) || !Array.isArray(line.metal_processing.operations) || !Array.isArray(line.metal_processing.schemes)))) {
    throw new Error('当前环境缺少新版金工加工数量依据，暂不可办理，请联系管理员核对。')
  }
  return preview
}
function receiptResult(value: SemiReceiptResult | undefined): SemiReceiptResult {
  if (typeof value?.receipt_id !== 'string' || !semiReceiptUuid.test(value.receipt_id) || typeof value.receipt_number !== 'string' || !value.receipt_number || !Array.isArray(value.record_ids)
    || !value.record_ids.every(id => typeof id === 'string' && semiReceiptUuid.test(id))
    || !['PENDING', 'CONFIRMED'].includes(value.status) || typeof value.replayed !== 'boolean') throw new Error('未收到完整半成品入库结果，请使用原编号核对。')
  return value
}
export async function createSemiReceipt(payload: SemiReceiptPayload, etag: string): Promise<SemiReceiptResult> {
  const { data } = await apiClient.post<{ data: SemiReceiptResult }>(base, payload, { headers: { 'If-Match': etag }, timeout: 30000 })
  return receiptResult(data.data)
}
export async function findSemiReceipt(requestId: string): Promise<SemiReceiptResult> {
  const { data } = await apiClient.get<{ data: SemiReceiptResult }>(`${base}by-request/${encodeURIComponent(requestId)}/`, { timeout: 15000 })
  return receiptResult(data.data)
}
