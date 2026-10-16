import type { AxiosResponse } from 'axios'
import { apiClient } from './request'
import type {
  MaterialAttributeInput, MaterialCatalog, MaterialCatalogInput, MaterialCatalogList,
  MaterialCatalogOptions, MaterialCatalogQuery, MaterialUnitInput, VersionedMaterialCatalog,
} from '@/types/materialCatalog'

const basePath = '/api/v1/material-catalog/'
type DataResponse<T> = { data: T }
const path = (id: string) => `${basePath}${encodeURIComponent(id)}/`
const headers = (etag: string) => ({ headers: { 'If-Match': etag } })
function versioned(response: AxiosResponse<DataResponse<MaterialCatalog>>): VersionedMaterialCatalog {
  return { data: response.data.data, etag: typeof response.headers.etag === 'string' ? response.headers.etag : '' }
}

export async function fetchMaterialCatalogOptions(): Promise<MaterialCatalogOptions> {
  return (await apiClient.get<DataResponse<MaterialCatalogOptions>>(`${basePath}options/`)).data.data
}
export async function fetchMaterialCatalogs(query: MaterialCatalogQuery): Promise<MaterialCatalogList> {
  return (await apiClient.get<MaterialCatalogList>(basePath, { params: query })).data
}
export async function fetchMaterialCatalog(id: string): Promise<VersionedMaterialCatalog> {
  return versioned(await apiClient.get<DataResponse<MaterialCatalog>>(path(id)))
}
export async function createMaterialCatalog(payload: MaterialCatalogInput): Promise<VersionedMaterialCatalog> {
  return versioned(await apiClient.post<DataResponse<MaterialCatalog>>(basePath, payload))
}
export async function updateMaterialCatalog(id: string, payload: { spray_enabled: boolean }, etag: string): Promise<VersionedMaterialCatalog> {
  return versioned(await apiClient.patch<DataResponse<MaterialCatalog>>(path(id), payload, headers(etag)))
}
export async function addMaterialAttributeValue(id: string, payload: MaterialAttributeInput, etag: string): Promise<VersionedMaterialCatalog> {
  return versioned(await apiClient.post<DataResponse<MaterialCatalog>>(`${path(id)}values/`, payload, headers(etag)))
}
export async function deleteMaterialAttributeValue(id: string, valueId: string, etag: string): Promise<VersionedMaterialCatalog> {
  return versioned(await apiClient.delete<DataResponse<MaterialCatalog>>(`${path(id)}values/${encodeURIComponent(valueId)}/`, headers(etag)))
}
export async function addMaterialAllowedUnit(id: string, payload: MaterialUnitInput, etag: string): Promise<VersionedMaterialCatalog> {
  return versioned(await apiClient.post<DataResponse<MaterialCatalog>>(`${path(id)}units/`, payload, headers(etag)))
}
export async function deleteMaterialAllowedUnit(id: string, optionId: string, etag: string): Promise<VersionedMaterialCatalog> {
  return versioned(await apiClient.delete<DataResponse<MaterialCatalog>>(`${path(id)}units/${encodeURIComponent(optionId)}/`, headers(etag)))
}

type ApiError = { response?: { status?: number; data?: { error?: { message?: string; field_errors?: Record<string, unknown> }; detail?: string } }; message?: string }
export function materialCatalogErrorStatus(error: unknown): number | undefined {
  return (error as ApiError | null)?.response?.status
}
export function materialCatalogError(error: unknown): string {
  const issue = error as ApiError | null
  const status = materialCatalogErrorStatus(error)
  if (status === 412 || status === 428) return '档案版本已变化或缺失，请重新读取后再保存。'
  const data = issue?.response?.data
  const fields = Object.values(data?.error?.field_errors ?? {}).flat().filter(value => typeof value === 'string')
  if (fields.length) return fields.join('；')
  return data?.error?.message || data?.detail || issue?.message || '操作失败，请稍后重试。'
}
