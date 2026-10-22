import { apiClient } from './request'
import type { ProductionTimelinePage } from '@/types/productionTimeline'

export async function fetchProductionTimeline(id: string, params: { page: number; page_size: number; search: string }) {
  const { data } = await apiClient.get<ProductionTimelinePage>(`/api/v1/production-schedules/${encodeURIComponent(id)}/timeline/`, { params })
  return data
}
