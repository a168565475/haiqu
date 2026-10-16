import { apiClient } from './request'
import type {
  InquiryCreateInput,
  InquiryDeletionPreview,
  InquiryCommunicationInput,
  InquiryDetail,
  InquiryDraftInput,
  InquiryListResult,
  InquiryMetrics,
  InquiryOptions,
  InquiryItem,
  InquiryProductSelectionOptions,
  InquiryRow,
  InquiryTimelineEvent,
  VersionedInquiry,
} from '@/types/inquiry'

const path = '/api/v1/inquiries/'
export async function fetchInquiryDeletionPreview(id: string): Promise<{ data: InquiryDeletionPreview; etag: string }> {
  const response = await apiClient.get<{ data: InquiryDeletionPreview }>(`${path}${encodeURIComponent(id)}/deletion-preview/`)
  return { data: response.data.data, etag: String(response.headers.etag || '') }
}
const dataOf = <T>(response: { data: { data: T } }) => response.data.data
const versioned = (response: { data: { data: InquiryDetail }; headers: { etag?: string } }): VersionedInquiry => ({
  data: response.data.data,
  etag: response.headers.etag || null,
})

export async function fetchInquiries(params: Record<string, unknown>) { return (await apiClient.get<InquiryListResult>(path, { params })).data }
export async function exportInquiries(params: Record<string, unknown>): Promise<Blob> {
  const response = await apiClient.get(`${path}export/`, { params, responseType: 'blob', timeout: 60000 })
  return response.data as Blob
}
export async function fetchInquiryMetrics(params: Record<string, unknown> = {}) { return dataOf<InquiryMetrics>(await apiClient.get(`${path}metrics/`, { params })) }
export async function setInquiryPriority(id: string, etag: string, priority: string): Promise<InquiryRow> {
  return dataOf<InquiryRow>(await apiClient.post(`${path}${encodeURIComponent(id)}/priority/`, { priority }, { headers: { 'If-Match': etag } }))
}
export async function fetchInquiryOptions(params: Record<string, unknown> = {}) { return dataOf<InquiryOptions>(await apiClient.get(`${path}options/`, { params })) }
export async function fetchInquiryProductSelectionOptions(categoryId: string, params: { product_name?: string; specification?: string } = {}): Promise<InquiryProductSelectionOptions> {
  return dataOf<InquiryProductSelectionOptions>(await apiClient.get('/api/v1/products/selection-options/', { params: { category_id: categoryId, ...params } }))
}
export const inquiryProductImageUrl = (itemId: string) => apiClient.getUri({ url: `/api/v1/inquiry-items/${encodeURIComponent(itemId)}/product-image/` })
export async function uploadInquiryProductImage(itemId: string, file: File, etag: string): Promise<VersionedInquiry<InquiryItem>> {
  const payload = new FormData()
  payload.append('file', file)
  const response = await apiClient.post(inquiryProductImageUrl(itemId), payload, { headers: { 'If-Match': etag } })
  return { data: response.data.data, etag: response.headers.etag || null }
}
export async function removeInquiryProductImage(itemId: string, etag: string): Promise<VersionedInquiry<InquiryItem>> {
  const response = await apiClient.delete(inquiryProductImageUrl(itemId), { headers: { 'If-Match': etag } })
  return { data: response.data.data, etag: response.headers.etag || null }
}
export async function downloadInquiryFile(id: string, fileId?: string): Promise<Blob> {
  const suffix = fileId ? `files/${encodeURIComponent(fileId)}/download/` : 'files-download/'
  return (await apiClient.get<Blob>(`${path}${encodeURIComponent(id)}/${suffix}`, { responseType: 'blob', timeout: 60000 })).data
}
export async function fetchInquiryTasks(id: string) {
  return dataOf<import('@/types/task').TaskSummary[]>(await apiClient.get(`${path}${encodeURIComponent(id)}/tasks/`))
}
export async function fetchAssignmentQueue(params: Record<string, unknown>) { return (await apiClient.get<InquiryListResult>(`${path}assignment-queue/`, { params })).data }
export async function fetchInquiryBoard(params: Record<string, unknown> = {}) { return dataOf<{ read_only: boolean; lanes: Array<{ code: string; label: string; count: number; cards: InquiryRow[] }> }>(await apiClient.get(`${path}board/`, { params })) }
export async function seedFigmaDemoInquiries() { return dataOf<{ created_or_existing: number; inquiry_ids: string[] }>(await apiClient.post(`${path}demo-seed/?demo=figma`)) }
export async function assignInquiry(id: string, etag: string, ownerEmployeeId: string, reason: string) { return dataOf<InquiryRow>(await apiClient.post(`${path}${id}/assign/`, { owner_employee_id: ownerEmployeeId, reason }, { headers: { 'If-Match': etag } })) }
export async function markInquiryInvalid(id: string, etag: string, reasonCode: string, reasonDetail: string) { return dataOf<InquiryRow>(await apiClient.post(`${path}${id}/mark-invalid/`, { reason_code: reasonCode, reason_detail: reasonDetail }, { headers: { 'If-Match': etag } })) }
export async function bulkAssignInquiries(items: Array<{ id: string; etag: string }>, ownerEmployeeId: string, reason: string) { return dataOf<{ updated: number }>(await apiClient.post(`${path}bulk-assign/`, { items, owner_employee_id: ownerEmployeeId, reason })) }
export async function bulkMarkInquiryInvalid(items: Array<{ id: string; etag: string }>, reasonCode: string, reasonDetail: string) { return dataOf<{ updated: number }>(await apiClient.post(`${path}bulk-mark-invalid/`, { items, reason_code: reasonCode, reason_detail: reasonDetail })) }
export async function fetchInquiry(id: string, params: Record<string, unknown> = {}): Promise<VersionedInquiry> {
  return versioned(await apiClient.get(`${path}${encodeURIComponent(id)}/`, { params }))
}
export async function deleteInquiry(id: string, etag: string): Promise<{ deleted_count: number }> {
  return dataOf<{ deleted_count: number }>(await apiClient.delete(`${path}${encodeURIComponent(id)}/`, { headers: { 'If-Match': etag } }))
}
export async function createInquiry(payload: InquiryCreateInput): Promise<VersionedInquiry> {
  return versioned(await apiClient.post(path, payload))
}
export async function uploadInquiryAttachment(id: string, file: File, uploadId: string, etag: string) {
  const body = new FormData()
  body.append('file', file)
  body.append('upload_id', uploadId)
  const response = await apiClient.post(`${path}${encodeURIComponent(id)}/attachments/`, body, { headers: { 'If-Match': etag }, timeout: 60000 })
  return { data: dataOf<import('@/types/inquiry').InquiryFile>(response), etag: typeof response.headers.etag === 'string' ? response.headers.etag : null }
}
export async function saveInquiryDraft(id: string, payload: InquiryDraftInput, etag: string): Promise<VersionedInquiry> {
  return versioned(await apiClient.patch(`${path}${encodeURIComponent(id)}/draft/`, payload, { headers: { 'If-Match': etag } }))
}
export async function submitInquiry(id: string, etag: string): Promise<VersionedInquiry> {
  return versioned(await apiClient.post(`${path}${encodeURIComponent(id)}/submit/`, {}, { headers: { 'If-Match': etag } }))
}
export async function startInquiry(id: string, etag: string): Promise<VersionedInquiry> {
  return versioned(await apiClient.post(`${path}${encodeURIComponent(id)}/start/`, {}, { headers: { 'If-Match': etag } }))
}
export async function respondToInquiry(id: string, etag: string, payload: InquiryCommunicationInput): Promise<VersionedInquiry> {
  return versioned(await apiClient.post(`${path}${encodeURIComponent(id)}/respond/`, payload, { headers: { 'If-Match': etag } }))
}
export async function confirmInquiryRequirements(id: string, etag: string): Promise<VersionedInquiry> {
  return versioned(await apiClient.post(`${path}${encodeURIComponent(id)}/confirm-requirements/`, {}, { headers: { 'If-Match': etag } }))
}
export async function syncInquiryQuotation(id: string, etag: string): Promise<VersionedInquiry> {
  return versioned(await apiClient.post(`${path}${encodeURIComponent(id)}/sync-quotation/`, {}, { headers: { 'If-Match': etag } }))
}
export async function markInquiryQuoted(id: string, etag: string): Promise<VersionedInquiry> {
  return versioned(await apiClient.post(`${path}${encodeURIComponent(id)}/mark-quoted/`, {}, { headers: { 'If-Match': etag } }))
}
export async function followUpInquiry(id: string, etag: string, payload: InquiryCommunicationInput): Promise<VersionedInquiry> {
  return versioned(await apiClient.post(`${path}${encodeURIComponent(id)}/follow-up/`, payload, { headers: { 'If-Match': etag } }))
}
export async function markInquiryLost(id: string, etag: string, reason: string): Promise<VersionedInquiry> {
  return versioned(await apiClient.post(`${path}${encodeURIComponent(id)}/mark-lost/`, { reason }, { headers: { 'If-Match': etag } }))
}
export async function attachInquiryContact(id: string, etag: string, customerContactId: string): Promise<VersionedInquiry> {
  return versioned(await apiClient.post(`${path}${encodeURIComponent(id)}/attach-contact/`, { customer_contact_id: customerContactId }, { headers: { 'If-Match': etag } }))
}
export async function fetchInquiryTimeline(id: string, params: Record<string, unknown> = {}) {
  return (await apiClient.get<{ data: InquiryTimelineEvent[]; meta: { page: number; page_size: number; total: number; total_pages: number } }>(`${path}${encodeURIComponent(id)}/timeline/`, { params })).data
}
