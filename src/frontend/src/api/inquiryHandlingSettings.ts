import { apiClient } from './request'
import type { InquiryWorkCalendar } from '@/types/inquiry'

export interface InquiryHandlingSettings {
  stage_minutes: Record<string, number>
  work_calendar: InquiryWorkCalendar
}
const endpoint = '/api/v1/inquiry-handling-time/settings/'
export async function fetchInquiryHandlingSettings() {
  const response = await apiClient.get<{data: InquiryHandlingSettings}>(endpoint)
  return {data: response.data.data, etag: String(response.headers.etag || '')}
}
export async function saveInquiryHandlingSettings(data: InquiryHandlingSettings, etag: string) {
  const response = await apiClient.put<{data: InquiryHandlingSettings}>(endpoint, data, {headers: {'If-Match':etag}})
  return {data: response.data.data, etag: String(response.headers.etag || '')}
}
