import type { AxiosResponse } from 'axios'

import { apiClient } from './request'
import type { DataResponse } from '@/types/referenceData'
import type {
  MaterialIssue, MaterialIssueOptions, MaterialIssuePreview, MaterialIssueProduct, MaterialRequirementResponse, PaginatedMaterialIssues,
} from '@/types/materialIssue'

const root = '/api/v1/material-issues/'
const detailTimeout = 15000
const mutationTimeout = 30000
const versioned = (response: AxiosResponse<DataResponse<MaterialIssue>>) => ({
  data: response.data.data,
  etag: String(response.headers.etag || ''),
})

export function materialIssueProductImageUrl(taskId: string, fileId: string): string {
  const path = `${root}product-images/${encodeURIComponent(taskId)}/${encodeURIComponent(fileId)}/`
  return new URL(path, `${apiClient.defaults.baseURL || window.location.origin}/`).toString()
}

export async function fetchMaterialIssues(params: Record<string, unknown>) {
  const { data } = await apiClient.get<PaginatedMaterialIssues>(root, { params })
  return data
}
export async function fetchMaterialIssueOptions(includeTaskId?: string) {
  const { data } = await apiClient.get<DataResponse<MaterialIssueOptions>>(`${root}options/`, { params: { include_task_id: includeTaskId || undefined }, timeout: 15000 })
  return data.data
}
export async function fetchEligibleMaterialIssueProducts(productionTaskId: string) {
  const { data } = await apiClient.get<DataResponse<MaterialIssueProduct[]>>(`${root}eligible-products/`, { params: { production_task_id: productionTaskId } })
  return data.data
}
export async function fetchMaterialRequirements(productionTaskId: string, productLineId: string, workshopId: string, issueId?: string, planCategory?: string) {
  const { data } = await apiClient.get<DataResponse<MaterialRequirementResponse>>(`${root}requirements/`, { params: { production_task_id: productionTaskId, product_line_id: productLineId, workshop_id: workshopId, ...(issueId ? { issue_id: issueId } : {}), ...(planCategory ? { plan_category: planCategory } : {}) }, timeout: 15000 })
  return data.data
}
export async function fetchMaterialIssue(id: string) { return versioned(await apiClient.get<DataResponse<MaterialIssue>>(`${root}${id}/`, { timeout: detailTimeout })) }
export async function createMaterialIssue(payload: Record<string, unknown>) { return versioned(await apiClient.post<DataResponse<MaterialIssue>>(root, payload, { timeout: mutationTimeout })) }
export async function updateMaterialIssue(id: string, payload: Record<string, unknown>, etag: string) { return versioned(await apiClient.patch<DataResponse<MaterialIssue>>(`${root}${id}/`, payload, { headers: { 'If-Match': etag }, timeout: mutationTimeout })) }
export async function submitMaterialIssue(id: string, etag: string) { return versioned(await apiClient.post<DataResponse<MaterialIssue>>(`${root}${id}/submit/`, {}, { headers: { 'If-Match': etag }, timeout: mutationTimeout })) }
export async function returnMaterialIssue(id: string, reason: string, etag: string) { return versioned(await apiClient.post<DataResponse<MaterialIssue>>(`${root}${id}/return/`, { reason }, { headers: { 'If-Match': etag } })) }
export async function previewMaterialIssue(id: string) { const { data } = await apiClient.post<DataResponse<MaterialIssuePreview>>(`${root}${id}/preview-issue/`, {}, { timeout: detailTimeout }); return data.data }
export async function confirmMaterialIssue(id: string, requestId: string, etag: string) { return versioned(await apiClient.post<DataResponse<MaterialIssue>>(`${root}${id}/confirm-issue/`, { request_id: requestId }, { headers: { 'If-Match': etag }, timeout: mutationTimeout })) }
