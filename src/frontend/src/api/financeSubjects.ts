import { apiClient } from './request'
import type { FinanceSubject, FinanceSubjectInput, FinanceSubjectPage, FinanceSubjectQuery } from '@/types/financeSubjects'

const path = '/api/v1/finance/subjects/'
export async function fetchFinanceSubjects(query: FinanceSubjectQuery, signal?: AbortSignal): Promise<FinanceSubjectPage> {
  return (await apiClient.get<FinanceSubjectPage>(path, { params: query, signal })).data
}
export async function fetchSubjectTree(query: FinanceSubjectQuery, signal?: AbortSignal): Promise<FinanceSubjectPage> {
  return (await apiClient.get<FinanceSubjectPage>('/api/v1/finance/subject-tree/', { params: query, signal })).data
}
export async function fetchFinanceSubject(id: string, signal?: AbortSignal): Promise<FinanceSubject> {
  return (await apiClient.get<{ data: FinanceSubject }>(`${path}${id}/`, { signal })).data.data
}
export async function createFinanceSubject(input: FinanceSubjectInput, key: string): Promise<FinanceSubject> {
  return (await apiClient.post<{ data: FinanceSubject }>(path, input, { headers: { 'Idempotency-Key': key } })).data.data
}
export async function updateFinanceSubject(id: string, input: Partial<Pick<FinanceSubjectInput, 'name' | 'status'>>, etag: string): Promise<FinanceSubject> {
  return (await apiClient.patch<{ data: FinanceSubject }>(`${path}${id}/`, input, { headers: { 'If-Match': etag } })).data.data
}
export async function deleteFinanceSubject(id: string, etag: string): Promise<void> {
  await apiClient.delete(`${path}${id}/`, { headers: { 'If-Match': etag } })
}
