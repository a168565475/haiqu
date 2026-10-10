import type { OutsourcingReconciliation, OutsourcingReconciliationInput } from '@/types/outsourcing'
import type { AxiosResponse } from 'axios'

import { apiClient } from './request'
import type { DataResponse } from '@/types/referenceData'
import type {
  OutsourcingFactory,
  OutsourcingFactoryInput,
  OutsourcingDispatchContext,
  OutsourcingOptions,
  OutsourcingOrder,
  OutsourcingOrderCreateInput,
  OutsourcingOrderDetail,
  OutsourcingSourcePlan,
  OutsourcingSourceBomContext,
  Paginated,
  VersionedFactory,
  VersionedOutsourcingOrder,
} from '@/types/outsourcing'

const factoryPath = '/api/v1/outsourcing-factories/'
const orderPath = '/api/v1/outsourcing-orders/'

function versioned(response: AxiosResponse<DataResponse<OutsourcingFactory>>): VersionedFactory {
  return {
    data: response.data.data,
    etag: typeof response.headers.etag === 'string' ? response.headers.etag : '',
  }
}

function versionedOrder(response: AxiosResponse<DataResponse<OutsourcingOrderDetail>>): VersionedOutsourcingOrder {
  return {
    data: response.data.data,
    etag: typeof response.headers.etag === 'string' ? response.headers.etag : '',
  }
}

export async function fetchOutsourcingFactories(params: Record<string, unknown>): Promise<Paginated<OutsourcingFactory>> {
  const { data } = await apiClient.get<Paginated<OutsourcingFactory>>(factoryPath, { params })
  return data
}

export async function fetchOutsourcingFactory(id: string): Promise<VersionedFactory> {
  return versioned(await apiClient.get<DataResponse<OutsourcingFactory>>(`${factoryPath}${encodeURIComponent(id)}/`))
}

export async function fetchOutsourcingFactoryOrders(id: string, params: Record<string, unknown>): Promise<Paginated<OutsourcingOrder>> {
  const { data } = await apiClient.get<Paginated<OutsourcingOrder>>(
    `${factoryPath}${encodeURIComponent(id)}/related-orders/`, { params },
  )
  return data
}

export async function fetchOutsourcingFactoryOptions(): Promise<{ crafts: OutsourcingOptions['crafts']; processing_types: string[] }> {
  const { data } = await apiClient.get<DataResponse<{ crafts: OutsourcingOptions['crafts']; processing_types: string[] }>>(`${factoryPath}options/`)
  return data.data
}

export async function createOutsourcingFactory(payload: OutsourcingFactoryInput): Promise<VersionedFactory> {
  return versioned(await apiClient.post<DataResponse<OutsourcingFactory>>(factoryPath, payload))
}

export async function updateOutsourcingFactory(id: string, payload: OutsourcingFactoryInput, etag: string): Promise<VersionedFactory> {
  return versioned(await apiClient.patch<DataResponse<OutsourcingFactory>>(
    `${factoryPath}${encodeURIComponent(id)}/`, payload, { headers: { 'If-Match': etag } },
  ))
}

export async function disableOutsourcingFactory(id: string, etag: string): Promise<VersionedFactory> {
  return versioned(await apiClient.post<DataResponse<OutsourcingFactory>>(
    `${factoryPath}${encodeURIComponent(id)}/disable/`, {}, { headers: { 'If-Match': etag } },
  ))
}

export async function fetchOutsourcingOrders(params: Record<string, unknown>): Promise<Paginated<OutsourcingOrder>> {
  const { data } = await apiClient.get<Paginated<OutsourcingOrder>>(orderPath, { params })
  return data
}

export async function createOutsourcingOrder(payload: OutsourcingOrderCreateInput): Promise<VersionedOutsourcingOrder> {
  return versionedOrder(await apiClient.post<DataResponse<OutsourcingOrderDetail>>(orderPath, payload))
}

export async function fetchOutsourcingOrder(id: string): Promise<VersionedOutsourcingOrder> {
  return versionedOrder(await apiClient.get<DataResponse<OutsourcingOrderDetail>>(
    `${orderPath}${encodeURIComponent(id)}/`,
  ))
}

export function outsourcingProductImageUrl(orderId: string, fileId: string): string {
  const path = `${orderPath}${encodeURIComponent(orderId)}/product-files/${encodeURIComponent(fileId)}/`
  return new URL(path, `${apiClient.defaults.baseURL || window.location.origin}/`).toString()
}

export async function cancelOutsourcingOrder(
  id: string,
  reason: string,
  etag: string,
): Promise<VersionedOutsourcingOrder> {
  return versionedOrder(await apiClient.post<DataResponse<OutsourcingOrderDetail>>(
    `${orderPath}${encodeURIComponent(id)}/cancel/`,
    { reason },
    { headers: { 'If-Match': etag } },
  ))
}

export async function deleteOutsourcingOrder(id: string, etag: string): Promise<void> {
  await apiClient.delete(
    `${orderPath}${encodeURIComponent(id)}/`,
    { headers: { 'If-Match': etag } },
  )
}

export async function revokeDispatchedOutsourcingOrder(
  id: string,
  reason: string,
  requestId: string,
  etag: string,
): Promise<VersionedOutsourcingOrder> {
  return versionedOrder(await apiClient.post<DataResponse<OutsourcingOrderDetail>>(
    `${orderPath}${encodeURIComponent(id)}/revoke-dispatched/`,
    { reason, request_id: requestId },
    { headers: { 'If-Match': etag } },
  ))
}

export async function confirmOutsourcingDispatch(
  id: string,
  payload: {
    request_id: string
    remark: string
    lines: Array<{
      material_item_id: string
      zone_id: string
      requested_quantity: string
    }>
  },
  etag: string,
): Promise<VersionedOutsourcingOrder> {
  return versionedOrder(await apiClient.post<DataResponse<OutsourcingOrderDetail>>(
    `${orderPath}${encodeURIComponent(id)}/confirm-dispatch/`,
    payload,
    { headers: { 'If-Match': etag } },
  ))
}

export async function fetchOutsourcingDispatchContext(id: string): Promise<OutsourcingDispatchContext> {
  const { data } = await apiClient.get<DataResponse<OutsourcingDispatchContext>>(
    `${orderPath}${encodeURIComponent(id)}/dispatch-context/`,
  )
  return data.data
}

export async function confirmOutsourcingReturn(
  id: string,
  payload: {
    request_id: string
    factory_id: string
    good_zone_id: string | null
    defective_zone_id: string | null
    received_by_employee_id: string
    return_date: string
    delivery_note_number: string
    raw_inputs?: OutsourcingReconciliationInput[]
    lines: Array<{
      allocation_id: string
      good_quantity: string
      defective_quantity: string
      defect_reason: string
    }>
    remark: string
  },
  etag: string,
): Promise<VersionedOutsourcingOrder> {
  return versionedOrder(await apiClient.post<DataResponse<OutsourcingOrderDetail>>(
    `${orderPath}${encodeURIComponent(id)}/confirm-return/`,
    payload,
    { headers: { 'If-Match': etag } },
  ))
}

export async function fetchOutsourcingOptions(): Promise<OutsourcingOptions> {
  const { data } = await apiClient.get<DataResponse<OutsourcingOptions>>(`${orderPath}options/`)
  return data.data
}

export async function fetchOutsourcingSourcePlans(params: Record<string, unknown>): Promise<Paginated<OutsourcingSourcePlan>> {
  const { data } = await apiClient.get<Paginated<OutsourcingSourcePlan>>(`${orderPath}source-plans/`, { params })
  return data
}

export async function fetchOutsourcingSourceBom(
  scheduleProductId: string,
  craftId: string,
): Promise<OutsourcingSourceBomContext> {
  const encodedId = encodeURIComponent(scheduleProductId)
  const { data } = await apiClient.get<DataResponse<OutsourcingSourceBomContext>>(
    `${orderPath}source-products/${encodedId}/bom/`,
    { params: { craft_id: craftId } },
  )
  return data.data
}

export async function fetchOutsourcingReconciliation(id: string): Promise<OutsourcingReconciliation> {
  const { data } = await apiClient.get<DataResponse<OutsourcingReconciliation>>(`${orderPath}${encodeURIComponent(id)}/reconciliation/`)
  return data.data
}
export async function confirmOutsourcingFlow(
  id: string, action: 'confirm-raw-return' | 'confirm-reconciliation' | 'complete',
  payload: { request_id: string; factory_id?: string; reason?: string; lines?: Array<{ dispatch_line_id: string; quantity: string }>; entries?: OutsourcingReconciliationInput[] }, etag: string,
): Promise<VersionedOutsourcingOrder> {
  return versionedOrder(await apiClient.post<DataResponse<OutsourcingOrderDetail>>(
    `${orderPath}${encodeURIComponent(id)}/${action}/`, payload, { headers: { 'If-Match': etag } },
  ))
}
