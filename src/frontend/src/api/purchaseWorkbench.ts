import { apiClient } from './request'
import type { DataResponse } from '@/types/referenceData'
import type { PurchaseTrackingPage } from '@/types/purchaseTracking'
import type { PurchaseWorkbenchCategory, PurchaseWorkbenchRow, PurchaseWorkbenchSpend, PurchaseWorkbenchSummary, SpendPeriod } from '@/types/purchaseWorkbench'

const base = '/api/v1/purchase-tracking/'

export async function getPurchaseWorkbench(signal?: AbortSignal) {
  return (await apiClient.get<DataResponse<PurchaseWorkbenchSummary>>(`${base}workbench/`, { signal })).data.data
}

export async function getPurchaseWorkbenchItems(category: PurchaseWorkbenchCategory, page: number, signal?: AbortSignal) {
  return (await apiClient.get<PurchaseTrackingPage<PurchaseWorkbenchRow>>(`${base}workbench-items/`, {
    params: { category, page, page_size: 20 }, signal,
  })).data
}

export async function getPurchaseWorkbenchSpend(period: SpendPeriod, date: string, signal?: AbortSignal) {
  return (await apiClient.get<DataResponse<PurchaseWorkbenchSpend>>(`${base}workbench-spend/`, {
    params: { period, date }, signal,
  })).data.data
}
