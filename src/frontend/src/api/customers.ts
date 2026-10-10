import type { AxiosResponse } from 'axios'

import { apiClient } from './request'
import type {
  ApiDataResponse,
  CursorPaginatedResponse,
  CustomerActivityChangeInput,
  CustomerActivitySummary,
  CustomerBusinessSnapshot,
  CustomerBusinessSnapshotInput,
  CustomerAddress,
  CustomerAddressInput,
  CustomerBulkResult,
  CustomerBulkTagInput,
  CustomerClassificationChangeInput,
  CustomerClassificationResult,
  CustomerCreateInput,
  CustomerDetail,
  CustomerDuplicateCase,
  CustomerDuplicateCheckQuery,
  CustomerDuplicateCheckResult,
  CustomerEffectiveSummary,
  CustomerEntity,
  CustomerEntityInput,
  CustomerGradeChangeInput,
  CustomerListItem,
  CustomerListQuery,
  CustomerOptions,
  CustomerOptionsQuery,
  CustomerSourceChangeInput,
  CustomerSourceSummary,
  CustomerSummary,
  CustomerStats,
  CustomerTagCreateInput,
  CustomerTagOption,
  CustomerTimelineEvent,
  CustomerTimelineQuery,
  CustomerUpdateInput,
  CustomerTransferInput,
  CustomerTransferRequest,
  CustomerMergePreview,
  PaginatedResponse,
  VersionedCustomer,
} from '@/types/customer'

const customersPath = '/api/v1/customers/'

function customerPath(customerId: string, suffix = ''): string {
  return `${customersPath}${encodeURIComponent(customerId)}/${suffix}`
}

function unwrapData<T>(response: AxiosResponse<ApiDataResponse<T>>): T {
  return response.data.data
}

function unwrapVersionedCustomer(
  response: AxiosResponse<ApiDataResponse<CustomerDetail>>,
): VersionedCustomer<CustomerDetail> {
  return {
    data: response.data.data,
    etag: typeof response.headers.etag === 'string' ? response.headers.etag : null,
  }
}

export async function fetchCustomers(
  params: CustomerListQuery = {},
): Promise<PaginatedResponse<CustomerListItem>> {
  const { data } = await apiClient.get<PaginatedResponse<CustomerListItem>>(customersPath, {
    params,
  })
  return data
}

export async function fetchCustomerOptions(
  params: CustomerOptionsQuery = {},
): Promise<CustomerOptions> {
  const response = await apiClient.get<ApiDataResponse<CustomerOptions>>(
    `${customersPath}options/`,
    { params },
  )
  return unwrapData(response)
}

export async function createCustomerTag(
  payload: CustomerTagCreateInput,
): Promise<CustomerTagOption> {
  const response = await apiClient.post<ApiDataResponse<CustomerTagOption>>(
    `${customersPath}tags/`,
    payload,
  )
  return unwrapData(response)
}

export async function fetchCustomerStats(): Promise<CustomerStats> {
  const response = await apiClient.get<ApiDataResponse<CustomerStats>>(`${customersPath}stats/`)
  return unwrapData(response)
}

export async function exportCustomers(params: CustomerListQuery = {}): Promise<Blob> {
  const response = await apiClient.get(`${customersPath}export/`, {
    params,
    responseType: 'blob',
  })
  return response.data as Blob
}

export async function bulkAddCustomerTags(
  payload: CustomerBulkTagInput,
): Promise<CustomerBulkResult> {
  const response = await apiClient.post<ApiDataResponse<CustomerBulkResult>>(
    `${customersPath}bulk-add-tags/`,
    payload,
  )
  return unwrapData(response)
}

export async function createCustomerTransferRequest(payload: CustomerTransferInput): Promise<void> {
  await apiClient.post('/api/v1/customer-transfer-requests/', payload)
}

export async function checkCustomerDuplicates(
  params: CustomerDuplicateCheckQuery,
): Promise<CustomerDuplicateCheckResult> {
  const response = await apiClient.get<ApiDataResponse<CustomerDuplicateCheckResult>>(
    `${customersPath}duplicate-check/`,
    { params },
  )
  return unwrapData(response)
}

export async function createCustomer(
  payload: CustomerCreateInput,
): Promise<VersionedCustomer<CustomerDetail>> {
  const response = await apiClient.post<ApiDataResponse<CustomerDetail>>(customersPath, payload)
  return unwrapVersionedCustomer(response)
}

export async function fetchCustomer(
  customerId: string,
): Promise<VersionedCustomer<CustomerDetail>> {
  const response = await apiClient.get<ApiDataResponse<CustomerDetail>>(customerPath(customerId))
  return unwrapVersionedCustomer(response)
}

export async function deleteCustomer(customerId: string, etag: string): Promise<{ deleted_count: number }> {
  const response = await apiClient.delete<ApiDataResponse<{ deleted_count: number }>>(
    customerPath(customerId),
    { headers: { 'If-Match': etag } },
  )
  return unwrapData(response)
}

export async function updateCustomer(
  customerId: string,
  payload: CustomerUpdateInput,
  etag: string,
): Promise<VersionedCustomer<CustomerDetail>> {
  const response = await apiClient.patch<ApiDataResponse<CustomerDetail>>(
    customerPath(customerId),
    payload,
    { headers: { 'If-Match': etag } },
  )
  return unwrapVersionedCustomer(response)
}

export async function fetchCustomerSummary(customerId: string): Promise<CustomerSummary> {
  const response = await apiClient.get<ApiDataResponse<CustomerSummary>>(
    customerPath(customerId, 'summary/'),
  )
  return unwrapData(response)
}

export async function fetchCustomerTimeline(
  customerId: string,
  params: CustomerTimelineQuery = {},
): Promise<CursorPaginatedResponse<CustomerTimelineEvent>> {
  const { data } = await apiClient.get<CursorPaginatedResponse<CustomerTimelineEvent>>(
    customerPath(customerId, 'timeline/'),
    { params },
  )
  return data
}

export async function fetchCustomerGradeHistory(
  customerId: string,
): Promise<CustomerEffectiveSummary[]> {
  const response = await apiClient.get<ApiDataResponse<CustomerEffectiveSummary[]>>(
    customerPath(customerId, 'grade-history/'),
  )
  return unwrapData(response)
}

export async function setCustomerGrade(
  customerId: string,
  payload: CustomerGradeChangeInput,
): Promise<CustomerEffectiveSummary> {
  const response = await apiClient.post<ApiDataResponse<CustomerEffectiveSummary>>(
    customerPath(customerId, 'set-grade/'),
    payload,
  )
  return unwrapData(response)
}

export async function fetchCustomerSourceHistory(
  customerId: string,
): Promise<CustomerSourceSummary[]> {
  const response = await apiClient.get<ApiDataResponse<CustomerSourceSummary[]>>(
    customerPath(customerId, 'source-history/'),
  )
  return unwrapData(response)
}

export async function setCustomerSource(
  customerId: string,
  payload: CustomerSourceChangeInput,
): Promise<CustomerSourceSummary> {
  const response = await apiClient.post<ApiDataResponse<CustomerSourceSummary>>(
    customerPath(customerId, 'set-source/'),
    payload,
  )
  return unwrapData(response)
}

export async function fetchCustomerActivityHistory(
  customerId: string,
): Promise<CustomerActivitySummary[]> {
  const response = await apiClient.get<ApiDataResponse<CustomerActivitySummary[]>>(
    customerPath(customerId, 'activity-history/'),
  )
  return unwrapData(response)
}

export async function setCustomerActivity(
  customerId: string,
  payload: CustomerActivityChangeInput,
): Promise<CustomerActivitySummary> {
  const response = await apiClient.post<ApiDataResponse<CustomerActivitySummary>>(
    customerPath(customerId, 'set-activity/'),
    payload,
  )
  return unwrapData(response)
}

export async function setCustomerClassification(
  customerId: string,
  payload: CustomerClassificationChangeInput,
): Promise<CustomerClassificationResult> {
  const response = await apiClient.post<ApiDataResponse<CustomerClassificationResult>>(
    customerPath(customerId, 'set-classification/'),
    payload,
  )
  return unwrapData(response)
}

export async function fetchCustomerBusinessSnapshotHistory(
  customerId: string,
): Promise<CustomerBusinessSnapshot[]> {
  const response = await apiClient.get<ApiDataResponse<CustomerBusinessSnapshot[]>>(
    customerPath(customerId, 'business-snapshot-history/'),
  )
  return unwrapData(response)
}

export async function setCustomerBusinessSnapshot(
  customerId: string,
  payload: CustomerBusinessSnapshotInput,
): Promise<CustomerBusinessSnapshot> {
  const response = await apiClient.post<ApiDataResponse<CustomerBusinessSnapshot>>(
    customerPath(customerId, 'set-business-snapshot/'),
    payload,
  )
  return unwrapData(response)
}

export async function fetchCustomerEntities(customerId: string): Promise<CustomerEntity[]> {
  const response = await apiClient.get<ApiDataResponse<CustomerEntity[]>>(
    customerPath(customerId, 'entities/'),
  )
  return unwrapData(response)
}

export async function createCustomerEntity(
  customerId: string,
  payload: CustomerEntityInput,
): Promise<CustomerEntity> {
  const response = await apiClient.post<ApiDataResponse<CustomerEntity>>(
    customerPath(customerId, 'entities/'),
    payload,
  )
  return unwrapData(response)
}

export async function fetchCustomerEntity(
  entityId: string,
): Promise<{ data: CustomerEntity; etag: string | null }> {
  const response = await apiClient.get<ApiDataResponse<CustomerEntity>>(
    `/api/v1/customer-entities/${encodeURIComponent(entityId)}/`,
  )
  return { data: response.data.data, etag: response.headers.etag || null }
}

export async function updateCustomerEntity(
  entityId: string,
  payload: Partial<CustomerEntityInput>,
  etag: string,
): Promise<CustomerEntity> {
  const response = await apiClient.patch<ApiDataResponse<CustomerEntity>>(
    `/api/v1/customer-entities/${encodeURIComponent(entityId)}/`,
    payload,
    { headers: { 'If-Match': etag } },
  )
  return unwrapData(response)
}

export async function fetchEntityAddresses(entityId: string): Promise<CustomerAddress[]> {
  const response = await apiClient.get<ApiDataResponse<CustomerAddress[]>>(
    `/api/v1/customer-entities/${encodeURIComponent(entityId)}/addresses/`,
  )
  return unwrapData(response)
}

export async function createEntityAddress(
  entityId: string,
  payload: CustomerAddressInput,
): Promise<CustomerAddress> {
  const response = await apiClient.post<ApiDataResponse<CustomerAddress>>(
    `/api/v1/customer-entities/${encodeURIComponent(entityId)}/addresses/`,
    payload,
  )
  return unwrapData(response)
}

export async function fetchEntityAddress(
  addressId: string,
): Promise<{ data: CustomerAddress; etag: string | null }> {
  const response = await apiClient.get<ApiDataResponse<CustomerAddress>>(
    `/api/v1/customer-addresses/${encodeURIComponent(addressId)}/`,
  )
  return { data: response.data.data, etag: response.headers.etag || null }
}

export async function updateEntityAddress(
  addressId: string,
  payload: Partial<CustomerAddressInput>,
  etag: string,
): Promise<CustomerAddress> {
  const response = await apiClient.patch<ApiDataResponse<CustomerAddress>>(
    `/api/v1/customer-addresses/${encodeURIComponent(addressId)}/`,
    payload,
    { headers: { 'If-Match': etag } },
  )
  return unwrapData(response)
}

export async function fetchCustomerTransferRequests(
  customerId?: string,
): Promise<PaginatedResponse<CustomerTransferRequest>> {
  const { data } = await apiClient.get<PaginatedResponse<CustomerTransferRequest>>(
    '/api/v1/customer-transfer-requests/',
    { params: customerId ? { customer_id: customerId } : undefined },
  )
  return data
}

export async function fetchCustomerTransferRequest(
  requestId: string,
): Promise<VersionedCustomer<CustomerTransferRequest>> {
  const response = await apiClient.get<ApiDataResponse<CustomerTransferRequest>>(
    `/api/v1/customer-transfer-requests/${encodeURIComponent(requestId)}/`,
  )
  return {
    data: response.data.data,
    etag: typeof response.headers.etag === 'string' ? response.headers.etag : null,
  }
}

async function decideCustomerTransferRequest(
  requestId: string,
  action: 'approve' | 'reject' | 'cancel',
  decisionNote: string,
  etag: string,
): Promise<CustomerTransferRequest> {
  const response = await apiClient.post<ApiDataResponse<CustomerTransferRequest>>(
    `/api/v1/customer-transfer-requests/${encodeURIComponent(requestId)}/${action}/`,
    { decision_note: decisionNote },
    { headers: { 'If-Match': etag } },
  )
  return unwrapData(response)
}

export async function approveCustomerTransferRequest(
  requestId: string,
  decisionNote: string,
  etag: string,
): Promise<CustomerTransferRequest> {
  return decideCustomerTransferRequest(requestId, 'approve', decisionNote, etag)
}

export async function rejectCustomerTransferRequest(
  requestId: string,
  decisionNote: string,
  etag: string,
): Promise<CustomerTransferRequest> {
  return decideCustomerTransferRequest(requestId, 'reject', decisionNote, etag)
}

export async function cancelCustomerTransferRequest(
  requestId: string,
  decisionNote: string,
  etag: string,
): Promise<CustomerTransferRequest> {
  return decideCustomerTransferRequest(requestId, 'cancel', decisionNote, etag)
}

export async function fetchCustomerDuplicateCases(
  status?: string,
): Promise<PaginatedResponse<CustomerDuplicateCase>> {
  const { data } = await apiClient.get<PaginatedResponse<CustomerDuplicateCase>>(
    '/api/v1/customer-duplicate-cases/',
    { params: status ? { status } : undefined },
  )
  return data
}

export async function fetchCustomerDuplicateCase(
  caseId: string,
): Promise<{ data: CustomerDuplicateCase; etag: string | null }> {
  const response = await apiClient.get<ApiDataResponse<CustomerDuplicateCase>>(
    `/api/v1/customer-duplicate-cases/${encodeURIComponent(caseId)}/`,
  )
  return {
    data: response.data.data,
    etag: typeof response.headers.etag === 'string' ? response.headers.etag : null,
  }
}

export async function previewCustomerMerge(
  caseId: string,
  payload: {
    survivor_customer_id: string
    source_customer_ids: string[]
    reason: string
    field_decisions: Record<string, unknown>
  },
): Promise<CustomerMergePreview> {
  const response = await apiClient.post<ApiDataResponse<CustomerMergePreview>>(
    `/api/v1/customer-duplicate-cases/${encodeURIComponent(caseId)}/merge-preview/`,
    payload,
  )
  return unwrapData(response)
}

export async function mergeCustomers(
  caseId: string,
  payload: {
    survivor_customer_id: string
    source_customer_ids: string[]
    reason: string
    field_decisions: Record<string, unknown>
  },
  etag: string,
): Promise<Record<string, unknown>> {
  const response = await apiClient.post<ApiDataResponse<Record<string, unknown>>>(
    `/api/v1/customer-duplicate-cases/${encodeURIComponent(caseId)}/merge/`,
    payload,
    { headers: { 'If-Match': etag } },
  )
  return unwrapData(response)
}

export async function dismissCustomerDuplicateCase(
  caseId: string,
  decisionNote: string,
  etag: string,
): Promise<CustomerDuplicateCase> {
  const response = await apiClient.post<ApiDataResponse<CustomerDuplicateCase>>(
    `/api/v1/customer-duplicate-cases/${encodeURIComponent(caseId)}/dismiss/`,
    { decision_note: decisionNote },
    { headers: { 'If-Match': etag } },
  )
  return unwrapData(response)
}

export async function decideCustomerDuplicateCandidate(
  candidateId: string,
  decision: 'SURVIVOR' | 'DUPLICATE' | 'NOT_DUPLICATE',
  etag: string,
): Promise<CustomerDuplicateCase['candidates'][number]> {
  const response = await apiClient.post<ApiDataResponse<CustomerDuplicateCase['candidates'][number]>>(
    `/api/v1/customer-duplicate-candidates/${encodeURIComponent(candidateId)}/decide/`,
    { decision },
    { headers: { 'If-Match': etag } },
  )
  return unwrapData(response)
}
