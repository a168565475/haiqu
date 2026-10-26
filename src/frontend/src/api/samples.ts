import type { AxiosResponse } from 'axios'

import { apiClient } from './request'
import type { ApiDataResponse } from '@/types/customer'
import type {
  SampleCreateInput,
  SampleFromInquiryCreateInput,
  SampleFromQuotationCreateInput,
  SampleListQuery,
  SampleListResult,
  SampleListItem,
  SampleOptions,
  SampleFormContext,
  SampleFormOptions,
  SampleRequestFormInput,
  SampleStats,
  SampleDetail,
  SampleDetailUpdateInput,
  SampleItemDetail,
  SampleFeeApproval,
  SampleFeeCreateInput,
  SampleFeeRecord,
  SampleFeedback,
  SampleFeedbackCreateInput,
  SampleRequotationCreateInput,
  SampleRequotationOption,
  SampleRequotationResult,
  SampleShipInput,
  SampleShipment,
  SampleShipmentCreateInput,
  SampleShipmentProgressInput,
  SampleInventoryOptions,
  SampleInventoryEligibleResult,
  SampleFinishedGoodsDestination,
  SampleFinishedGoodsOptions,
  SampleInventoryReceiptCreated,
  SampleInventoryReceiptDetail,
  SampleInventoryReceiptLineInput,
  SampleInventoryQuery,
  SampleInventoryResult,
  SampleInventorySummary,
  SampleOutboundOptions,
  SampleOutboundEligibleResult,
  SampleOutboundCreateLineInput,
  SampleOutboundCreated,
  SampleOutboundDetail,
  SampleOutboundQuery,
  SampleOutboundResult,
  SampleOutboundSummary,
  SampleLoanOptions,
  SampleLoanCreateLineInput,
  SampleLoanCreated,
  SampleLoanDetail,
  SampleLoanEligibleResult,
  SampleLoanQuery,
  SampleLoanResult,
  SampleLoanSummary,
} from '@/types/sample'

function unwrap<T>(response: AxiosResponse<ApiDataResponse<T>>): T {
  return response.data.data
}

export async function fetchSamples(query: SampleListQuery, signal?: AbortSignal): Promise<SampleListResult> {
  const { data } = await apiClient.get<SampleListResult>('/api/v1/sample-requests/', {
    params: sampleQueryParams(query), ...(signal ? { signal } : {}),
  })
  return data
}

// DRF 全局 SEARCH_PARAM 为 q；页面和历史保存视图继续使用已有 search 字段。
function sampleQueryParams(query: Partial<SampleListQuery>) {
  const { search, ...params } = query
  return { ...params, ...(search?.trim() ? { q: search.trim() } : {}) }
}

export async function fetchSampleInventory(query: SampleInventoryQuery): Promise<SampleInventoryResult> {
  const { data } = await apiClient.get<SampleInventoryResult>('/api/v1/sample-inventory/', { params: query })
  return data
}

export async function fetchSampleInventorySummary(): Promise<SampleInventorySummary> {
  return unwrap(await apiClient.get<ApiDataResponse<SampleInventorySummary>>('/api/v1/sample-inventory/summary/'))
}

export async function fetchSampleInventoryOptions(): Promise<SampleInventoryOptions> {
  return unwrap(await apiClient.get<ApiDataResponse<SampleInventoryOptions>>('/api/v1/sample-inventory/options/'))
}

export async function fetchSampleInventoryEligible(page = 1): Promise<SampleInventoryEligibleResult> {
  if (!Number.isSafeInteger(page) || page < 1) throw new RangeError('候选样品页码必须为正整数。')
  const { data } = await apiClient.get<SampleInventoryEligibleResult>('/api/v1/sample-inventory/eligible/', {
    params: { page, page_size: 100 },
  })
  return data
}

export async function fetchSampleFinishedGoodsOptions(): Promise<SampleFinishedGoodsOptions> {
  return unwrap(await apiClient.get<ApiDataResponse<SampleFinishedGoodsOptions>>(
    '/api/v1/sample-inventory/finished-goods-options/',
  ))
}

export async function createSampleInventoryReceipt(
  items: SampleInventoryReceiptLineInput[],
  finishedGoodsDestination: SampleFinishedGoodsDestination,
): Promise<SampleInventoryReceiptCreated> {
  return unwrap(await apiClient.post<ApiDataResponse<SampleInventoryReceiptCreated>>(
    '/api/v1/sample-inventory/receipts/',
    { items, finished_goods_destination: finishedGoodsDestination },
  ))
}

export async function fetchSampleInventoryReceiptDetail(
  receiptId: string,
): Promise<SampleInventoryReceiptDetail> {
  return unwrap(await apiClient.get<ApiDataResponse<SampleInventoryReceiptDetail>>(
    `/api/v1/sample-inventory/receipts/${receiptId}/`,
  ))
}

export async function deleteSampleInventoryReceipt(receiptId: string): Promise<void> {
  await apiClient.delete(`/api/v1/sample-inventory/receipts/${receiptId}/`)
}

export async function fetchSampleOutbound(query: SampleOutboundQuery): Promise<SampleOutboundResult> {
  const { data } = await apiClient.get<SampleOutboundResult>('/api/v1/sample-outbound/', { params: query })
  return data
}

export async function fetchSampleOutboundSummary(): Promise<SampleOutboundSummary> {
  return unwrap(await apiClient.get<ApiDataResponse<SampleOutboundSummary>>('/api/v1/sample-outbound/summary/'))
}

export async function fetchSampleOutboundOptions(): Promise<SampleOutboundOptions> {
  return unwrap(await apiClient.get<ApiDataResponse<SampleOutboundOptions>>('/api/v1/sample-outbound/options/'))
}

export async function fetchSampleOutboundEligible(page = 1): Promise<SampleOutboundEligibleResult> {
  if (!Number.isSafeInteger(page) || page < 1) throw new RangeError('页码必须为正整数')
  const { data } = await apiClient.get<SampleOutboundEligibleResult>('/api/v1/sample-outbound/eligible/', {
    params: { page, page_size: 100 },
  })
  return data
}

export async function createSampleOutbound(
  items: SampleOutboundCreateLineInput[],
): Promise<SampleOutboundCreated> {
  return unwrap(await apiClient.post<ApiDataResponse<SampleOutboundCreated>>(
    '/api/v1/sample-outbound/documents/',
    { items },
  ))
}

export async function fetchSampleOutboundDetail(
  outboundId: string,
): Promise<SampleOutboundDetail> {
  return unwrap(await apiClient.get<ApiDataResponse<SampleOutboundDetail>>(
    `/api/v1/sample-outbound/documents/${outboundId}/`,
  ))
}

export async function deleteSampleOutbound(outboundId: string): Promise<void> {
  await apiClient.delete(`/api/v1/sample-outbound/documents/${outboundId}/`)
}

export async function fetchSampleLoans(query: SampleLoanQuery): Promise<SampleLoanResult> {
  const { data } = await apiClient.get<SampleLoanResult>('/api/v1/sample-loans/', { params: query })
  return data
}

export async function fetchSampleLoanSummary(): Promise<SampleLoanSummary> {
  return unwrap(await apiClient.get<ApiDataResponse<SampleLoanSummary>>('/api/v1/sample-loans/summary/'))
}

export async function fetchSampleLoanOptions(): Promise<SampleLoanOptions> {
  return unwrap(await apiClient.get<ApiDataResponse<SampleLoanOptions>>('/api/v1/sample-loans/options/'))
}

export async function fetchSampleLoanEligible(page = 1): Promise<SampleLoanEligibleResult> {
  if (!Number.isSafeInteger(page) || page < 1) throw new RangeError('页码必须为正整数')
  const { data } = await apiClient.get<SampleLoanEligibleResult>('/api/v1/sample-loans/eligible/', {
    params: { page, page_size: 100 },
  })
  return data
}

export async function createSampleLoan(
  items: SampleLoanCreateLineInput[],
): Promise<SampleLoanCreated> {
  return unwrap(await apiClient.post<ApiDataResponse<SampleLoanCreated>>(
    '/api/v1/sample-loans/documents/',
    { items },
  ))
}

export async function fetchSampleLoanDetail(loanId: string): Promise<SampleLoanDetail> {
  return unwrap(await apiClient.get<ApiDataResponse<SampleLoanDetail>>(
    `/api/v1/sample-loans/documents/${loanId}/`,
  ))
}

export async function deleteSampleLoan(loanId: string): Promise<void> {
  await apiClient.delete(`/api/v1/sample-loans/documents/${loanId}/`)
}

export async function fetchSampleStats(query?: Partial<SampleListQuery>): Promise<SampleStats> {
  return unwrap(await apiClient.get<ApiDataResponse<SampleStats>>('/api/v1/sample-requests/summary/', query ? { params: sampleQueryParams(query) } : undefined))
}

export async function fetchSampleOptions(): Promise<SampleOptions> {
  return unwrap(await apiClient.get<ApiDataResponse<SampleOptions>>('/api/v1/sample-requests/options/'))
}

export async function fetchSampleFormOptions(): Promise<SampleFormOptions> {
  return unwrap(await apiClient.get<ApiDataResponse<SampleFormOptions>>('/api/v1/sample-requests/form-options/'))
}

export async function fetchSampleFormContext(
  sourceType: 'inquiry' | 'quotation',
  sourceId: string,
): Promise<SampleFormContext> {
  return unwrap(await apiClient.get<ApiDataResponse<SampleFormContext>>(
    '/api/v1/sample-requests/form-context/',
    { params: { sourceType, sourceId } },
  ))
}

function sampleFormData(
  payload: SampleRequestFormInput,
  taskFiles: Record<string, File | null>,
  samplingImageFiles: Record<string, File | null>,
): FormData {
  const body = new FormData()
  body.append('payload', JSON.stringify(payload))
  for (const [clientKey, file] of Object.entries(taskFiles)) {
    if (file) body.append(`task_sheet_${clientKey}`, file)
  }
  for (const [clientKey, file] of Object.entries(samplingImageFiles)) {
    if (file) body.append(`sampling_image_${clientKey}`, file)
  }
  return body
}

export async function submitSampleForm(
  payload: SampleRequestFormInput,
  taskFiles: Record<string, File | null>,
  samplingImageFiles: Record<string, File | null>,
): Promise<{ data: SampleDetail; etag: string }> {
  const response = await apiClient.post<ApiDataResponse<SampleDetail>>(
    '/api/v1/sample-requests/',
    sampleFormData(payload, taskFiles, samplingImageFiles),
    { timeout: 120_000 },
  )
  return { data: unwrap(response), etag: response.headers.etag || '' }
}

export async function patchSampleForm(
  sampleId: string,
  payload: SampleRequestFormInput,
  taskFiles: Record<string, File | null>,
  samplingImageFiles: Record<string, File | null>,
  etag: string,
): Promise<{ data: SampleDetail; etag: string }> {
  const response = await apiClient.patch<ApiDataResponse<SampleDetail>>(
    `/api/v1/sample-requests/${encodeURIComponent(sampleId)}/form/`,
    sampleFormData(payload, taskFiles, samplingImageFiles),
    { headers: { 'If-Match': etag }, timeout: 120_000 },
  )
  return { data: unwrap(response), etag: response.headers.etag || '' }
}

export async function createSample(payload: SampleCreateInput): Promise<SampleListItem> {
  return unwrap(await apiClient.post<ApiDataResponse<SampleListItem>>('/api/v1/sample-requests/', payload))
}

export async function createSampleFromInquiry(payload: SampleFromInquiryCreateInput): Promise<SampleDetail> {
  return unwrap(await apiClient.post<ApiDataResponse<SampleDetail>>('/api/v1/sample-requests/create-from-inquiry/', payload))
}

export async function createSampleFromQuotation(payload: SampleFromQuotationCreateInput): Promise<SampleDetail> {
  return unwrap(await apiClient.post<ApiDataResponse<SampleDetail>>('/api/v1/sample-requests/create-from-quotation/', payload))
}

export async function fetchSample(sampleId: string): Promise<{ data: SampleDetail; etag: string }> {
  const response = await apiClient.get<ApiDataResponse<SampleDetail>>(`/api/v1/sample-requests/${sampleId}/`)
  return { data: unwrap(response), etag: response.headers.etag || '' }
}

function workflowFormData(note: string, file?: File | null): FormData {
  const body = new FormData()
  body.append('note', note)
  if (file) body.append('file', file)
  return body
}

async function postSampleWorkflow(
  sampleId: string,
  action: string,
  etag: string,
  body: FormData | { note: string },
): Promise<{ data: SampleDetail; etag: string }> {
  const response = await apiClient.post<ApiDataResponse<SampleDetail>>(
    `/api/v1/sample-requests/${encodeURIComponent(sampleId)}/${action}/`,
    body,
    { headers: { 'If-Match': etag }, timeout: 120_000 },
  )
  return { data: unwrap(response), etag: String(response.headers.etag || '') }
}

export function confirmSampleFinance(
  sampleId: string,
  note: string,
  file: File | null,
  etag: string,
) {
  return postSampleWorkflow(sampleId, 'finance-confirm', etag, workflowFormData(note, file))
}

export function approveSamplePmc(sampleId: string, etag: string, note = '') {
  return postSampleWorkflow(sampleId, 'pmc-approve', etag, { note })
}

export function uploadSampleParameters(
  sampleId: string,
  parameterType: 'metalwork' | 'cutting',
  note: string,
  file: File,
  etag: string,
) {
  const action = parameterType === 'metalwork' ? 'metalwork-parameters' : 'cutting-parameters'
  return postSampleWorkflow(sampleId, action, etag, workflowFormData(note, file))
}

export function uploadSampleParameterImage(
  sampleId: string,
  parameterType: 'metalwork' | 'cutting',
  file: File,
  etag: string,
) {
  const action = parameterType === 'metalwork' ? 'metalwork-parameters' : 'cutting-parameters'
  return postSampleWorkflow(sampleId, action, etag, workflowFormData('', file))
}

export async function deleteSampleParameterImage(
  sampleId: string,
  imageId: string,
  etag: string,
): Promise<{ data: SampleDetail; etag: string }> {
  const response = await apiClient.delete<ApiDataResponse<SampleDetail>>(
    `/api/v1/sample-requests/${encodeURIComponent(sampleId)}/parameter-images/${encodeURIComponent(imageId)}/`,
    { headers: { 'If-Match': etag } },
  )
  return { data: unwrap(response), etag: String(response.headers.etag || '') }
}

export async function fetchSampleBusinessFile(sampleId: string, fileId: string): Promise<Blob> {
  const response = await apiClient.get(
    `/api/v1/sample-requests/${encodeURIComponent(sampleId)}/business-files/${encodeURIComponent(fileId)}/`,
    { responseType: 'blob', timeout: 120_000 },
  )
  return response.data as Blob
}

export async function deleteSample(sampleId: string, etag: string): Promise<{ deleted_count: number }> {
  return unwrap(await apiClient.delete<ApiDataResponse<{ deleted_count: number }>>(
    `/api/v1/sample-requests/${encodeURIComponent(sampleId)}/`,
    { headers: { 'If-Match': etag } },
  ))
}

export async function updateSample(sampleId: string, payload: SampleDetailUpdateInput, etag: string): Promise<{ data: SampleDetail; etag: string }> {
  const response = await apiClient.patch<ApiDataResponse<SampleDetail>>(`/api/v1/sample-requests/${sampleId}/`, payload, { headers: { 'If-Match': etag } })
  return { data: unwrap(response), etag: response.headers.etag || '' }
}

export async function transitionSample(sampleId: string, action: 'submit' | 'start-preparing' | 'confirm' | 'reject' | 'cancel', etag: string, note = ''): Promise<{ data: SampleDetail; etag: string }> {
  const field = action === 'reject' || action === 'cancel' ? { reason: note } : { note }
  const response = await apiClient.post<ApiDataResponse<SampleDetail>>(`/api/v1/sample-requests/${sampleId}/${action}/`, field, { headers: { 'If-Match': etag } })
  return { data: unwrap(response), etag: response.headers.etag || '' }
}

export async function addSampleItem(sampleId: string, payload: Omit<SampleItemDetail, 'id' | 'source_inquiry_item' | 'source_quotation_line'>, etag: string): Promise<{ data: SampleItemDetail; etag: string }> {
  const response = await apiClient.post<ApiDataResponse<SampleItemDetail>>(`/api/v1/sample-requests/${sampleId}/items/`, payload, { headers: { 'If-Match': etag } })
  return { data: unwrap(response), etag: response.headers.etag || '' }
}

export async function createSampleFeeRecord(sampleId: string, payload: SampleFeeCreateInput, etag: string): Promise<{ data: SampleFeeRecord; etag: string }> {
  const response = await apiClient.post<ApiDataResponse<SampleFeeRecord>>(`/api/v1/sample-requests/${sampleId}/fee-records/`, payload, { headers: { 'If-Match': etag } })
  return { data: unwrap(response), etag: response.headers.etag || '' }
}

export async function uploadSampleFeeEvidence(sampleId: string, file: File, etag: string): Promise<{ etag: string }> {
  const body = new FormData()
  body.append('file', file)
  const response = await apiClient.post(
    `/api/v1/sample-requests/${encodeURIComponent(sampleId)}/fee-evidence/`,
    body,
    { headers: { 'If-Match': etag }, timeout: 120_000 },
  )
  return { etag: String(response.headers.etag || '') }
}

export async function decideSampleFeeWaiver(sampleId: string, approvalId: string, approved: boolean, etag: string, note = ''): Promise<{ data: { fee_record: SampleFeeRecord; approval: SampleFeeApproval }; etag: string }> {
  const action = approved ? 'approve' : 'reject'
  const response = await apiClient.post<ApiDataResponse<{ fee_record: SampleFeeRecord; approval: SampleFeeApproval }>>(
    `/api/v1/sample-requests/${sampleId}/fee-approval/${action}/`,
    { approval_id: approvalId, note },
    { headers: { 'If-Match': etag } },
  )
  return { data: unwrap(response), etag: response.headers.etag || '' }
}

export async function fetchSampleShipment(shipmentId: string): Promise<{ data: SampleShipment; etag: string }> {
  const response = await apiClient.get<ApiDataResponse<SampleShipment>>(`/api/v1/sample-shipments/${shipmentId}/`)
  return { data: unwrap(response), etag: response.headers.etag || '' }
}

export async function createSampleShipment(sampleId: string, payload: SampleShipmentCreateInput, etag: string): Promise<{ data: SampleShipment; etag: string; sampleEtag: string }> {
  const response = await apiClient.post<ApiDataResponse<SampleShipment>>(
    `/api/v1/sample-requests/${sampleId}/shipments/`,
    payload,
    { headers: { 'If-Match': etag } },
  )
  return { data: unwrap(response), etag: response.headers.etag || '', sampleEtag: response.headers['sample-request-etag'] || '' }
}

export async function shipSampleShipment(shipmentId: string, payload: SampleShipInput, etag: string): Promise<{ data: SampleShipment; etag: string; sampleEtag: string }> {
  const response = await apiClient.post<ApiDataResponse<SampleShipment>>(
    `/api/v1/sample-shipments/${shipmentId}/ship/`,
    payload,
    { headers: { 'If-Match': etag } },
  )
  return { data: unwrap(response), etag: response.headers.etag || '', sampleEtag: response.headers['sample-request-etag'] || '' }
}

export async function deliverSampleShipment(shipmentId: string, note: string, etag: string): Promise<{ data: SampleShipment; etag: string; sampleEtag: string }> {
  const response = await apiClient.post<ApiDataResponse<SampleShipment>>(
    `/api/v1/sample-shipments/${shipmentId}/deliver/`,
    { note },
    { headers: { 'If-Match': etag } },
  )
  return { data: unwrap(response), etag: response.headers.etag || '', sampleEtag: response.headers['sample-request-etag'] || '' }
}

export async function markSampleShipmentException(shipmentId: string, reason: string, etag: string): Promise<{ data: SampleShipment; etag: string; sampleEtag: string }> {
  const response = await apiClient.post<ApiDataResponse<SampleShipment>>(
    `/api/v1/sample-shipments/${shipmentId}/exception/`,
    { reason },
    { headers: { 'If-Match': etag } },
  )
  return { data: unwrap(response), etag: response.headers.etag || '', sampleEtag: response.headers['sample-request-etag'] || '' }
}

export async function recordSampleShipmentProgress(shipmentId: string, payload: SampleShipmentProgressInput, etag: string): Promise<{ data: SampleShipment; etag: string; sampleEtag: string }> {
  const response = await apiClient.post<ApiDataResponse<SampleShipment>>(
    `/api/v1/sample-shipments/${shipmentId}/progress/`,
    payload,
    { headers: { 'If-Match': etag } },
  )
  return { data: unwrap(response), etag: response.headers.etag || '', sampleEtag: response.headers['sample-request-etag'] || '' }
}

export async function createSampleFeedback(sampleId: string, payload: SampleFeedbackCreateInput, etag: string): Promise<{ data: SampleFeedback; etag: string }> {
  const response = await apiClient.post<ApiDataResponse<SampleFeedback>>(
    `/api/v1/sample-requests/${sampleId}/feedback/`,
    payload,
    { headers: { 'If-Match': etag } },
  )
  return { data: unwrap(response), etag: response.headers.etag || '' }
}

export async function fetchSampleFeedbackRequotationOptions(
  sampleId: string,
  feedbackId: string,
): Promise<{ data: SampleRequotationOption[]; etag: string }> {
  const response = await apiClient.get<ApiDataResponse<SampleRequotationOption[]>>(
    `/api/v1/sample-requests/${sampleId}/feedback/${feedbackId}/requotation-options/`,
  )
  return { data: unwrap(response), etag: response.headers.etag || '' }
}

export async function createSampleFeedbackRequotation(
  sampleId: string,
  feedbackId: string,
  payload: SampleRequotationCreateInput,
  etag: string,
): Promise<{ data: SampleRequotationResult; etag: string }> {
  const response = await apiClient.post<ApiDataResponse<SampleRequotationResult>>(
    `/api/v1/sample-requests/${sampleId}/feedback/${feedbackId}/create-requotation/`,
    payload,
    { headers: { 'If-Match': etag } },
  )
  return { data: unwrap(response), etag: response.headers.etag || '' }
}

export async function exportSamples(query: SampleListQuery): Promise<Blob> {
  const response = await apiClient.get('/api/v1/sample-requests/export/', {
    params: sampleQueryParams(query),
    responseType: 'blob',
  })
  return response.data as Blob
}

export async function bulkTransferSamples(payload: {
  sample_ids: string[]
  etags: Record<string, string>
  owner_employee_id: string
  note: string
}): Promise<{ updated_count: number }> {
  return unwrap(await apiClient.post('/api/v1/sample-requests/bulk-transfer/', payload))
}

export async function bulkRemindSamples(payload: {
  sample_ids: string[]
  etags: Record<string, string>
  note?: string
}): Promise<{ task_count: number; task_ids: string[] }> {
  return unwrap(await apiClient.post('/api/v1/sample-requests/bulk-remind/', payload))
}

export async function reportSampleProduction(sampleId: string, etag: string, items: import('@/types/sample').SampleProductionReportItem[]): Promise<{ data: SampleDetail; etag: string }> {
  if (!sampleId || !etag) throw new Error('缺少样品或数据版本，请刷新后重试。')
  const response = await apiClient.post<ApiDataResponse<SampleDetail>>(`/api/v1/sample-requests/${sampleId}/production-report/`, { items }, { headers: { 'If-Match': etag } })
  return { data: unwrap(response), etag: response.headers.etag || '' }
}
