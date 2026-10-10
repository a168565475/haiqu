import type { AxiosResponse } from 'axios'

import { apiClient } from './request'
import type { ApiDataResponse, PaginatedResponse } from '@/types/customer'
import type {
  ContactCreateInput,
  ContactDetail,
  ContactDuplicateSummary,
  ContactEmploymentEvent,
  ContactEmploymentRecordInput,
  ContactLeaveInput,
  ContactMethod,
  ContactMethodInput,
  ContactMethodType,
  ContactListQuery,
  ContactOptions,
  ContactPage,
  ContactUpdateInput,
  ImportBatch,
  ImportRecord,
  SavedContactView,
  VersionedContact,
} from '@/types/contact'

function versioned(response: AxiosResponse<ApiDataResponse<ContactDetail>>): VersionedContact {
  return {
    data: response.data.data,
    etag: typeof response.headers.etag === 'string' ? response.headers.etag : null,
  }
}

export async function fetchContacts(params: ContactListQuery): Promise<ContactPage> {
  const { data } = await apiClient.get<ContactPage>('/api/v1/contacts/', { params })
  return data
}

export async function fetchCustomerContacts(
  customerId: string,
  params: ContactListQuery,
): Promise<ContactPage> {
  const { data } = await apiClient.get<ContactPage>(
    `/api/v1/customers/${encodeURIComponent(customerId)}/contacts/`,
    { params },
  )
  return data
}

export async function fetchContact(contactId: string): Promise<VersionedContact> {
  return versioned(
    await apiClient.get<ApiDataResponse<ContactDetail>>(
      `/api/v1/contacts/${encodeURIComponent(contactId)}/`,
    ),
  )
}

export async function deleteContact(contactId: string, etag: string): Promise<{ deleted_count: number }> {
  const { data } = await apiClient.delete<ApiDataResponse<{ deleted_count: number }>>(
    `/api/v1/contacts/${encodeURIComponent(contactId)}/`,
    { headers: { 'If-Match': etag } },
  )
  return data.data
}

export async function fetchContactOptions(): Promise<ContactOptions> {
  const { data } = await apiClient.get<ApiDataResponse<ContactOptions>>('/api/v1/contacts/options/')
  return data.data
}

export async function checkContactDuplicate(params: {
  customer_id: string
  method_type: ContactMethodType
  value: string
  exclude_contact_id?: string
}): Promise<ContactDuplicateSummary> {
  const { data } = await apiClient.get<ApiDataResponse<ContactDuplicateSummary>>(
    '/api/v1/contacts/duplicate-check/',
    { params },
  )
  return data.data
}

export async function createContact(payload: ContactCreateInput): Promise<VersionedContact> {
  const { customer_id: customerId, ...data } = payload
  return versioned(
    await apiClient.post<ApiDataResponse<ContactDetail>>(
      `/api/v1/customers/${encodeURIComponent(customerId)}/contacts/`,
      data,
    ),
  )
}

export async function updateContact(
  contactId: string,
  payload: ContactUpdateInput,
  etag: string,
): Promise<VersionedContact> {
  return versioned(
    await apiClient.patch<ApiDataResponse<ContactDetail>>(
      `/api/v1/contacts/${encodeURIComponent(contactId)}/`,
      payload,
      { headers: { 'If-Match': etag } },
    ),
  )
}

export async function addContactMethod(
  contactId: string,
  payload: ContactMethodInput & { duplicate_acknowledged?: boolean },
): Promise<ContactMethod> {
  const response = await apiClient.post<ApiDataResponse<ContactMethod>>(
    `/api/v1/contacts/${encodeURIComponent(contactId)}/methods/`,
    payload,
  )
  return response.data.data
}

export async function markContactLeft(contactId: string, payload: ContactLeaveInput, etag: string): Promise<void> {
  await apiClient.post(
    `/api/v1/contacts/${encodeURIComponent(contactId)}/mark-left/`,
    payload,
    { headers: { 'If-Match': etag } },
  )
}

export async function fetchContactEmploymentHistory(contactId: string): Promise<ContactEmploymentEvent[]> {
  const { data } = await apiClient.get<ApiDataResponse<ContactEmploymentEvent[]>>(
    `/api/v1/contacts/${encodeURIComponent(contactId)}/employment-history/`,
  )
  return data.data
}

export async function createContactEmploymentRecord(
  contactId: string,
  payload: ContactEmploymentRecordInput,
  etag: string,
): Promise<{ data: ContactEmploymentEvent; etag: string | null }> {
  const response = await apiClient.post<ApiDataResponse<ContactEmploymentEvent>>(
    `/api/v1/contacts/${encodeURIComponent(contactId)}/employment-history/`,
    payload,
    { headers: { 'If-Match': etag } },
  )
  return {
    data: response.data.data,
    etag: typeof response.headers.etag === 'string' ? response.headers.etag : null,
  }
}

export async function bulkMarkContactsLeft(contactIds: string[], reason: string): Promise<void> {
  await apiClient.post('/api/v1/contacts/bulk-mark-left/', { contact_ids: contactIds, reason })
}

export async function bulkCreateContactTasks(payload: Record<string, unknown>): Promise<void> {
  await apiClient.post('/api/v1/contacts/bulk-create-tasks/', payload)
}

export async function uploadContactImport(
  file: File,
  customerId: string | undefined,
  allowDuplicates: boolean,
): Promise<ImportBatch> {
  const body = new FormData()
  body.append('file', file)
  if (customerId) body.append('customer_id', customerId)
  body.append('allow_same_customer_duplicates', String(allowDuplicates))
  const response = await apiClient.post<ApiDataResponse<ImportBatch>>('/api/v1/contact-imports/', body, {
    timeout: 120_000,
  })
  return response.data.data
}

export async function fetchImportRecords(batchId: string): Promise<ImportRecord[]> {
  const { data } = await apiClient.get<PaginatedResponse<ImportRecord>>(
    `/api/v1/contact-imports/${encodeURIComponent(batchId)}/records/`,
    { params: { page_size: 100 } },
  )
  return data.data
}

export function contactImportTemplateUrl(scope: 'global' | 'customer'): string {
  const base = apiClient.defaults.baseURL || ''
  return `${base}/api/v1/contact-imports/template/?scope=${scope}`
}

export async function fetchSavedContactViews(): Promise<SavedContactView[]> {
  const { data } = await apiClient.get<PaginatedResponse<SavedContactView>>('/api/v1/saved-views/', {
    params: { module_code: 'CONTACT' },
  })
  return data.data
}

export async function createSavedContactView(payload: {
  view_name: string
  filter_definition: Record<string, unknown>
  column_definition: string[]
  sort_definition: string[]
}): Promise<SavedContactView> {
  const { data } = await apiClient.post<ApiDataResponse<SavedContactView>>('/api/v1/saved-views/', {
    module_code: 'CONTACT',
    ...payload,
  })
  return data.data
}
