import { apiClient } from './request'
import type { InternalReceiptResult, MetalReceiptPayload, MetalReceiptPreview, ReceiptPayload, ReceiptPreview, SemiReceiptRecord } from '@/types/internalReceipt'
const root = '/api/v1/semi-finished-receipts/'
export async function fetchReceiptPreview(scheduleProductId: string, category: string) {
  const response = await apiClient.get<{ data: ReceiptPreview }>(`${root}preview/`, {
    params: { schedule_product_id: scheduleProductId, plan_category: category }, timeout: 15000,
  })
  return response.data.data
}
export async function confirmInternalReceipt(payload: ReceiptPayload | MetalReceiptPayload, etag: string) {
  const response = await apiClient.post<{ data: { receipt_id: string; record_ids: string[]; receipt_number: string; replayed: boolean } }>(root, payload,
    { headers: { 'If-Match': etag }, timeout: 30000 })
  return response.data.data
}
export async function fetchSemiReceiptRecords(params: Record<string, unknown>) {
  const response = await apiClient.get<{ data: { items: SemiReceiptRecord[]; total: number } }>(root, { params, timeout: 15000 })
  return response.data.data
}
export async function fetchSemiReceiptRecord(id: string) {
  const response = await apiClient.get<{ data: SemiReceiptRecord }>(`${root}${id}/`, { timeout: 15000 })
  return response.data.data
}

export async function fetchMetalReceiptPreview(scheduleProductId: string) {
  const response = await apiClient.get<{ data: MetalReceiptPreview }>(`${root}preview/`, {
    params: { schedule_product_id: scheduleProductId, plan_category: 'METAL' }, timeout: 15000,
  })
  return response.data.data
}

export async function findInternalReceipt(requestId: string) {
  const response = await apiClient.get<{ data: InternalReceiptResult }>(`${root}by-request/${encodeURIComponent(requestId)}/`, { timeout: 15000 })
  return response.data.data
}
