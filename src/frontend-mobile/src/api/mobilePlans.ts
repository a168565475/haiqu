import { apiClient } from '@/utils/request'
import type { MobileContext, MobilePlan, MobilePlanList } from '@/types/mobilePlan'

const path = '/api/v1/workshop-mobile/plans/'
export async function fetchMobileContext(signal?: AbortSignal) {
  const { data } = await apiClient.get<{ data: MobileContext }>('/api/v1/workshop-mobile/context/', { signal })
  return data.data
}
export async function fetchMobilePlans(params: { page?: number; page_size?: number; search?: string; plan_category?: string; workshop_id?: string }, signal?: AbortSignal) {
  const { data } = await apiClient.get<MobilePlanList>(path, { params, signal })
  return data
}
export async function fetchMobilePlan(id: string, params: { plan_category: string; workshop_id: string }, signal?: AbortSignal) {
  const { data } = await apiClient.get<{ data: MobilePlan }>(`${path}${encodeURIComponent(id)}/`, { params, signal })
  return data.data
}
