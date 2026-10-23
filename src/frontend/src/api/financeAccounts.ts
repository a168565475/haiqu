import { apiClient } from './request'
import type { FinanceAccount, FinanceAccountInput, FinanceAccountPage, FinanceAccountQuery } from '@/types/financeAccounts'

const path = '/api/v1/finance/accounts/'

export async function fetchFinanceAccounts(query: FinanceAccountQuery, signal?: AbortSignal): Promise<FinanceAccountPage> {
  return (await apiClient.get<FinanceAccountPage>(path, { params: query, signal })).data
}

export async function fetchFinanceAccount(id: string, signal?: AbortSignal): Promise<FinanceAccount> {
  return (await apiClient.get<{ data: FinanceAccount }>(`${path}${id}/`, { signal })).data.data
}

export async function createFinanceAccount(input: FinanceAccountInput, key: string): Promise<FinanceAccount> {
  return (await apiClient.post<{ data: FinanceAccount }>(path, input, { headers: { 'Idempotency-Key': key } })).data.data
}

export async function updateFinanceAccount(id: string, input: Partial<Omit<FinanceAccountInput, 'code'>>, etag: string): Promise<FinanceAccount> {
  return (await apiClient.patch<{ data: FinanceAccount }>(`${path}${id}/`, input, { headers: { 'If-Match': etag } })).data.data
}

export async function deleteFinanceAccount(id: string, etag: string): Promise<void> {
  await apiClient.delete(`${path}${id}/`, { headers: { 'If-Match': etag } })
}
