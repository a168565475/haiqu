import { apiClient } from './request'
import type { DataResponse } from '@/types/referenceData'
import type { MaterialTrackingDetail, MaterialTrackingList } from '@/types/materialTracking'

const root = '/api/v1/material-tracking/'

export async function fetchMaterialTracking(
  params: { task_number: string; page: number; page_size: number }, signal: AbortSignal,
) {
  const { data } = await apiClient.get<MaterialTrackingList>(root, { params, signal })
  return data
}

export async function fetchMaterialTrackingDetail(productId: string, signal: AbortSignal) {
  const { data } = await apiClient.get<DataResponse<MaterialTrackingDetail>>(`${root}${productId}/`, { signal })
  return data.data
}

export function materialTrackingBomFileUrl(productId: string, bomId: string) {
  return `${root}${productId}/bom-file/${bomId}/`
}
