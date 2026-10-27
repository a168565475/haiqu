import { apiClient } from './request'
import type { DataResponse } from '@/types/referenceData'
import type { TubeSourceKind } from '@/types/tubeOutsourcing'
import type { TubeReceipt, TubeReceiptCandidates, TubeReceiptInput, TubeReceiptPreview } from '@/types/tubeReceipts'

const root = '/api/v1/tube-outsourcing-orders/'
export async function fetchTubeReceiptCandidates(params: { search?: string; source_kind?: TubeSourceKind; page?: number; page_size?: number; category?: 'cutting' }): Promise<TubeReceiptCandidates> {
  const response = await apiClient.get<DataResponse<TubeReceiptCandidates>>(`${root}receipt-candidates/`, { params, timeout: 15000 })
  return response.data.data
}
export async function fetchTubeReceiptPreview(id: string, warehouse = false): Promise<TubeReceiptPreview> {
  const response = await apiClient.get<DataResponse<TubeReceiptPreview>>(`${root}${encodeURIComponent(id)}/receipt-preview/`, { timeout: 15000, ...(warehouse ? { params: { warehouse_stage: 'all' } } : {}) })
  return response.data.data
}
export async function confirmTubeReceipt(id: string, payload: TubeReceiptInput, etag: string): Promise<TubeReceipt> {
  const response = await apiClient.post<DataResponse<TubeReceipt>>(`${root}${encodeURIComponent(id)}/confirm-receipt/`, payload, { headers: { 'If-Match': etag }, timeout: 30000 })
  return response.data.data
}
export async function findTubeReceipt(id: string, requestId: string, warehouse = false): Promise<TubeReceipt> {
  const response = await apiClient.get<DataResponse<TubeReceipt>>(`${root}${encodeURIComponent(id)}/receipt-by-request/${encodeURIComponent(requestId)}/`, { timeout: 15000, ...(warehouse ? { params: { warehouse_stage: 'all' } } : {}) })
  return response.data.data
}
export async function fetchTubeReceipt(id: string, warehouse = false): Promise<TubeReceipt> {
  const response = await apiClient.get<DataResponse<TubeReceipt>>(`${root}${encodeURIComponent(id)}/receipt/`, { timeout: 15000, ...(warehouse ? { params: { warehouse_stage: 'all' } } : {}) })
  return response.data.data
}
