import { apiClient } from './request'
import type { Paginated } from '@/types/outsourcing'
import type { DataResponse } from '@/types/referenceData'
import type { TubeOptions, TubeOrderDetail, TubeOrderResult, TubePendingOrderInput, TubeSourceContext } from '@/types/tubeOutsourcing'
import type { UnifiedOutsourcingOrder } from '@/types/unifiedOutsourcing'

const path = '/api/v1/cut-piece-printing-orders/'

export async function fetchPrintOrders(params: { search: string; page: number; page_size: number }) {
  const { data } = await apiClient.get<Paginated<UnifiedOutsourcingOrder>>(path, { params })
  return data
}

export async function fetchPrintOrder(id: string) {
  const { data } = await apiClient.get<DataResponse<TubeOrderDetail>>(`${path}${encodeURIComponent(id)}/`)
  return data.data
}

export async function fetchPrintOptions() {
  const { data } = await apiClient.get<DataResponse<TubeOptions>>(`${path}options/`, { params: { category: 'screen_printing' } })
  return data.data
}

export async function fetchPrintSource(scheduleProductId: string, craftId: string) {
  const { data } = await apiClient.get<DataResponse<TubeSourceContext>>(`${path}source-context/`, {
    params: { category: 'screen_printing', is_plan: true, schedule_product_id: scheduleProductId, craft_id: craftId },
    timeout: 15000,
  })
  return data.data
}

export async function createPrintOrder(payload: TubePendingOrderInput) {
  const { data } = await apiClient.post<DataResponse<TubeOrderResult>>(path, payload, { timeout: 30000 })
  return data.data
}

export async function findPrintOrder(requestId: string) {
  const { data } = await apiClient.get<DataResponse<TubeOrderResult>>(`${path}by-request/${encodeURIComponent(requestId)}/`, { timeout: 15000 })
  return data.data
}
