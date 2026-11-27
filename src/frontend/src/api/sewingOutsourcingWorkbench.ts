import type { Paginated } from '@/types/outsourcing'
import type { DataResponse } from '@/types/referenceData'
import type { SewingPeriod, SewingQueue, SewingWorkbenchActivity, SewingWorkbenchOrder, SewingWorkbenchOverview } from '@/types/sewingOutsourcingWorkbench'
import { apiClient } from './request'

const base = '/api/v1/sewing-outsourcing-workbench/'

export async function getSewingOverview(signal?: AbortSignal) {
  return (await apiClient.get<DataResponse<SewingWorkbenchOverview>>(base, { signal })).data.data
}

export async function getSewingActivity(period: SewingPeriod, signal?: AbortSignal) {
  return (await apiClient.get<DataResponse<SewingWorkbenchActivity>>(`${base}activity/`, { params: { period }, signal })).data.data
}

export async function getSewingItems(category: SewingQueue, page: number, date?: string, signal?: AbortSignal) {
  return (await apiClient.get<Paginated<SewingWorkbenchOrder>>(`${base}items/`, {
    params: { category, page, page_size: 20, date }, signal,
  })).data
}
