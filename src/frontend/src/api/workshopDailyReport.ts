import type { WorkshopDailyPage, WorkshopDailyTable } from '@/types/workshopDailyReport'
import { apiClient } from './request'

export async function fetchWorkshopDailyReport(
  params: { report: WorkshopDailyTable; date: string; task_number: string; page: number },
  signal: AbortSignal,
) {
  const { data } = await apiClient.get<WorkshopDailyPage>('/api/v1/workshop-reporting/daily-reports/', { params, signal })
  return data
}
