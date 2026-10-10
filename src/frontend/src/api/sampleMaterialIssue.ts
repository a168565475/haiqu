import { apiClient } from './request'
import type { SampleMaterialIssueResult } from '@/types/sampleMaterialIssue'

type Envelope = { data: SampleMaterialIssueResult }

function requestId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  // 兼容没有 crypto.randomUUID 的旧浏览器；后端只要求合法 UUID。
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (character) => {
    const random = Math.random() * 16 | 0
    const value = character === 'x' ? random : (random & 0x3 | 0x8)
    return value.toString(16)
  })
}

function unwrap(response: { data: Envelope }): SampleMaterialIssueResult {
  return response.data.data
}

export async function fetchSampleMaterialIssue(sampleId: string): Promise<{ data: SampleMaterialIssueResult; etag: string }> {
  const response = await apiClient.get<Envelope>(`/api/v1/sample-requests/${encodeURIComponent(sampleId)}/material-issue/`)
  return { data: unwrap(response), etag: String(response.headers.etag || '') }
}

export async function initiateSampleMaterialIssue(
  sampleId: string,
  etag: string,
  note = '',
): Promise<{ data: SampleMaterialIssueResult; etag: string }> {
  const response = await apiClient.post<Envelope>(
    `/api/v1/sample-requests/${encodeURIComponent(sampleId)}/material-issue/initiate/`,
    { client_request_id: requestId(), note },
    { headers: { 'If-Match': etag }, timeout: 30_000 },
  )
  return { data: unwrap(response), etag: String(response.headers.etag || '') }
}

export async function confirmSampleMaterialIssue(
  sampleId: string,
  etag: string,
  lines: Array<{ line_id: string; issued_quantity: string }>,
): Promise<{ data: SampleMaterialIssueResult; etag: string }> {
  const response = await apiClient.post<Envelope>(
    `/api/v1/sample-requests/${encodeURIComponent(sampleId)}/material-issue/confirm/`,
    { request_id: requestId(), lines },
    { headers: { 'If-Match': etag }, timeout: 30_000 },
  )
  return { data: unwrap(response), etag: String(response.headers.etag || '') }
}
