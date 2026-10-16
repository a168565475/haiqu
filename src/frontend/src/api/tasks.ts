import type { AxiosResponse } from 'axios'

import { apiClient } from './request'
import type { ApiDataResponse, PaginatedResponse } from '@/types/customer'
import type {
  TaskDetail,
  TaskFilters,
  TaskOptions,
  TaskSummary,
} from '@/types/task'

function query(filters: Partial<TaskFilters>) {
  return Object.fromEntries(Object.entries(filters).filter(([, value]) => value !== '' && value !== undefined && value !== null))
}

export async function fetchTasks(filters: Partial<TaskFilters>): Promise<PaginatedResponse<TaskSummary>> {
  const response = await apiClient.get<PaginatedResponse<TaskSummary>>('/api/v1/tasks/', { params: query(filters) })
  return response.data
}

export async function fetchTaskOptions(scope: string): Promise<TaskOptions> {
  const response = await apiClient.get<ApiDataResponse<TaskOptions>>('/api/v1/tasks/options/', { params: { scope } })
  return response.data.data
}

export async function fetchTask(taskId: string): Promise<{ data: TaskDetail; etag: string | null }> {
  const response = await apiClient.get<ApiDataResponse<TaskDetail>>(`/api/v1/tasks/${encodeURIComponent(taskId)}/`)
  return { data: response.data.data, etag: response.headers.etag || null }
}

export async function deleteTask(taskId: string, etag: string): Promise<{ deleted_count: number }> {
  const response = await apiClient.delete<ApiDataResponse<{ deleted_count: number }>>(
    `/api/v1/tasks/${encodeURIComponent(taskId)}/`,
    { headers: { 'If-Match': etag } },
  )
  return response.data.data
}

export async function fetchTaskActivity(taskId: string): Promise<Array<{ kind: string; id: string; event_type: string; title: string; summary: string; occurred_at: string; actor: string | null }>> {
  const response = await apiClient.get<ApiDataResponse<Array<{ kind: string; id: string; event_type: string; title: string; summary: string; occurred_at: string; actor: string | null }>>>(`/api/v1/tasks/${encodeURIComponent(taskId)}/activity/`)
  return response.data.data
}

export async function createTask(payload: Record<string, unknown>): Promise<TaskDetail> {
  const response = await apiClient.post<ApiDataResponse<TaskDetail>>('/api/v1/tasks/', payload)
  return response.data.data
}

export async function postTaskAction(taskId: string, action: string, payload: Record<string, unknown>, etag: string): Promise<{ data: TaskDetail; etag: string | null }> {
  const response: AxiosResponse<ApiDataResponse<TaskDetail>> = await apiClient.post(
    `/api/v1/tasks/${encodeURIComponent(taskId)}/${action}/`, payload, { headers: { 'If-Match': etag } },
  )
  return { data: response.data.data, etag: response.headers.etag || null }
}

export async function previewTaskReschedule(taskId: string, payload: { new_due_at: string; reason: string; sync_reminders: boolean }): Promise<{ warning: boolean; conflict_count: number }> {
  const response = await apiClient.post<ApiDataResponse<{ warning: boolean; conflict_count: number }>>(
    `/api/v1/tasks/${encodeURIComponent(taskId)}/reschedule-preview/`,
    payload,
  )
  return response.data.data
}

export async function toggleTaskChecklist(taskId: string, itemId: string, isCompleted: boolean, etag: string): Promise<string | null> {
  const response = await apiClient.patch(
    `/api/v1/tasks/${encodeURIComponent(taskId)}/checklist/${encodeURIComponent(itemId)}/`,
    { is_completed: isCompleted },
    { headers: { 'If-Match': etag } },
  )
  return response.headers.etag || null
}
