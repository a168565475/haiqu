import type { AxiosResponse } from 'axios'
import { apiClient } from '@/utils/request'
import type {
  IssueWritePayload, MaterialIssue, MaterialIssueOptions, MaterialIssuePage, MaterialIssueProduct,
  MaterialRequirementResponse, VersionedIssue,
} from '@/types/materialIssue'

const root = '/api/v1/material-issues/'
const versioned = (response: AxiosResponse<{ data: MaterialIssue }>): VersionedIssue => ({
  data: response.data.data, etag: String(response.headers.etag || ''),
})

export async function fetchMaterialIssueOptions(taskId?: string) {
  const response = await apiClient.get<{ data: MaterialIssueOptions }>(`${root}options/`, {
    params: { include_task_id: taskId || undefined }, timeout: 15000,
  })
  return response.data.data
}
export async function fetchMaterialIssueProducts(taskId: string) {
  const response = await apiClient.get<{ data: MaterialIssueProduct[] }>(`${root}eligible-products/`, {
    params: { production_task_id: taskId }, timeout: 15000,
  })
  return response.data.data
}
export async function fetchMaterialRequirements(params: {
  production_task_id: string; product_line_id: string; workshop_id: string; issue_id?: string; plan_category?: string
}) {
  const response = await apiClient.get<{ data: MaterialRequirementResponse }>(`${root}requirements/`, { params, timeout: 15000 })
  return response.data.data
}
export async function fetchMaterialIssues(params: Record<string, unknown>) {
  return (await apiClient.get<MaterialIssuePage>(root, { params, timeout: 15000 })).data
}
export async function fetchMaterialIssue(id: string) {
  return versioned(await apiClient.get<{ data: MaterialIssue }>(`${root}${encodeURIComponent(id)}/`, { timeout: 15000 }))
}
export async function createMaterialIssue(payload: IssueWritePayload) {
  return versioned(await apiClient.post<{ data: MaterialIssue }>(root, payload, { timeout: 30000 }))
}
export async function updateMaterialIssue(id: string, payload: IssueWritePayload, etag: string) {
  if (!etag) throw new Error('领料单版本信息缺失，请重新加载后再修改。')
  return versioned(await apiClient.patch<{ data: MaterialIssue }>(`${root}${encodeURIComponent(id)}/`, payload, {
    headers: { 'If-Match': etag }, timeout: 30000,
  }))
}

/** 提交超时可能已成功，只读核对原单状态，不重建申请或自动重发写请求。 */
export async function submitMaterialIssue(id: string, etag: string, onReconciled?: (result: VersionedIssue) => void) {
  if (!etag) throw new Error('领料单版本信息缺失，请重新加载后再提交。')
  try {
    return versioned(await apiClient.post<{ data: MaterialIssue }>(`${root}${encodeURIComponent(id)}/submit/`, {}, {
      headers: { 'If-Match': etag }, timeout: 30000,
    }))
  } catch (submitError) {
    let latest: VersionedIssue
    try { latest = await fetchMaterialIssue(id) }
    catch { throw submitError }
    onReconciled?.(latest)
    if (latest.data.status === 'PENDING_REVIEW' || latest.data.status === 'ISSUED') return latest
    throw submitError
  }
}
