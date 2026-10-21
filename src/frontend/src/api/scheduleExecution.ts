import { apiClient } from './request'
import type { DataResponse } from '@/types/referenceData'
import type { ScheduleExecutionSummary } from '@/types/scheduleExecution'

export async function fetchScheduleExecutionSummary(scheduleId: string): Promise<ScheduleExecutionSummary> {
  const { data } = await apiClient.get<DataResponse<ScheduleExecutionSummary>>(
    `/api/v1/production-schedules/${encodeURIComponent(scheduleId)}/detail-summary/`,
  )
  return data.data
}
