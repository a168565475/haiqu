import type { AxiosResponse } from 'axios'

import { apiClient } from './request'
import type { ApiDataResponse, PaginatedResponse } from '@/types/customer'
import type { WorkbenchDashboardPayload, WorkbenchMode, WorkbenchTask } from '@/types/workbench'

export async function fetchWorkbenchDashboard(mode: WorkbenchMode): Promise<WorkbenchDashboardPayload> {
  const path = mode === 'MANAGER' ? '/api/v1/dashboard/manager/' : '/api/v1/dashboard/me/'
  const response = await apiClient.get<ApiDataResponse<WorkbenchDashboardPayload>>(path)
  return response.data.data
}

export async function fetchWorkbenchTasks(
  status: 'PENDING' | 'IN_PROGRESS',
  params: Record<string, unknown> = {},
): Promise<PaginatedResponse<WorkbenchTask>> {
  const response = await apiClient.get<PaginatedResponse<WorkbenchTask>>('/api/v1/tasks/', {
    params: { status, ordering: 'due_at', page_size: 100, ...params },
  })
  return response.data
}

export async function fetchWorkbenchTask(
  taskId: string,
): Promise<{ data: WorkbenchTask & { description: string }; etag: string | null }> {
  const response = await apiClient.get<ApiDataResponse<WorkbenchTask & { description: string }>>(
    `/api/v1/tasks/${encodeURIComponent(taskId)}/`,
  )
  return { data: response.data.data, etag: response.headers.etag || null }
}

export async function transitionWorkbenchTask(
  taskId: string,
  action: 'start' | 'complete',
  etag: string,
): Promise<WorkbenchTask> {
  const response: AxiosResponse<ApiDataResponse<WorkbenchTask>> = await apiClient.post(
    `/api/v1/tasks/${encodeURIComponent(taskId)}/${action}/`,
    { note: '' },
    { headers: { 'If-Match': etag } },
  )
  return response.data.data
}

export interface InquiryQuickCreateInput {
  customer_account_id: string
  owner_employee_id: string
  subject: string
  description: string
  received_at: string
  requested_due_at?: string
}

export async function createInquiry(payload: InquiryQuickCreateInput): Promise<Record<string, unknown>> {
  const response = await apiClient.post<ApiDataResponse<Record<string, unknown>>>(
    '/api/v1/inquiries/',
    payload,
  )
  return response.data.data
}
