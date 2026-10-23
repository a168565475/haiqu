import type { AxiosResponse } from 'axios'

import { apiClient } from './request'
import type { DataResponse } from '@/types/referenceData'
import type {
  PaginatedWorkshopConfig,
  EditableResourceKind,
  ResourceKind,
  VersionedWorkshopConfig,
  WorkshopConfigInput,
  WorkshopConfigQuery,
  WorkshopConfigRecord,
  WorkshopConfigSummary,
} from '@/types/workshopConfig'

const basePath = '/api/v1/workshop-config/'

export async function deleteWorkshopEmployee(id: string, etag: string): Promise<void> {
  await apiClient.delete(`${basePath}employees/${encodeURIComponent(id)}/`, { headers: { 'If-Match': etag } })
}

function resourcePath(kind: ResourceKind): string {
  return `${basePath}${kind}/`
}

function versioned<T extends WorkshopConfigRecord>(
  response: AxiosResponse<DataResponse<T>>,
): VersionedWorkshopConfig<T> {
  return {
    data: response.data.data,
    etag: typeof response.headers.etag === 'string' ? response.headers.etag : '',
  }
}

export async function fetchWorkshopConfigList<T extends WorkshopConfigRecord>(
  kind: ResourceKind,
  query: WorkshopConfigQuery,
): Promise<PaginatedWorkshopConfig<T>> {
  const { data } = await apiClient.get<PaginatedWorkshopConfig<T>>(resourcePath(kind), { params: query })
  return data
}

export async function fetchWorkshopConfigDetail<T extends WorkshopConfigRecord>(
  kind: ResourceKind,
  id: string,
): Promise<VersionedWorkshopConfig<T>> {
  const response = await apiClient.get<DataResponse<T>>(`${resourcePath(kind)}${encodeURIComponent(id)}/`)
  return versioned(response)
}

export async function fetchWorkshopConfigSummary(
  kind: ResourceKind,
): Promise<WorkshopConfigSummary> {
  const { data } = await apiClient.get<DataResponse<WorkshopConfigSummary>>(`${resourcePath(kind)}summary/`)
  return data.data
}

export async function createWorkshopConfig<T extends WorkshopConfigRecord>(
  kind: EditableResourceKind,
  payload: WorkshopConfigInput,
): Promise<VersionedWorkshopConfig<T>> {
  const response = await apiClient.post<DataResponse<T>>(resourcePath(kind), payload)
  return versioned(response)
}

export async function updateWorkshopConfig<T extends WorkshopConfigRecord>(
  kind: EditableResourceKind,
  id: string,
  payload: Partial<WorkshopConfigInput>,
  etag: string,
): Promise<VersionedWorkshopConfig<T>> {
  const response = await apiClient.patch<DataResponse<T>>(
    `${resourcePath(kind)}${encodeURIComponent(id)}/`,
    payload,
    { headers: { 'If-Match': etag } },
  )
  return versioned(response)
}
