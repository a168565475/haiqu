import type { DataResponse, PageMeta, PaginatedReferenceData } from '@/types/referenceData'
import type { WarehouseActivity, WarehouseDetail, WarehouseOverview, WarehousePeriod, WarehouseQueue, WarehouseReference, WarehouseRow } from '@/types/warehouseWorkbench'
import { apiClient } from './request'

const base = '/api/v1/warehouse-workbench/'

export async function getWarehouseOverview(signal: AbortSignal) {
  return (await apiClient.get<DataResponse<WarehouseOverview>>(base, { signal })).data.data
}

export async function getWarehouseItems(queue: WarehouseQueue, taskId: string | undefined, page: number, signal: AbortSignal) {
  const params = { queue, task_id: taskId, page, page_size: 20 }
  return (await apiClient.get<PaginatedReferenceData<WarehouseRow>>(base + 'items/', { params, signal })).data
}

export async function getWarehouseDetail(reference: WarehouseReference, signal: AbortSignal) {
  const { queue, kind, id } = reference
  return (await apiClient.get<DataResponse<WarehouseDetail>>(base + 'detail/', { params: { queue, kind, id }, signal })).data.data
}

export async function getWarehouseActivity(period: WarehousePeriod, queue: WarehouseQueue | 'all', page: number, signal: AbortSignal, summary = false) {
  const params = { period, queue, page, page_size: 20, summary: summary ? 1 : undefined }
  return (await apiClient.get<{ data: WarehouseActivity; meta: PageMeta }>(base + 'activity/', { params, signal })).data
}
