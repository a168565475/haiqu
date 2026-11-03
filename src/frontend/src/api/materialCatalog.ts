import type { AxiosResponse } from 'axios'
import { apiClient } from './request'
import type {
  MaterialAttributeInput, MaterialCatalog, MaterialCatalogDraft, MaterialCatalogInput, MaterialCatalogList,
  MaterialCatalogOptions, MaterialCatalogQuery, MaterialCatalogPatch, MaterialUnitSelection, MaterialUnitInput, VersionedMaterialCatalog,
  PublicMaterialFields, PublicMaterialOptions, PublicMaterialOptionsQuery, PublicTubeOptions,
  PublicMaterialResource, PublicMaterialRecord, PublicMaterialRecords, PublicMaterialRecordsQuery,
  PublicMaterialRecordInput, PublicMaterialRecordPatch, VersionedPublicMaterialRecord,
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
export async function fetchPublicMaterialFields(): Promise<PublicMaterialFields> {
  return (await apiClient.get<DataResponse<PublicMaterialFields>>(`${basePath}public-fields/`)).data.data
}
export async function fetchPublicMaterialOptions(query: PublicMaterialOptionsQuery): Promise<PublicMaterialOptions> {
  return (await apiClient.get<DataResponse<PublicMaterialOptions>>(`${basePath}public-options/`, { params: query })).data.data
}
export async function fetchPublicTubeOptions(): Promise<PublicTubeOptions> {
  return (await apiClient.get<DataResponse<PublicTubeOptions>>(`${basePath}public-tube-options/`)).data.data
}
const publicPath = (resource: PublicMaterialResource, id?: string) => `/api/v1/reference-data/${resource}/${id ? `${encodeURIComponent(id)}/` : ''}`
function publicVersioned<T extends PublicMaterialRecord>(response: AxiosResponse<DataResponse<T>>): VersionedPublicMaterialRecord<T> {
  return { data: response.data.data, etag: typeof response.headers.etag === 'string' ? response.headers.etag : '' }
}
export async function fetchPublicMaterialRecords<T extends PublicMaterialRecord = PublicMaterialRecord>(resource: PublicMaterialResource, query: PublicMaterialRecordsQuery = {}): Promise<PublicMaterialRecords<T>> {
  return (await apiClient.get<PublicMaterialRecords<T>>(publicPath(resource), { params: query })).data
}
export async function fetchPublicMaterialRecord<T extends PublicMaterialRecord = PublicMaterialRecord>(resource: PublicMaterialResource, id: string): Promise<VersionedPublicMaterialRecord<T>> {
  return publicVersioned(await apiClient.get<DataResponse<T>>(publicPath(resource, id)))
}
export async function createPublicMaterialRecord<T extends PublicMaterialRecord = PublicMaterialRecord>(resource: PublicMaterialResource, payload: PublicMaterialRecordInput): Promise<VersionedPublicMaterialRecord<T>> {
  return publicVersioned(await apiClient.post<DataResponse<T>>(publicPath(resource), payload))
}
export async function updatePublicMaterialRecord<T extends PublicMaterialRecord = PublicMaterialRecord>(resource: PublicMaterialResource, id: string, payload: PublicMaterialRecordPatch, etag: string): Promise<VersionedPublicMaterialRecord<T>> {
  return publicVersioned(await apiClient.patch<DataResponse<T>>(publicPath(resource, id), payload, headers(etag)))
}
export async function changePublicMaterialRecordStatus<T extends PublicMaterialRecord = PublicMaterialRecord>(resource: PublicMaterialResource, id: string, action: 'activate' | 'deactivate', etag: string, reason: string): Promise<VersionedPublicMaterialRecord<T>> {
  return publicVersioned(await apiClient.post<DataResponse<T>>(`${publicPath(resource, id)}${action}/`, { reason, confirm_references: false }, headers(etag)))
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
export async function updateMaterialCatalog(id: string, payload: MaterialCatalogPatch, etag: string): Promise<VersionedMaterialCatalog> {
  return versioned(await apiClient.patch<DataResponse<MaterialCatalog>>(path(id), payload, headers(etag)))
}
export async function saveMaterialCatalog(id: string, payload: MaterialCatalogDraft, etag: string): Promise<VersionedMaterialCatalog> {
  return versioned(await apiClient.put<DataResponse<MaterialCatalog>>(path(id), payload, headers(etag)))
}
export async function archiveMaterialCatalog(id: string, etag: string): Promise<void> {
  await apiClient.delete(path(id), headers(etag))
}
export async function addMaterialAttributeValue(id: string, payload: MaterialAttributeInput, etag: string): Promise<VersionedMaterialCatalog> {
  return versioned(await apiClient.post<DataResponse<MaterialCatalog>>(`${path(id)}values/`, payload, headers(etag)))
}
export async function deleteMaterialAttributeValue(id: string, valueId: string, etag: string): Promise<VersionedMaterialCatalog> {
  return versioned(await apiClient.delete<DataResponse<MaterialCatalog>>(`${path(id)}values/${encodeURIComponent(valueId)}/`, headers(etag)))
}
export async function updateMaterialAttributeValue(id: string, valueId: string, payload: { value: string }, etag: string): Promise<VersionedMaterialCatalog> {
  return versioned(await apiClient.patch<DataResponse<MaterialCatalog>>(`${path(id)}values/${encodeURIComponent(valueId)}/`, payload, headers(etag)))
}
export async function addMaterialAllowedUnit(id: string, payload: MaterialUnitInput, etag: string): Promise<VersionedMaterialCatalog> {
  return versioned(await apiClient.post<DataResponse<MaterialCatalog>>(`${path(id)}units/`, payload, headers(etag)))
}
export async function deleteMaterialAllowedUnit(id: string, optionId: string, etag: string): Promise<VersionedMaterialCatalog> {
  return versioned(await apiClient.delete<DataResponse<MaterialCatalog>>(`${path(id)}units/${encodeURIComponent(optionId)}/`, headers(etag)))
}
export async function updateMaterialAllowedUnit(id: string, optionId: string, payload: MaterialUnitSelection, etag: string): Promise<VersionedMaterialCatalog> {
  return versioned(await apiClient.patch<DataResponse<MaterialCatalog>>(`${path(id)}units/${encodeURIComponent(optionId)}/`, payload, headers(etag)))
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
