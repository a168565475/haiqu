import type { AxiosResponse } from 'axios'

import { apiClient } from './request'
import type { ApiDataResponse, PaginatedResponse } from '@/types/customer'
import type { EmailAccount, EmailAccountInput, VersionedEmailAccount } from '@/types/emailAccount'

const basePath = '/api/v1/email-accounts/'

function versioned(response: AxiosResponse<ApiDataResponse<EmailAccount>>): VersionedEmailAccount {
  return {
    data: response.data.data,
    etag: typeof response.headers.etag === 'string' ? response.headers.etag : '',
  }
}

export async function fetchEmailAccounts(): Promise<EmailAccount[]> {
  const { data } = await apiClient.get<PaginatedResponse<EmailAccount>>(basePath, {
    params: { page_size: 100 },
  })
  return data.data
}

export async function fetchEmailAccount(id: string): Promise<VersionedEmailAccount> {
  return versioned(await apiClient.get<ApiDataResponse<EmailAccount>>(`${basePath}${encodeURIComponent(id)}/`))
}

export async function createEmailAccount(payload: EmailAccountInput): Promise<VersionedEmailAccount> {
  return versioned(await apiClient.post<ApiDataResponse<EmailAccount>>(basePath, payload))
}

export async function updateEmailAccount(
  id: string,
  payload: Partial<EmailAccountInput>,
  etag: string,
): Promise<VersionedEmailAccount> {
  return versioned(await apiClient.patch<ApiDataResponse<EmailAccount>>(
    `${basePath}${encodeURIComponent(id)}/`,
    payload,
    { headers: { 'If-Match': etag } },
  ))
}

export async function deleteEmailAccount(id: string, etag: string): Promise<void> {
  await apiClient.delete(`${basePath}${encodeURIComponent(id)}/`, { headers: { 'If-Match': etag } })
}

export async function setDefaultEmailAccount(id: string, etag: string): Promise<VersionedEmailAccount> {
  return versioned(await apiClient.post<ApiDataResponse<EmailAccount>>(
    `${basePath}${encodeURIComponent(id)}/set-default/`,
    {},
    { headers: { 'If-Match': etag } },
  ))
}

export async function sendEmailAccountTest(
  id: string,
  recipient: string,
  etag: string,
): Promise<VersionedEmailAccount> {
  return versioned(await apiClient.post<ApiDataResponse<EmailAccount>>(
    `${basePath}${encodeURIComponent(id)}/test-send/`,
    { recipient },
    { headers: { 'If-Match': etag } },
  ))
}

