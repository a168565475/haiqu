import type { AxiosResponse } from 'axios'
import { apiClient } from '@/utils/request'
import type { VersionedWorkshopEmployee, WorkshopEmployee, WorkshopEmployeeInput, WorkshopEmployeeOptions, WorkshopEmployeePage, WorkshopEmployeeQuery } from '@/types/workshopEmployees'

const base = '/api/v1/workshop-config/employees/'

function versioned(response: AxiosResponse<{ data: WorkshopEmployee }>): VersionedWorkshopEmployee {
  const data = response.data?.data
  const etag = response.headers.etag
  if (!data?.id || typeof data.can_edit !== 'boolean' || typeof etag !== 'string' || !etag) {
    throw new Error('未收到完整员工配置或版本，请重新读取后核对。')
  }
  return { data, etag }
}

function requireVersion(etag: string) {
  if (!etag) throw new Error('缺少员工配置版本，请重新读取后操作。')
}

export async function fetchWorkshopEmployees(query: WorkshopEmployeeQuery, signal?: AbortSignal): Promise<WorkshopEmployeePage> {
  const { data } = await apiClient.get<WorkshopEmployeePage>(base, { params: { page_size: 20, ...query }, signal })
  if (!Array.isArray(data?.data) || !data.data.every(row => row.id && typeof row.can_edit === 'boolean')
    || !Number.isInteger(data.meta?.total) || data.meta.total < 0
    || !Number.isInteger(data.meta?.total_pages) || data.meta.total_pages < 0) {
    throw new Error('员工名单返回不完整，请重新加载。')
  }
  return data
}

export async function fetchWorkshopEmployeeOptions(signal?: AbortSignal): Promise<WorkshopEmployeeOptions> {
  const { data } = await apiClient.get<{ data: WorkshopEmployeeOptions }>(`${base}options/`, { signal })
  const options = data?.data
  if (!Array.isArray(options?.workshops) || !Array.isArray(options?.editable_workshops)) {
    throw new Error('车间选项返回不完整，请重新加载。')
  }
  return options
}

export async function fetchWorkshopEmployee(id: string, signal?: AbortSignal): Promise<VersionedWorkshopEmployee> {
  return versioned(await apiClient.get<{ data: WorkshopEmployee }>(`${base}${encodeURIComponent(id)}/`, { signal }))
}

export async function updateWorkshopEmployee(id: string, payload: Partial<WorkshopEmployeeInput>, etag: string): Promise<VersionedWorkshopEmployee> {
  requireVersion(etag)
  return versioned(await apiClient.patch<{ data: WorkshopEmployee }>(`${base}${encodeURIComponent(id)}/`, payload, { headers: { 'If-Match': etag } }))
}

export async function deleteWorkshopEmployee(id: string, etag: string): Promise<void> {
  requireVersion(etag)
  await apiClient.delete(`${base}${encodeURIComponent(id)}/`, { headers: { 'If-Match': etag } })
}
