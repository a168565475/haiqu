import type { AxiosResponse } from 'axios'

import { apiClient } from './request'
import type { DataResponse } from '@/types/referenceData'
import type { Paginated } from '@/types/outsourcing'
import type {
  P4ExternalOrder, P4HandoffDetail, P4Options, P4OriginalGoodReturnContext, P4OriginalOrderContext, P4Rework, P4SemiStock, P4Source, P4UnsprayedReturn,
} from '@/types/metalProcessingP4'
import { createClientUuid } from '@/utils/clientUuid'

const sourcePath = '/api/v1/metal-processing-sources/'
const handoffPath = '/api/v1/metal-processing-handoffs/'
const returnPath = '/api/v1/metal-processing-unsprayed-returns/'
const reworkPath = '/api/v1/metal-processing-reworks/'
const orderPath = '/api/v1/metal-processing-external-orders/'
const originalOrderPath = '/api/v1/metal-processing-original-orders/'

export async function fetchP4OriginalOrder(id: string): Promise<P4OriginalOrderContext> {
  return data(await apiClient.get<DataResponse<P4OriginalOrderContext>>(`${originalOrderPath}${encodeURIComponent(id)}/`))
}

export async function closeP4OriginalOrder(
  id: string,
  payload: { request_id: string; remark: string },
  etag: string,
): Promise<P4OriginalOrderContext> {
  return data(await apiClient.post<DataResponse<P4OriginalOrderContext>>(`${originalOrderPath}${encodeURIComponent(id)}/close/`, payload, { headers: { 'If-Match': etag } }))
}

export async function cancelP4OriginalPending(
  id: string,
  payload: { request_id: string; allocation_id: string; remark: string },
  etag: string,
): Promise<P4OriginalOrderContext> {
  return data(await apiClient.post<DataResponse<P4OriginalOrderContext>>(`${originalOrderPath}${encodeURIComponent(id)}/cancel-pending/`, payload, { headers: { 'If-Match': etag } }))
}

function data<T>(response: AxiosResponse<DataResponse<T>>): T {
  return response.data.data
}

export function newP4RequestId(): string {
  return createClientUuid()
}

export async function fetchP4Options(): Promise<P4Options> {
  return data(await apiClient.get<DataResponse<P4Options>>(`${sourcePath}options/`))
}

export async function fetchP4Sources(params: Record<string, unknown> = {}): Promise<Paginated<P4Source>> {
  const response = await apiClient.get<Paginated<P4Source>>(sourcePath, { params })
  return response.data
}

export async function fetchP4Source(id: string): Promise<P4Source> {
  return data(await apiClient.get<DataResponse<P4Source>>(`${sourcePath}${encodeURIComponent(id)}/`))
}

export async function fetchP4SourceClosurePreview(id: string): Promise<P4Source> {
  return data(await apiClient.get<DataResponse<P4Source>>(`${sourcePath}${encodeURIComponent(id)}/closure-preview/`))
}

export async function registerP4SourceCompletion(
  id: string,
  payload: { request_id: string; good_pieces: number; completion_date: string },
  etag: string,
): Promise<P4Source> {
  return data(await apiClient.post<DataResponse<P4Source>>(`${sourcePath}${encodeURIComponent(id)}/completions/`, payload, { headers: { 'If-Match': etag } }))
}

export async function closeP4Source(
  id: string,
  payload: { request_id: string; remark: string },
  etag: string,
): Promise<P4Source> {
  return data(await apiClient.post<DataResponse<P4Source>>(`${sourcePath}${encodeURIComponent(id)}/close/`, payload, { headers: { 'If-Match': etag } }))
}

export async function createP4OriginalHandoff(
  sourceId: string,
  payload: { request_id: string; original_order_id: string; factory_id: string; handoff_pieces: number; handoff_date: string },
  etag: string,
): Promise<P4Source> {
  return data(await apiClient.post<DataResponse<P4Source>>(`${sourcePath}${encodeURIComponent(sourceId)}/handoffs/`, payload, { headers: { 'If-Match': etag } }))
}

export async function fetchP4Handoff(id: string): Promise<P4HandoffDetail> {
  return data(await apiClient.get<DataResponse<P4HandoffDetail>>(`${handoffPath}${encodeURIComponent(id)}/`))
}

export async function confirmP4OriginalGoodReturn(
  handoffId: string,
  payload: { request_id: string; good_pieces: number; zone_id: string; received_by_employee_id: string; return_date: string; remark: string },
  etag: string,
): Promise<P4OriginalGoodReturnContext> {
  return data(await apiClient.post<DataResponse<P4OriginalGoodReturnContext>>(`${handoffPath}${encodeURIComponent(handoffId)}/good-returns/`, payload, { headers: { 'If-Match': etag } }))
}

export async function createP4UnsprayedReturn(
  handoffId: string,
  payload: { request_id: string; returned_pieces: number; received_by_employee_id: string; storage_location: string; return_date: string; remark: string },
  etag: string,
): Promise<P4UnsprayedReturn> {
  return data(await apiClient.post<DataResponse<P4UnsprayedReturn>>(`${handoffPath}${encodeURIComponent(handoffId)}/returns/`, payload, { headers: { 'If-Match': etag } }))
}

export async function createP4Rework(
  returnId: string,
  payload: { request_id: string; completed_pieces: number; completion_date: string },
): Promise<P4Rework> {
  return data(await apiClient.post<DataResponse<P4Rework>>(`${returnPath}${encodeURIComponent(returnId)}/rework/`, payload))
}

export async function createP4ExternalOrder(
  reworkId: string,
  payload: { request_id: string; factory_id: string; craft_id: string; allocated_pieces: number; unit_price?: string },
): Promise<P4ExternalOrder> {
  return data(await apiClient.post<DataResponse<P4ExternalOrder>>(`${reworkPath}${encodeURIComponent(reworkId)}/orders/`, payload))
}

export async function fetchP4ExternalOrders(): Promise<Paginated<P4ExternalOrder>> {
  const response = await apiClient.get<{ data: P4ExternalOrder[]; meta: { total: number } }>(orderPath)
  return { data: response.data.data, meta: { page: 1, page_size: response.data.data.length, total: response.data.meta.total, total_pages: 1 } }
}

export async function fetchP4ExternalOrder(id: string): Promise<P4ExternalOrder> {
  return data(await apiClient.get<DataResponse<P4ExternalOrder>>(`${orderPath}${encodeURIComponent(id)}/`))
}

export async function adjustP4ExternalAllocation(
  id: string,
  payload: { request_id: string; allocated_pieces: number },
  etag: string,
): Promise<P4ExternalOrder> {
  return data(await apiClient.post<DataResponse<P4ExternalOrder>>(`${orderPath}${encodeURIComponent(id)}/allocation/`, payload, { headers: { 'If-Match': etag } }))
}

export async function confirmP4ExternalHandoff(
  id: string,
  payload: { request_id: string; handoff_pieces: number; handoff_date: string },
  etag: string,
): Promise<P4ExternalOrder> {
  return data(await apiClient.post<DataResponse<P4ExternalOrder>>(`${orderPath}${encodeURIComponent(id)}/handoff/`, payload, { headers: { 'If-Match': etag } }))
}

export async function confirmP4GoodReturn(
  id: string,
  payload: { request_id: string; good_pieces: number; zone_id: string; received_by_employee_id: string; return_date: string; remark: string },
  etag: string,
): Promise<P4ExternalOrder> {
  return data(await apiClient.post<DataResponse<P4ExternalOrder>>(`${orderPath}${encodeURIComponent(id)}/returns/`, payload, { headers: { 'If-Match': etag } }))
}

export async function closeP4ExternalOrder(
  id: string,
  payload: { request_id: string; remark: string },
  etag: string,
): Promise<P4ExternalOrder> {
  return data(await apiClient.post<DataResponse<P4ExternalOrder>>(`${orderPath}${encodeURIComponent(id)}/close/`, payload, { headers: { 'If-Match': etag } }))
}

export async function fetchP4SemiStock(id: string): Promise<P4SemiStock> {
  return data(await apiClient.get<DataResponse<P4SemiStock>>(`${orderPath}${encodeURIComponent(id)}/semi-stock/`))
}
