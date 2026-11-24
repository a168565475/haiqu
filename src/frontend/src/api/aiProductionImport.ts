import { isAxiosError, type AxiosResponse } from 'axios'
import { apiClient } from './request'
import type { AiImportIssue, AiImportRecordSummary, AiImportReviewDraft, AiOpenAiConfig, AiOpenAiConfigInput, AiProductionImportPayload, AiProductionImportResponse } from '@/types/aiProductionImport'

const configBase = '/api/v1/ai-openai-configs/'
const importBase = '/api/v1/ai-production-imports/'

function etag(response: AxiosResponse<unknown>): string { return String(response.headers.etag || '') }
function versioned(response: AxiosResponse<{ data: AiProductionImportPayload; replay?: boolean }>): AiProductionImportResponse {
  const payload = response.data.data
  const sources = Array.isArray(payload.sources) ? payload.sources : Object.entries(payload.sources || {}).map(([sourceId, source]) => ({
    ...source, source_id: sourceId, cell_range: source.cell_range || source.ref || '',
  }))
  const issues = (payload.issues || []).map(issue => ({
    ...issue,
    id: issue.id || issue.issue_key,
    code: issue.code || issue.kind,
    severity: issue.severity || 'warning' as const,
    source_refs: issue.source_refs || issue.source_ids || [],
  }))
  return { data: { ...payload, sources, issues }, replay: response.data.replay, etag: etag(response) }
}

export async function fetchAiOpenAiConfig() {
  const response = await apiClient.get<{ data?: AiOpenAiConfig | AiOpenAiConfig[]; results?: AiOpenAiConfig[] } | AiOpenAiConfig[]>(configBase)
  const payload = response.data
  const list = Array.isArray(payload)
    ? payload
    : Array.isArray(payload.data)
      ? payload.data
      : payload.results || []
  const data = Array.isArray(payload) ? payload[0] : Array.isArray(payload.data) ? payload.data[0] : payload.data || list[0]
  if (data?.id && !etag(response)) {
    const detail = await apiClient.get<{ data: AiOpenAiConfig }>(`${configBase}${encodeURIComponent(data.id)}/`)
    return { data: detail.data.data, etag: etag(detail) }
  }
  return { data: data || { configured: false, key_configured: false, label: '', provider: 'openai', model: 'gpt-6-astra', key_last4: '', key_fingerprint: '', updated_at: null }, etag: etag(response) }
}
export async function saveAiOpenAiConfig(payload: AiOpenAiConfigInput, currentEtag = '', id = '') {
  const { api_key, ...fields } = payload
  const body = id && !api_key.trim() ? fields : payload
  const response = id
    ? await apiClient.patch<{ data: AiOpenAiConfig }>(`${configBase}${encodeURIComponent(id)}/`, body, { headers: currentEtag ? { 'If-Match': currentEtag } : undefined })
    : await apiClient.post<{ data: AiOpenAiConfig }>(configBase, payload, { headers: currentEtag ? { 'If-Match': currentEtag } : undefined })
  return { data: response.data.data, etag: etag(response) }
}
export async function clearAiOpenAiConfig(id: string, currentEtag = '') {
  const response = await apiClient.delete(`${configBase}${encodeURIComponent(id)}/`, { headers: currentEtag ? { 'If-Match': currentEtag } : undefined })
  return { etag: etag(response) }
}
export async function uploadAiProductionImport(file: File, requestId: string) {
  const form = new FormData(); form.append('file', file); form.append('client_request_id', requestId)
  return versioned(await apiClient.post(importBase, form, { timeout: 1_230_000 }))
}
export async function fetchAiProductionImport(id: string, signal?: AbortSignal) {
  return versioned(await apiClient.get(`${importBase}${encodeURIComponent(id)}/`, { signal }))
}
export async function listAiProductionImports(offset = 0, limit = 20) {
  return (await apiClient.get<{ count: number; results: AiImportRecordSummary[] }>(importBase, { params: { offset, limit } })).data
}
export async function saveAiImportReview(id: string, draft: AiImportReviewDraft, currentEtag: string) {
  return versioned(await apiClient.patch(`${importBase}${encodeURIComponent(id)}/`, draft, { headers: { 'If-Match': currentEtag } }))
}
export async function deleteAiProductionImport(id: string, currentEtag: string) {
  await apiClient.delete(`${importBase}${encodeURIComponent(id)}/`, { headers: { 'If-Match': currentEtag } })
}
export async function remapAiProductionImport(id: string, currentEtag: string) {
  return versioned(await apiClient.post(`${importBase}${encodeURIComponent(id)}/remap/`, {}, { headers: { 'If-Match': currentEtag }, timeout: 1_230_000 }))
}
export async function matchAiProductionMaterials(id: string, currentEtag: string) {
  return versioned(await apiClient.post(`${importBase}${encodeURIComponent(id)}/match-materials/`, {}, { headers: { 'If-Match': currentEtag }, timeout: 630_000 }))
}
export async function selectAiImportTask(id: string, taskKey: string, currentEtag: string) {
  return versioned(await apiClient.post(`${importBase}${encodeURIComponent(id)}/select-task/`,
    { task_key: taskKey }, { headers: { 'If-Match': currentEtag } }))
}
export async function restoreAiImportReview(id: string, currentEtag: string) {
  return versioned(await apiClient.post(`${importBase}${encodeURIComponent(id)}/restore-review/`, {},
    { headers: { 'If-Match': currentEtag } }))
}
export async function createAiProductionTaskDraft(id: string, payload: Record<string, unknown>, currentEtag = '', taskKey?: string) {
  const response = await apiClient.post<{ data: AiProductionImportPayload; replay?: boolean }>(
    `${importBase}${encodeURIComponent(id)}/create-task/`, { payload, ...(taskKey ? { task_key: taskKey } : {}) },
    { headers: currentEtag ? { 'If-Match': currentEtag } : undefined },
  )
  return versioned(response)
}
export async function createAiProductionBoms(id: string, plans: Array<Record<string, unknown>>, currentEtag = '', taskKey?: string) {
  const response = await apiClient.post<{ data: AiProductionImportPayload; replay?: boolean; boms?: Array<Record<string, unknown>> }>(
    `${importBase}${encodeURIComponent(id)}/create-boms/`, { plans, ...(taskKey ? { task_key: taskKey } : {}) },
    { headers: currentEtag ? { 'If-Match': currentEtag } : undefined },
  )
  return { ...versioned(response), boms: response.data.boms || [] }
}
export function importIssueText(issue: AiImportIssue): string { return issue.field_path ? `${issue.field_path}：${issue.message}` : issue.message }

export function aiImportErrorMessage(error: unknown, fallback: string): string {
  if (!isAxiosError(error)) return fallback
  if (error.code === 'ECONNABORTED' || error.code === 'ETIMEDOUT') {
    return '等待识别结果超时，尚未创建生产任务或 BOM。请先确认后端处理状态，避免重复提交。'
  }
  if (!error.response) return '无法连接识别服务，请检查网络或后端服务。尚未创建生产任务或 BOM。'
  const body = error.response.data as { error?: { message?: unknown; field_errors?: { detail?: unknown } }; detail?: unknown } | undefined
  const candidates = [body?.error?.field_errors?.detail, body?.detail, body?.error?.message]
  for (const candidate of candidates) {
    const message = Array.isArray(candidate) ? candidate.find(value => typeof value === 'string') : candidate
    // 后端统一异常包装有时把错误码放进 message；不把代码或原始异常当用户说明。
    if (typeof message === 'string' && message.trim() && !/^[A-Z][A-Z0-9_]+$/.test(message.trim())) return message
  }
  return fallback
}

