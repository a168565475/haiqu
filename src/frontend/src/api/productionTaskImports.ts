import type { AxiosResponse } from 'axios'
import { apiClient } from './request'
import { fetchProductionTask } from './productionTasks'
import type { ImportReview, ProductionTaskImport, VersionedImport } from '@/types/productionTaskImport'

const base = '/api/v1/production-task-imports/'
function versioned(response: AxiosResponse<{ data: ProductionTaskImport }>): VersionedImport {
  return { data: response.data.data, etag: String(response.headers.etag || '') }
}
export async function uploadProductionTaskImport(file: File, requestId: string) {
  const form = new FormData()
  form.append('file', file); form.append('client_request_id', requestId)
  return versioned(await apiClient.post(base, form, { timeout: 60_000 }))
}
export async function fetchProductionTaskImport(id: string, signal?: AbortSignal) {
  return versioned(await apiClient.get(`${base}${encodeURIComponent(id)}/`, { signal }))
}
export async function recoverSavedProductionTaskImport(id: string) {
  const { data } = await fetchProductionTaskImport(id)
  if (data.state !== 'SAVED') return null
  if (!data.saved_task_id) throw new Error(`该导入已保存为 ${data.saved_task_number}，原单据已删除，不能重复建单。`)
  return fetchProductionTask(data.saved_task_id)
}
export async function actOnProductionTaskImport(id: string, action: 'select' | 'cancel' | 'retry' | 'rematch', etag: string, payload: object = {}) {
  return versioned(await apiClient.post(`${base}${encodeURIComponent(id)}/${action}/`, payload, { headers: { 'If-Match': etag } }))
}
export async function reviewProductionTaskImport(id: string, review: ImportReview, etag: string) {
  return versioned(await apiClient.patch(`${base}${encodeURIComponent(id)}/review/`, { review }, { headers: { 'If-Match': etag } }))
}
export async function fetchImportSources(id: string) {
  const response = await apiClient.get<{ data: Record<string, unknown> }>(`${base}${encodeURIComponent(id)}/source/`)
  return response.data.data
}
export function importImageUrl(id: string, image: string) { return apiClient.getUri({ url: `${base}${encodeURIComponent(id)}/images/${encodeURIComponent(image)}/` }) }
export function importSourceUrl(id: string) { return apiClient.getUri({ url: `${base}${encodeURIComponent(id)}/source/`, params: { download: '1' } }) }
