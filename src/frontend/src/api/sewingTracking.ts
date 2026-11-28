import type { SewingTrackingPage, SewingTrackingQuery } from '@/types/sewingTracking'
import { apiClient } from './request'

export async function fetchSewingTracking(
  params: SewingTrackingQuery, signal: AbortSignal,
) {
  const { data } = await apiClient.get<SewingTrackingPage>('/api/v1/sewing-tracking/', { params, signal })
  return data
}
