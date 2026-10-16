import type { AxiosResponse } from 'axios'

import { apiClient } from './request'
import type { DataResponse } from '@/types/referenceData'
import type {
  CollaborationEvent,
  ConfirmedSalesOrderChangeInput,
  PaginatedSalesOrders,
  QuotationOrderContext,
  SalesOrder,
  SalesOrderInput,
  SalesOrderOptions,
  SalesOrderExchangeRatePreview,
  VersionedSalesOrder,
} from '@/types/salesOrder'

const basePath = '/api/v1/sales-orders/'

function versioned(response: AxiosResponse<DataResponse<SalesOrder>>): VersionedSalesOrder {
  return { data: response.data.data, etag: String(response.headers.etag || '') }
}

export async function fetchSalesOrders(query: Record<string, unknown>): Promise<PaginatedSalesOrders> {
  const { data } = await apiClient.get<PaginatedSalesOrders>(basePath, { params: query })
  return data
}
export async function fetchSalesOrder(id: string): Promise<VersionedSalesOrder> {
  return versioned(await apiClient.get<DataResponse<SalesOrder>>(`${basePath}${encodeURIComponent(id)}/`))
}
export async function fetchSalesOrderOptions(): Promise<SalesOrderOptions> {
  const { data } = await apiClient.get<DataResponse<SalesOrderOptions>>(`${basePath}options/`)
  return data.data
}
export async function fetchSalesOrderExchangeRate(currencyCode: string): Promise<SalesOrderExchangeRatePreview> {
  const { data } = await apiClient.get<DataResponse<SalesOrderExchangeRatePreview>>(`${basePath}exchange-rate-preview/`, {
    params: { currency_code: currencyCode },
  })
  return data.data
}
export async function fetchQuotationOrderContext(versionId: string): Promise<QuotationOrderContext> {
  const { data } = await apiClient.get<DataResponse<QuotationOrderContext>>(`${basePath}quotation-options/`, {
    params: { quotation_version_id: versionId },
  })
  return data.data
}
export async function createSalesOrder(payload: SalesOrderInput): Promise<VersionedSalesOrder> {
  return versioned(await apiClient.post<DataResponse<SalesOrder>>(basePath, payload))
}
export async function updateSalesOrder(id: string, payload: SalesOrderInput, etag: string): Promise<VersionedSalesOrder> {
  return versioned(await apiClient.patch<DataResponse<SalesOrder>>(
    `${basePath}${encodeURIComponent(id)}/`, payload, { headers: { 'If-Match': etag } },
  ))
}
export async function confirmSalesOrder(id: string, etag: string): Promise<VersionedSalesOrder> {
  return versioned(await apiClient.post<DataResponse<SalesOrder>>(
    `${basePath}${encodeURIComponent(id)}/confirm/`, {}, { headers: { 'If-Match': etag } },
  ))
}
export async function changeConfirmedSalesOrder(
  id: string,
  payload: ConfirmedSalesOrderChangeInput,
  etag: string,
): Promise<VersionedSalesOrder> {
  return versioned(await apiClient.post<DataResponse<SalesOrder>>(
    `${basePath}${encodeURIComponent(id)}/confirmed-change/`, payload, { headers: { 'If-Match': etag } },
  ))
}
export async function addSalesOrderCollaborationEvent(
  id: string,
  payload: { delivery_batch_id: string | null; event_type: string; status: string; title: string; note: string; quantity: string | null; occurred_at: string },
  etag: string,
): Promise<{ data: CollaborationEvent; etag: string }> {
  const response = await apiClient.post<DataResponse<CollaborationEvent>>(
    `${basePath}${encodeURIComponent(id)}/collaboration-events/`, payload, { headers: { 'If-Match': etag } },
  )
  return { data: response.data.data, etag: String(response.headers.etag || '') }
}
export async function cancelSalesOrderDeliveryBatch(
  orderId: string,
  batchId: string,
  reason: string,
  evidenceFileId: string,
  etag: string,
): Promise<VersionedSalesOrder> {
  return versioned(await apiClient.post<DataResponse<SalesOrder>>(
    `${basePath}${encodeURIComponent(orderId)}/delivery-batches/${encodeURIComponent(batchId)}/cancel/`,
    { reason, evidence_file_id: evidenceFileId },
    { headers: { 'If-Match': etag } },
  ))
}
export async function completeSalesOrder(
  id: string,
  exceptionClose: boolean,
  reason: string,
  etag: string,
): Promise<VersionedSalesOrder> {
  return versioned(await apiClient.post<DataResponse<SalesOrder>>(
    `${basePath}${encodeURIComponent(id)}/complete/`,
    { exception_close: exceptionClose, reason },
    { headers: { 'If-Match': etag } },
  ))
}
export async function uploadSalesOrderEvidence(id: string, file: File, etag: string): Promise<VersionedSalesOrder> {
  const body = new FormData()
  body.append('file', file)
  return versioned(await apiClient.post<DataResponse<SalesOrder>>(
    `${basePath}${encodeURIComponent(id)}/evidence/`, body, { headers: { 'If-Match': etag }, timeout: 120_000 },
  ))
}
export async function uploadSalesOrderLineProductImage(orderId: string, lineId: string, file: File, etag: string): Promise<VersionedSalesOrder> {
  const body = new FormData()
  body.append('file', file)
  return versioned(await apiClient.post<DataResponse<SalesOrder>>(
    `${basePath}${encodeURIComponent(orderId)}/lines/${encodeURIComponent(lineId)}/product-image/`,
    body, { headers: { 'If-Match': etag }, timeout: 120_000 },
  ))
}
export async function removeSalesOrderLineProductImage(orderId: string, lineId: string, etag: string): Promise<VersionedSalesOrder> {
  return versioned(await apiClient.delete<DataResponse<SalesOrder>>(
    `${basePath}${encodeURIComponent(orderId)}/lines/${encodeURIComponent(lineId)}/product-image/`,
    { headers: { 'If-Match': etag } },
  ))
}
export function salesOrderLineProductImageUrl(orderId: string, lineId: string): string {
  return apiClient.getUri({ url: `${basePath}${encodeURIComponent(orderId)}/lines/${encodeURIComponent(lineId)}/product-image/` })
}
export function salesOrderEvidenceUrl(orderId: string, fileId: string): string {
  return `${apiClient.defaults.baseURL || ''}${basePath}${encodeURIComponent(orderId)}/business-files/${encodeURIComponent(fileId)}/`
}
