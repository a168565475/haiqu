import type { AxiosResponse } from 'axios'

import { apiClient } from './request'
import type { DataResponse } from '@/types/referenceData'
import type {
  Paginated, PlanWageStatus, ReportingContext, ScheduleProgressStatus, Versioned, WageScheme, WageSchemeInput, WorkReport, WorkReportDay, WorkReportTask,
} from '@/types/workshopReporting'

const basePath = '/api/v1/workshop-reporting/'
const versioned = <T>(response: AxiosResponse<DataResponse<T>>): Versioned<T> => ({
  data: response.data.data,
  etag: typeof response.headers.etag === 'string' ? response.headers.etag : '',
})

export async function fetchReportingContext(scheduleProductId?: string, purpose: 'wage_scheme' | 'work_report' = 'wage_scheme'): Promise<ReportingContext> {
  const { data } = await apiClient.get<DataResponse<ReportingContext>>(`${basePath}context/`, {
    params: { schedule_product_id: scheduleProductId || undefined, purpose },
  })
  return data.data
}
export async function fetchPlanWageStatuses(params: { schedule_product_ids: string; production_date: string; plan_category: string }): Promise<PlanWageStatus[]> {
  const { data } = await apiClient.get<DataResponse<PlanWageStatus[]>>(`${basePath}plan-wage-statuses/`, { params })
  return data.data
}
export async function fetchScheduleProgressStatuses(params: { schedule_ids: string; production_date?: string }): Promise<ScheduleProgressStatus[]> {
  const { data } = await apiClient.get<DataResponse<ScheduleProgressStatus[]>>(`${basePath}schedule-progress-statuses/`, { params })
  return data.data
}
export async function fetchWageSchemes(params: Record<string, unknown> = {}): Promise<Paginated<WageScheme>> {
  const { data } = await apiClient.get<Paginated<WageScheme>>(`${basePath}wage-schemes/`, { params })
  return data
}
export async function fetchWageSchemeHistory(params: Record<string, unknown> = {}): Promise<Paginated<WageScheme>> {
  const { data } = await apiClient.get<Paginated<WageScheme>>(`${basePath}wage-schemes/history-schemes/`, { params })
  return data
}
export async function fetchWageScheme(id: string): Promise<Versioned<WageScheme>> {
  return versioned(await apiClient.get<DataResponse<WageScheme>>(`${basePath}wage-schemes/${encodeURIComponent(id)}/`))
}
export async function createWageScheme(payload: WageSchemeInput): Promise<Versioned<WageScheme>> {
  return versioned(await apiClient.post<DataResponse<WageScheme>>(`${basePath}wage-schemes/`, payload))
}
export async function updateWageScheme(id: string, payload: Partial<WageSchemeInput>, etag: string): Promise<Versioned<WageScheme>> {
  return versioned(await apiClient.patch<DataResponse<WageScheme>>(
    `${basePath}wage-schemes/${encodeURIComponent(id)}/`, payload, { headers: { 'If-Match': etag } },
  ))
}
export async function createWageSchemeChange(id: string, payload: WageSchemeInput, etag: string): Promise<Versioned<WageScheme>> {
  return versioned(await apiClient.post<DataResponse<WageScheme>>(
    `${basePath}wage-schemes/${encodeURIComponent(id)}/change/`, payload, { headers: { 'If-Match': etag } },
  ))
}
export async function submitWageScheme(id: string, etag: string): Promise<Versioned<WageScheme>> {
  return versioned(await apiClient.post<DataResponse<WageScheme>>(
    `${basePath}wage-schemes/${encodeURIComponent(id)}/submit/`, {}, { headers: { 'If-Match': etag } },
  ))
}
export async function approveWageScheme(id: string, etag: string): Promise<Versioned<WageScheme>> {
  return versioned(await apiClient.post<DataResponse<WageScheme>>(
    `${basePath}wage-schemes/${encodeURIComponent(id)}/approve/`, {}, { headers: { 'If-Match': etag } },
  ))
}
export async function returnWageScheme(id: string, etag: string, comment: string): Promise<Versioned<WageScheme>> {
  return versioned(await apiClient.post<DataResponse<WageScheme>>(
    `${basePath}wage-schemes/${encodeURIComponent(id)}/return/`, { comment }, { headers: { 'If-Match': etag } },
  ))
}
export async function fetchPriceContext(params: { product_line_id: string; schedule_product_id?: string; workshop_id: string; craft_id: string; production_date: string }): Promise<WageScheme> {
  const { data } = await apiClient.get<DataResponse<WageScheme>>(`${basePath}work-reports/price-context/`, { params })
  return data.data
}
export async function createWorkReport(payload: Record<string, unknown>): Promise<WorkReport> {
  const { data } = await apiClient.post<DataResponse<WorkReport>>(`${basePath}work-reports/`, payload)
  return data.data
}
export async function fetchWorkReport(id: string): Promise<Versioned<WorkReport>> {
  return versioned(await apiClient.get<DataResponse<WorkReport>>(`${basePath}work-reports/${encodeURIComponent(id)}/`))
}
export async function fetchWorkReports(params: { page?: number; page_size?: number; production_task_id?: string; schedule_product_id?: string; workshop_id?: string; craft_id?: string } = {}): Promise<Paginated<WorkReport>> {
  const { data } = await apiClient.get<Paginated<WorkReport>>(`${basePath}work-reports/`, { params })
  return data
}
export async function deleteWorkReport(id: string, reason: string, etag: string): Promise<void> {
  await apiClient.delete(`${basePath}work-reports/${encodeURIComponent(id)}/`, {
    data: { reason }, headers: { 'If-Match': etag }, timeout: 30000,
  })
}
export async function updateWorkReport(id: string, payload: Record<string, unknown>, etag: string): Promise<Versioned<WorkReport>> {
  return versioned(await apiClient.patch<DataResponse<WorkReport>>(
    `${basePath}work-reports/${encodeURIComponent(id)}/`, payload, { headers: { 'If-Match': etag } },
  ))
}
export async function fetchWorkReportDays(params: Record<string, unknown> = {}): Promise<Paginated<WorkReportDay>> {
  const { data } = await apiClient.get<Paginated<WorkReportDay>>(`${basePath}work-report-days/`, { params })
  return data
}
export async function fetchWorkReportTasks(params: { q?: string; page?: number; page_size?: number; production_task_id?: string } = {}): Promise<Paginated<WorkReportTask>> {
  const { data } = await apiClient.get<Paginated<WorkReportTask>>(`${basePath}work-report-tasks/`, { params })
  return data
}
export async function fetchWorkReportDay(day: string, params: Record<string, unknown> = {}): Promise<Paginated<WorkReport>> {
  const { data } = await apiClient.get<Paginated<WorkReport>>(`${basePath}work-report-days/${encodeURIComponent(day)}/`, { params })
  return data
}
