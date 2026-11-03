import { apiClient } from './request'
import type { DataResponse } from '@/types/referenceData'
import type { TubeCancelInput, TubeDispatchInput, TubeOptions, TubeOrderDetail, TubePendingOrderInput, TubeOrderResult, TubeSourceContext, TubeSourceKind, TubePlanDispatchInput, TubePlanReceiptInput, TubePlanRecordCorrectionInput, TubePlanQuantityInput } from '@/types/tubeOutsourcing'

const path = '/api/v1/tube-outsourcing-orders/'

export async function fetchTubeOptions(category?: 'cutting'): Promise<TubeOptions> {
  const response = await apiClient.get<DataResponse<TubeOptions>>(`${path}options/`, ...(category ? [{ params: { category } }] : []))
  return response.data.data
}
export async function fetchTubeSource(params: {
  schedule_product_id: string; source_kind: TubeSourceKind; zone_id?: string; craft_id?: string; is_plan?: boolean; plan_id?: string
}): Promise<TubeSourceContext> {
  const response = await apiClient.get<DataResponse<TubeSourceContext>>(`${path}source-context/`, { params, timeout: 15000 })
  return response.data.data
}
export async function createTubeOrder(payload: TubePendingOrderInput): Promise<TubeOrderResult> {
  const response = await apiClient.post<DataResponse<TubeOrderResult>>(path, payload, { timeout: 30000 })
  return response.data.data
}
export async function findTubeOrder(requestId: string): Promise<TubeOrderResult> {
  const response = await apiClient.get<DataResponse<TubeOrderResult>>(`${path}by-request/${encodeURIComponent(requestId)}/`, { timeout: 15000 })
  return response.data.data
}
export async function fetchTubeOrder(id: string, warehouse = false): Promise<TubeOrderDetail> {
  const response = await apiClient.get<DataResponse<TubeOrderDetail>>(`${path}${encodeURIComponent(id)}/`, { timeout: 15000, ...(warehouse ? { params: { warehouse_stage: 'all' } } : {}) })
  return response.data.data
}
export async function dispatchTubeOrder(id: string, payload: TubeDispatchInput, etag: string): Promise<TubeOrderDetail> {
  const response = await apiClient.post<DataResponse<TubeOrderDetail>>(`${path}${encodeURIComponent(id)}/dispatch/`, payload, { timeout: 30000, headers: { 'If-Match': etag } })
  return response.data.data
}
export async function cancelTubeOrder(id: string, payload: TubeCancelInput, etag: string): Promise<TubeOrderDetail> {
  const response = await apiClient.post<DataResponse<TubeOrderDetail>>(`${path}${encodeURIComponent(id)}/cancel/`, payload, { timeout: 30000, headers: { 'If-Match': etag } })
  return response.data.data
}
export async function findTubeAction(id: string, requestId: string, warehouse = false): Promise<TubeOrderDetail> {
  const response = await apiClient.get<DataResponse<TubeOrderDetail>>(`${path}${encodeURIComponent(id)}/action-by-request/${encodeURIComponent(requestId)}/`, { timeout: 15000, ...(warehouse ? { params: { warehouse_stage: 'all' } } : {}) })
  return response.data.data
}

export async function dispatchTubePlan(id: string, payload: TubePlanDispatchInput, etag: string): Promise<TubeOrderDetail> {
  const response = await apiClient.post<DataResponse<TubeOrderDetail>>(`${path}${encodeURIComponent(id)}/plan-dispatch/`, payload, { timeout: 30000, headers: { 'If-Match': etag } })
  return response.data.data
}
export async function updateTubePlanQuantity(id: string, payload: TubePlanQuantityInput, etag: string): Promise<TubeOrderDetail> {
  const response = await apiClient.patch<DataResponse<TubeOrderDetail>>(`${path}${encodeURIComponent(id)}/plan-quantity/`, payload, { timeout: 30000, headers: { 'If-Match': etag } })
  return response.data.data
}
export async function receiveTubePlan(id: string, payload: TubePlanReceiptInput, etag: string): Promise<TubeOrderDetail> {
  const response = await apiClient.post<DataResponse<TubeOrderDetail>>(`${path}${encodeURIComponent(id)}/plan-receipt/`, payload, { timeout: 30000, headers: { 'If-Match': etag } })
  return response.data.data
}
export async function correctTubePlanRecord(id: string, payload: TubePlanRecordCorrectionInput, etag: string): Promise<TubeOrderDetail> {
  const response = await apiClient.post<DataResponse<TubeOrderDetail>>(`${path}${encodeURIComponent(id)}/plan-record-correction/`, payload, { timeout: 30000, headers: { 'If-Match': etag } })
  return response.data.data
}
export async function findTubePlanRecordCorrection(id: string, requestId: string, warehouse = false): Promise<TubeOrderDetail> {
  const response = await apiClient.get<DataResponse<TubeOrderDetail>>(`${path}${encodeURIComponent(id)}/plan-record-correction-by-request/${encodeURIComponent(requestId)}/`, { timeout: 15000, ...(warehouse ? { params: { warehouse_stage: 'all' } } : {}) })
  return response.data.data
}
