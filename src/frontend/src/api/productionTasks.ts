import type { AxiosResponse } from 'axios'

import { apiClient } from './request'
import type { DataResponse } from '@/types/referenceData'
import type {
  PaginatedProductionTasks,
  ProductionTask,
  ProductionTaskInput,
  ProductionTaskPatchInput,
  ProductionTaskOptions,
  ProductionTaskFilterOptions,
  ProductionTaskPmcDecisionInput,
  ProductionTaskQuery,
  ReservedContractNumber,
  ProductionTaskStats,
  ProductionOrderFromSalesInput,
  VersionedProductionTask,
} from '@/types/productionTask'

const basePath = '/api/v1/production-tasks/'

function versioned(response: AxiosResponse<DataResponse<ProductionTask>>): VersionedProductionTask {
  return { data: response.data.data, etag: typeof response.headers.etag === 'string' ? response.headers.etag : '' }
}

export async function fetchProductionTasks(query: ProductionTaskQuery): Promise<PaginatedProductionTasks> {
  const { data } = await apiClient.get<PaginatedProductionTasks>(basePath, { params: query })
  return data
}

export async function fetchProductionTask(id: string): Promise<VersionedProductionTask> {
  const response = await apiClient.get<DataResponse<ProductionTask>>(`${basePath}${encodeURIComponent(id)}/`)
  return versioned(response)
}

export async function fetchProductionTaskOptions(): Promise<ProductionTaskOptions> {
  const { data } = await apiClient.get<DataResponse<ProductionTaskOptions>>(`${basePath}options/`)
  return data.data
}

export async function fetchProductionTaskFilterOptions(): Promise<ProductionTaskFilterOptions> {
  const { data } = await apiClient.get<DataResponse<ProductionTaskFilterOptions>>(`${basePath}options/`, { params: { scope: 'filters' } })
  return data.data
}

export async function fetchProductionTaskStats(query: ProductionTaskQuery = {}): Promise<ProductionTaskStats> {
  const { data } = await apiClient.get<DataResponse<ProductionTaskStats>>(`${basePath}stats/`, { params: query })
  return data.data
}

export async function exportProductionTasks(query: ProductionTaskQuery, ids: string[] = []): Promise<{ blob: Blob; count: number | null }> {
  const config = {
    params: { ...query, page: undefined, page_size: undefined },
    responseType: 'blob' as const,
    timeout: 60_000,
  }
  const response = ids.length
    ? await apiClient.post<Blob>(`${basePath}export/`, { ids }, config)
    : await apiClient.get<Blob>(`${basePath}export/`, config)
  const parsedCount = Number(response.headers['x-export-count'])
  return { blob: response.data, count: Number.isInteger(parsedCount) && parsedCount >= 0 ? parsedCount : null }
}

export async function createProductionOrderFromSalesOrder(
  payload: ProductionOrderFromSalesInput,
): Promise<VersionedProductionTask> {
  const response = await apiClient.post<DataResponse<ProductionTask>>(`${basePath}create-from-sales-order/`, payload)
  return versioned(response)
}

export async function reserveProductionTaskContractNumber(orderDate: string): Promise<ReservedContractNumber> {
  const { data } = await apiClient.post<DataResponse<ReservedContractNumber>>(
    `${basePath}reserve-contract-number/`,
    { order_date: orderDate },
  )
  return data.data
}

function multipartPayload(payload: ProductionTaskInput | ProductionTaskPatchInput, productImages: Record<string, File[]>, detailImages: Record<string, File | null>) {
  const form = new FormData()
  form.append('payload', JSON.stringify(payload))
  Object.entries(productImages).forEach(([key, files]) => {
    files.forEach((file) => form.append(`product_image_${key}`, file))
  })
  Object.entries(detailImages).forEach(([key, file]) => { if (file) form.append(`detail_image_${key}`, file) })
  return form
}

export async function createProductionTask(
  payload: ProductionTaskInput,
  productImages: Record<string, File[]>,
  detailImages: Record<string, File | null>,
): Promise<VersionedProductionTask> {
  const response = await apiClient.post<DataResponse<ProductionTask>>(basePath, multipartPayload(payload, productImages, detailImages))
  return versioned(response)
}

export async function updateProductionTask(
  id: string,
  payload: ProductionTaskPatchInput,
  productImages: Record<string, File[]>,
  detailImages: Record<string, File | null>,
  etag: string,
): Promise<VersionedProductionTask> {
  const response = await apiClient.patch<DataResponse<ProductionTask>>(
    `${basePath}${encodeURIComponent(id)}/`,
    multipartPayload(payload, productImages, detailImages),
    { headers: { 'If-Match': etag } },
  )
  return versioned(response)
}

export async function submitProductionTask(id: string, etag: string): Promise<VersionedProductionTask> {
  const response = await apiClient.post<DataResponse<ProductionTask>>(
    `${basePath}${encodeURIComponent(id)}/submit/`, {}, { headers: { 'If-Match': etag } },
  )
  return versioned(response)
}

export async function decideProductionTaskByPmc(
  id: string,
  payload: ProductionTaskPmcDecisionInput,
  etag: string,
): Promise<VersionedProductionTask> {
  const response = await apiClient.post<DataResponse<ProductionTask>>(
    `${basePath}${encodeURIComponent(id)}/pmc-decision/`,
    payload,
    { headers: { 'If-Match': etag } },
  )
  return versioned(response)
}

export async function transitionProductionTask(
  id: string,
  action: 'confirm' | 'start',
  etag: string,
  payload: { start_waiver_reason?: string } = {},
): Promise<VersionedProductionTask> {
  const response = await apiClient.post<DataResponse<ProductionTask>>(
    `${basePath}${encodeURIComponent(id)}/${action}/`, payload, { headers: { 'If-Match': etag } },
  )
  return versioned(response)
}

async function closeProductionTask(id: string, action: 'cancel' | 'finish', reason: string, etag: string): Promise<VersionedProductionTask> {
  const response = await apiClient.post<DataResponse<ProductionTask>>(
    `${basePath}${encodeURIComponent(id)}/${action}/`, { reason }, { headers: { 'If-Match': etag } },
  )
  return versioned(response)
}

export function cancelProductionTask(id: string, reason: string, etag: string): Promise<VersionedProductionTask> {
  return closeProductionTask(id, 'cancel', reason, etag)
}

export async function finishProductionTask(
  id: string,
  reason: string,
  etag: string,
  completion?: {
    actual_quantity: string
    actual_good_quantity: string
    run_batches: Array<{ batch_number: string; planned_quantity: string; actual_quantity: string; good_quantity: string; status: 'COMPLETED'; note: string }>
  },
): Promise<VersionedProductionTask> {
  if (!completion) return closeProductionTask(id, 'finish', reason, etag)
  const response = await apiClient.post<DataResponse<ProductionTask>>(
    `${basePath}${encodeURIComponent(id)}/finish/`, { ...completion, reason }, { headers: { 'If-Match': etag } },
  )
  return versioned(response)
}

export function productionTaskBusinessFileUrl(taskId: string, fileId: string): string {
  const relativePath = `${basePath}${encodeURIComponent(taskId)}/business-files/${encodeURIComponent(fileId)}/`
  return new URL(relativePath, `${apiClient.defaults.baseURL || window.location.origin}/`).toString()
}
