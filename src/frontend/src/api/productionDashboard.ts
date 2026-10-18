import { apiClient } from './request'
import type { ProductionDashboardPayload, ProductionDashboardQuery } from '@/types/productionDashboard'

export async function fetchProductionDashboard(
  query: ProductionDashboardQuery,
  signal?: AbortSignal,
): Promise<ProductionDashboardPayload> {
  const response = await apiClient.get<{ data: ProductionDashboardPayload }>('/api/v1/production-dashboard/', {
    params: query,
    signal,
  })
  return response.data.data
}
