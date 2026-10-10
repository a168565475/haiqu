import type { AxiosResponse } from 'axios'

import { apiClient } from './request'
import type {
  BatchCreatedSchedules, Paginated, ProductionSchedule, ScheduleBatchCreateInput, ScheduleCreateInput, ScheduleItem, ScheduleOptions,
  ScheduleTaskCandidate, ScheduleUpdateInput, VersionedSchedule,
} from '@/types/productionScheduling'
import type { DataResponse } from '@/types/referenceData'

const basePath = '/api/v1/production-schedules/'

function versioned(response: AxiosResponse<DataResponse<ProductionSchedule>>): VersionedSchedule {
  return { data: response.data.data, etag: typeof response.headers.etag === 'string' ? response.headers.etag : '' }
}

export async function fetchSchedules(params: Record<string, unknown>): Promise<Paginated<ProductionSchedule>> {
  const { data } = await apiClient.get<Paginated<ProductionSchedule>>(basePath, { params })
  return data
}

export async function fetchSchedule(id: string): Promise<VersionedSchedule> {
  return versioned(await apiClient.get<DataResponse<ProductionSchedule>>(`${basePath}${encodeURIComponent(id)}/`))
}

export async function createSchedule(payload: ScheduleCreateInput): Promise<VersionedSchedule> {
  return versioned(await apiClient.post<DataResponse<ProductionSchedule>>(basePath, payload))
}

export async function createSchedulesBatch(payload: ScheduleBatchCreateInput): Promise<BatchCreatedSchedules> {
  const { data } = await apiClient.post<BatchCreatedSchedules>(`${basePath}batch/`, payload)
  return data
}

export async function updateSchedule(id: string, payload: ScheduleUpdateInput, etag: string): Promise<VersionedSchedule> {
  return versioned(await apiClient.patch<DataResponse<ProductionSchedule>>(
    `${basePath}${encodeURIComponent(id)}/`, payload, { headers: { 'If-Match': etag } },
  ))
}

export async function voidSchedule(id: string, reason: string, etag: string): Promise<VersionedSchedule> {
  return versioned(await apiClient.post<DataResponse<ProductionSchedule>>(
    `${basePath}${encodeURIComponent(id)}/void/`, { reason }, { headers: { 'If-Match': etag } },
  ))
}

export async function fetchScheduleOptions(): Promise<ScheduleOptions> {
  const { data } = await apiClient.get<DataResponse<ScheduleOptions>>(`${basePath}options/`)
  return data.data
}

export async function fetchTaskCandidates(params: Record<string, unknown>): Promise<Paginated<ScheduleTaskCandidate>> {
  const { data } = await apiClient.get<Paginated<ScheduleTaskCandidate>>(`${basePath}task-candidates/`, { params })
  return data
}

export async function fetchTaskCandidate(id: string): Promise<ScheduleTaskCandidate> {
  const { data } = await apiClient.get<DataResponse<ScheduleTaskCandidate>>(
    `${basePath}task-candidates/${encodeURIComponent(id)}/`,
  )
  return data.data
}

export async function fetchScheduleItems(params: Record<string, unknown>): Promise<Paginated<ScheduleItem>> {
  const { data } = await apiClient.get<Paginated<ScheduleItem>>('/api/v1/production-schedule-items/', { params })
  return data
}

export function scheduleProductImageUrl(taskId: string, fileId: string): string {
  const path = `${basePath}task-files/${encodeURIComponent(taskId)}/${encodeURIComponent(fileId)}/`
  return new URL(path, `${apiClient.defaults.baseURL || window.location.origin}/`).toString()
}
