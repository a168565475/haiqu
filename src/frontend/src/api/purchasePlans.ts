import { apiClient } from './request'
import type { DataResponse } from '@/types/referenceData'
import type { PurchasePlanCategory, PurchasePlanDetail, PurchasePlanPage, PurchasePlanQuery } from '@/types/purchasePlans'

const path = '/api/v1/purchase-plans/'

export async function fetchPurchasePlans(query: PurchasePlanQuery, signal?: AbortSignal): Promise<PurchasePlanPage> {
  return (await apiClient.get<PurchasePlanPage>(path, { params: query, signal })).data
}

export async function fetchPurchasePlanDetail(id: string, taskId: string, category: PurchasePlanCategory, signal?: AbortSignal): Promise<PurchasePlanDetail> {
  return (await apiClient.get<DataResponse<PurchasePlanDetail>>(`${path}${id}/`, {
    params: { task_id: taskId, category }, signal,
  })).data.data
}
