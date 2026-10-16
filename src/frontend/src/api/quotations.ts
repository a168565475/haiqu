import type { AxiosResponse } from 'axios'

import { apiClient } from './request'
import type { ApiDataResponse } from '@/types/customer'
import type { InquiryQuotationContext, InquiryQuotationCreatePayload, QuotationContainerConfig, QuotationContainerTier, QuotationCreatePayload, QuotationCreationOption, QuotationDetail, QuotationEmailDispatchAttempt, QuotationEmailDispatchResponse, QuotationLine, QuotationLinePackaging, QuotationLinePayload, QuotationListOptions, QuotationListQuery, QuotationListResult, QuotationPriceBasisPayload, QuotationPriceHistory, QuotationResponse, QuotationSummary, QuotationTemplate, QuotationTemplateResponse, QuotationTemplateSellerProfile, QuotationVersionDetail, QuotationVersionDiff, VersionResponse } from '@/types/quotation'

function unwrap<T>(response: AxiosResponse<ApiDataResponse<T>>): T {
  return response.data.data
}

export async function fetchQuotations(query: QuotationListQuery): Promise<QuotationListResult> {
  const { data } = await apiClient.get<QuotationListResult>('/api/v1/quotations/', { params: query })
  return data
}

export async function fetchQuotationSummary(query?: Partial<QuotationListQuery>): Promise<QuotationSummary> {
  return unwrap(await apiClient.get<ApiDataResponse<QuotationSummary>>('/api/v1/quotations/summary/', { params: query }))
}

export async function fetchQuotationOptions(): Promise<QuotationListOptions> {
  return unwrap(await apiClient.get<ApiDataResponse<QuotationListOptions>>('/api/v1/quotations/options/'))
}

export async function fetchQuotationPriceHistory(query: { customer_account_id?: string; product?: string; container_type_code?: string; currency_code?: string; period_months?: number }): Promise<QuotationPriceHistory> {
  return unwrap(await apiClient.get<ApiDataResponse<QuotationPriceHistory>>('/api/v1/quotations/price-history/', { params: query }))
}

export async function fetchQuotationCreationOptions(): Promise<QuotationCreationOption[]> {
  return unwrap(await apiClient.get<ApiDataResponse<QuotationCreationOption[]>>('/api/v1/quotations/creation-options/'))
}

export async function exportQuotations(query: QuotationListQuery): Promise<Blob> {
  const response = await apiClient.get('/api/v1/quotations/export/', { params: query, responseType: 'blob' })
  return response.data as Blob
}

function withEtag<T>(response: AxiosResponse<{ data: T }>): { data: T; etag: string } {
  return { data: response.data.data, etag: String(response.headers.etag || '') }
}

export async function fetchQuotation(quotationId: string): Promise<QuotationResponse> {
  return withEtag<QuotationDetail>(await apiClient.get(`/api/v1/quotations/${quotationId}/`))
}

export async function deleteQuotation(quotationId: string, etag: string): Promise<{ deleted_count: number }> {
  return unwrap(await apiClient.delete<ApiDataResponse<{ deleted_count: number }>>(
    `/api/v1/quotations/${encodeURIComponent(quotationId)}/`,
    { headers: { 'If-Match': etag } },
  ))
}

export async function fetchQuotationVersion(versionId: string): Promise<VersionResponse> {
  return withEtag<QuotationVersionDetail>(await apiClient.get(`/api/v1/quotation-versions/${versionId}/`))
}

export async function fetchQuotationTemplateSellerProfile(templateId: string): Promise<QuotationTemplateResponse> {
  return withEtag<QuotationTemplate>(await apiClient.get(`/api/v1/quotation-templates/${encodeURIComponent(templateId)}/seller-profile/`))
}

export async function updateQuotationTemplateSellerProfile(
  templateId: string,
  payload: Partial<QuotationTemplateSellerProfile>,
  etag: string,
): Promise<QuotationTemplateResponse> {
  return withEtag<QuotationTemplate>(await apiClient.patch(
    `/api/v1/quotation-templates/${encodeURIComponent(templateId)}/seller-profile/`,
    payload,
    { headers: { 'If-Match': etag } },
  ))
}

export async function createQuotation(payload: QuotationCreatePayload): Promise<QuotationResponse> {
  return withEtag<QuotationDetail>(await apiClient.post('/api/v1/quotations/', payload))
}

export async function createQuotationDraft(payload: QuotationCreatePayload & { currency_code: string; valid_until?: string | null }): Promise<QuotationResponse> {
  return withEtag<QuotationDetail>(await apiClient.post('/api/v1/quotations/create-draft/', payload))
}

export async function fetchInquiryQuotationContext(inquiryId: string): Promise<{ data: InquiryQuotationContext; etag: string }> {
  return withEtag<InquiryQuotationContext>(await apiClient.get('/api/v1/quotations/inquiry-context/', { params: { inquiry_id: inquiryId } }))
}

export async function createQuotationFromInquiry(payload: InquiryQuotationCreatePayload, inquiryEtag: string): Promise<{ data: { quotation: QuotationDetail; version_id: string; replayed: boolean }; etag: string; inquiryEtag: string }> {
  const response = await apiClient.post<{ data: { quotation: QuotationDetail; version_id: string; replayed: boolean } }>(
    '/api/v1/quotations/create-from-inquiry/', payload, { headers: { 'If-Match': inquiryEtag } },
  )
  return { data: response.data.data, etag: String(response.headers.etag || ''), inquiryEtag: String(response.headers['inquiry-etag'] || '') }
}

export async function createQuotationVersion(quotationId: string, payload: { currency_code: string; valid_until?: string | null; from_version_id?: string }, quotationEtag: string): Promise<VersionResponse> {
  return withEtag<QuotationVersionDetail>(await apiClient.post(`/api/v1/quotations/${quotationId}/versions/`, payload, { headers: { 'If-Match': quotationEtag } }))
}

export async function fetchQuotationVersionDiff(versionId: string, baseVersionId?: string | null): Promise<QuotationVersionDiff> {
  return unwrap(await apiClient.get<ApiDataResponse<QuotationVersionDiff>>(`/api/v1/quotation-versions/${versionId}/diff/`, {
    params: baseVersionId ? { base_version_id: baseVersionId } : undefined,
  }))
}

export async function updateQuotation(quotationId: string, payload: { subject?: string }, etag: string): Promise<QuotationResponse> {
  return withEtag<QuotationDetail>(await apiClient.patch(`/api/v1/quotations/${quotationId}/`, payload, { headers: { 'If-Match': etag } }))
}

export async function updateQuotationVersion(versionId: string, payload: { currency_code?: string; valid_until?: string | null; terms_snapshot?: Record<string, unknown>; notes?: string }, etag: string): Promise<VersionResponse> {
  return withEtag<QuotationVersionDetail>(await apiClient.patch(`/api/v1/quotation-versions/${versionId}/`, payload, { headers: { 'If-Match': etag } }))
}

export async function lockQuotationVersion(versionId: string, payload: { address_id: string; contact_id: string; tax_rate?: string; terms?: Record<string, unknown> }, etag: string): Promise<VersionResponse> {
  return withEtag<QuotationVersionDetail>(await apiClient.post(`/api/v1/quotation-versions/${versionId}/lock/`, payload, { headers: { 'If-Match': etag } }))
}

export async function issueQuotationVersion(versionId: string, etag: string): Promise<VersionResponse> {
  return withEtag<QuotationVersionDetail>(await apiClient.post(`/api/v1/quotation-versions/${versionId}/issue/`, {}, { headers: { 'If-Match': etag } }))
}

export async function createQuotationLine(versionId: string, payload: QuotationLinePayload, etag: string): Promise<{ data: QuotationLine; etag: string }> {
  return withEtag<QuotationLine>(await apiClient.post(`/api/v1/quotation-versions/${versionId}/lines/`, payload, { headers: { 'If-Match': etag } }))
}

export async function updateQuotationLine(lineId: string, payload: Partial<QuotationLinePayload>, etag: string): Promise<{ data: QuotationLine; etag: string }> {
  return withEtag<QuotationLine>(await apiClient.patch(`/api/v1/quotation-lines/${lineId}/`, payload, { headers: { 'If-Match': etag } }))
}
export async function syncQuotationLineToInquiry(lineId: string, inquiryEtag: string, quotationEtag: string): Promise<{ inquiryItemId: string; inquiryEtag: string; quotationEtag: string }> {
  const response = await apiClient.post<{ data: { inquiry_item_id: string; inquiry_etag: string } }>(
    `/api/v1/quotation-lines/${lineId}/sync-inquiry/`,
    { inquiry_etag: inquiryEtag },
    { headers: { 'If-Match': quotationEtag } },
  )
  return {
    inquiryItemId: response.data.data.inquiry_item_id,
    inquiryEtag: response.data.data.inquiry_etag,
    quotationEtag: String(response.headers.etag || ''),
  }
}

export async function deleteQuotationLine(lineId: string, etag: string): Promise<string> {
  const response = await apiClient.delete(`/api/v1/quotation-lines/${lineId}/`, { headers: { 'If-Match': etag } })
  return String(response.headers.etag || '')
}

export async function uploadQuotationLineProductImage(lineId: string, file: File, etag: string): Promise<{ data: QuotationLine; etag: string }> {
  const body = new FormData()
  body.append('file', file)
  return withEtag<QuotationLine>(await apiClient.post(`/api/v1/quotation-lines/${lineId}/product-image/`, body, {
    headers: { 'If-Match': etag },
    timeout: 120_000,
  }))
}

export interface QuotationInquiryImage { id: string; name: string; url: string }
export async function fetchQuotationInquiryImages(quotationId: string): Promise<QuotationInquiryImage[]> {
  const response=await apiClient.get<{data: QuotationInquiryImage[]}>(`/api/v1/quotations/${quotationId}/inquiry-images/`)
  return response.data.data
}
export async function selectQuotationInquiryImage(lineId: string, imageId: string, etag: string) {
  return withEtag<QuotationLine>(await apiClient.post(`/api/v1/quotation-lines/${lineId}/product-image/`, {source_image_id:imageId}, {headers:{'If-Match':etag}}))
}

export async function deleteQuotationLineProductImage(lineId: string, etag: string): Promise<string> {
  const response = await apiClient.delete(`/api/v1/quotation-lines/${lineId}/product-image/`, { headers: { 'If-Match': etag } })
  return String(response.headers.etag || '')
}

export function quotationLineProductImageUrl(lineId: string): string {
  const base = apiClient.defaults.baseURL || ''
  return `${base}/api/v1/quotation-lines/${encodeURIComponent(lineId)}/product-image/`
}

export async function downloadSampleInvoice(versionId: string, etag: string): Promise<{ blob: Blob; etag: string; filename: string }> {
  const response = await apiClient.post(`/api/v1/quotation-versions/${versionId}/generate-sample-invoice/`, {}, {
    headers: { 'If-Match': etag }, responseType: 'blob', timeout: 120_000,
  })
  const header = String(response.headers['content-disposition'] || '')
  const matched = /filename="?([^";]+)"?/i.exec(header)
  return { blob: response.data as Blob, etag: String(response.headers.etag || ''), filename: matched?.[1] || 'sample_invoice_demo.xlsx' }
}

export async function simulateQuotationDispatch(versionId: string, payload: { recipient?: string; notes?: string }, etag: string): Promise<VersionResponse> {
  return withEtag<QuotationVersionDetail>(await apiClient.post(`/api/v1/quotation-versions/${versionId}/simulate-dispatch/`, payload, { headers: { 'If-Match': etag } }))
}

export async function saveQuotationPriceMatrix(versionId: string, priceBases: QuotationPriceBasisPayload[], etag: string): Promise<VersionResponse> {
  return withEtag<QuotationVersionDetail>(await apiClient.put(
    `/api/v1/quotation-versions/${versionId}/price-matrix/`,
    { price_bases: priceBases },
    { headers: { 'If-Match': etag } },
  ))
}

export async function uploadFormalQuotationDocument(versionId: string, file: File, etag: string): Promise<VersionResponse> {
  const body = new FormData()
  body.append('file', file)
  return withEtag<QuotationVersionDetail>(await apiClient.post(
    `/api/v1/quotation-versions/${versionId}/formal-document/`,
    body,
    { headers: { 'If-Match': etag }, timeout: 120_000 },
  ))
}

export async function generateFormalQuotationPdf(versionId: string, etag: string): Promise<VersionResponse> {
  return withEtag<QuotationVersionDetail>(await apiClient.post(
    `/api/v1/quotation-versions/${versionId}/generate-formal-pdf/`,
    {},
    { headers: { 'If-Match': etag }, timeout: 120_000 },
  ))
}

export async function downloadFormalQuotationDocument(versionId: string): Promise<{ blob: Blob; filename: string }> {
  const response = await apiClient.get(
    `/api/v1/quotation-versions/${versionId}/formal-document-download/`,
    { responseType: 'blob', timeout: 120_000 },
  )
  const header = String(response.headers['content-disposition'] || '')
  const encodedMatch = /filename\*=UTF-8''([^;]+)/i.exec(header)
  const plainMatch = /filename="?([^";]+)"?/i.exec(header)
  const filename = encodedMatch
    ? decodeURIComponent(encodedMatch[1])
    : plainMatch?.[1] || 'quotation.pdf'
  return { blob: response.data as Blob, filename }
}

export async function downloadFormalQuotationXlsx(versionId: string): Promise<{ blob: Blob; filename: string }> {
  const response = await apiClient.get(
    `/api/v1/quotation-versions/${versionId}/formal-xlsx-download/`,
    { responseType: 'blob', timeout: 120_000 },
  )
  const header = String(response.headers['content-disposition'] || '')
  const encodedMatch = /filename\*=UTF-8''([^;]+)/i.exec(header)
  const plainMatch = /filename="?([^";]+)"?/i.exec(header)
  const filename = encodedMatch
    ? decodeURIComponent(encodedMatch[1])
    : plainMatch?.[1] || 'quotation.xlsx'
  return { blob: response.data as Blob, filename }
}

export async function confirmManualQuotationDispatch(versionId: string, payload: {
  price_basis_id: string
  recipient_snapshot: Record<string, unknown>
  evidence_file_id?: string | null
  external_reference?: string
  evidence_note?: string
  follow_up_due_at?: string | null
}, etag: string): Promise<VersionResponse> {
  return withEtag<QuotationVersionDetail>(await apiClient.post(
    `/api/v1/quotation-versions/${versionId}/manual-dispatch/`, payload, { headers: { 'If-Match': etag } },
  ))
}

export async function sendQuotationEmail(versionId: string, payload: {
  idempotency_key: string
  price_basis_id: string
  recipient: string
  cc?: string[]
  subject: string
  body: string
  follow_up_due_at?: string | null
}, etag: string): Promise<QuotationEmailDispatchResponse> {
  const response = await apiClient.post<{ data: QuotationVersionDetail; email_attempt: QuotationEmailDispatchAttempt }>(
    `/api/v1/quotation-versions/${versionId}/email-dispatch/`, payload, { headers: { 'If-Match': etag } },
  )
  return {
    data: response.data.data,
    emailAttempt: response.data.email_attempt,
    etag: String(response.headers.etag || ''),
  }
}

export async function fetchQuotationEmailAttempts(versionId: string, idempotencyKey?: string): Promise<QuotationEmailDispatchAttempt[]> {
  return unwrap(await apiClient.get<ApiDataResponse<QuotationEmailDispatchAttempt[]>>(
    `/api/v1/quotation-versions/${versionId}/email-attempts/`,
    { params: idempotencyKey ? { idempotency_key: idempotencyKey } : undefined },
  ))
}

export async function resolveQuotationEmailAttempt(
  attemptId: string,
  payload: { result: 'ACCEPTED' | 'NOT_SENT'; note: string },
  etag: string,
): Promise<QuotationEmailDispatchResponse> {
  const response = await apiClient.post<{ data: QuotationVersionDetail; email_attempt: QuotationEmailDispatchAttempt }>(
    `/api/v1/quotation-email-attempts/${attemptId}/resolve/`,
    payload,
    { headers: { 'If-Match': etag } },
  )
  return {
    data: response.data.data,
    emailAttempt: response.data.email_attempt,
    etag: String(response.headers.etag || ''),
  }
}

export async function acceptQuotation(quotationId: string, payload: {
  accepted_version_id: string
  price_basis_id: string
  customer_contact_id?: string | null
  accepted_at: string
  source: 'EMAIL' | 'PHONE' | 'MEETING' | 'OTHER'
  note?: string
}, etag: string): Promise<QuotationResponse> {
  return withEtag<QuotationDetail>(await apiClient.post(
    `/api/v1/quotations/${quotationId}/accept/`, payload, { headers: { 'If-Match': etag } },
  ))
}

export async function fetchQuotationLinePackaging(lineId: string): Promise<{ data: QuotationLinePackaging | null; etag: string }> {
  return withEtag<QuotationLinePackaging | null>(await apiClient.get(`/api/v1/quotation-lines/${lineId}/packaging/`))
}

export async function saveQuotationLinePackaging(lineId: string, payload: Omit<QuotationLinePackaging, 'id' | 'carton_cbm' | 'total_cbm'>, etag: string): Promise<{ data: QuotationLinePackaging; etag: string }> {
  return withEtag<QuotationLinePackaging>(await apiClient.put(`/api/v1/quotation-lines/${lineId}/packaging/`, payload, { headers: { 'If-Match': etag } }))
}

export async function fetchContainerOptions(lineId: string): Promise<QuotationContainerConfig[]> {
  return unwrap(await apiClient.get<ApiDataResponse<QuotationContainerConfig[]>>(`/api/v1/quotation-lines/${lineId}/container-options/`))
}

export async function fetchContainerTiers(lineId: string): Promise<{ data: QuotationContainerTier[]; etag: string }> {
  return withEtag<QuotationContainerTier[]>(await apiClient.get(`/api/v1/quotation-lines/${lineId}/container-tiers/`))
}

export async function createContainerTier(lineId: string, payload: {
  container_type_code: string
  effective_volume_cbm: string
  load_factor: string
  unit_price: string
}, etag: string): Promise<{ data: QuotationContainerTier; etag: string }> {
  return withEtag<QuotationContainerTier>(await apiClient.post(`/api/v1/quotation-lines/${lineId}/container-tiers/`, payload, { headers: { 'If-Match': etag } }))
}

export async function deleteContainerTier(tierId: string, etag: string): Promise<string> {
  const response = await apiClient.delete(`/api/v1/quotation-container-tiers/${tierId}/`, { headers: { 'If-Match': etag } })
  return String(response.headers.etag || '')
}
