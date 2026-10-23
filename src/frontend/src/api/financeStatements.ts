import { apiClient } from './request'
import type { FinanceSourcePage, FinanceSourceTaskPage, FinanceStatement, FinanceStatementInput, FinanceStatementPage, FinanceStatementQuery } from '@/types/financeStatements'
import type { ReceiptPage } from '@/types/financeReceipts'

const root = '/api/v1/finance/'
export async function fetchFinanceSourceTasks(query: { q?: string; mode?: 'statement' | 'receipt'; page: number; page_size: number }, signal?: AbortSignal): Promise<FinanceSourceTaskPage> {
  return (await apiClient.get<FinanceSourceTaskPage>(`${root}source-tasks/`, { params: query, signal })).data
}
export async function fetchFinanceSourceProducts(taskId: string, query: { page: number; page_size: number; editing_statement_id?: string }, signal?: AbortSignal): Promise<FinanceSourcePage> {
  return (await apiClient.get<FinanceSourcePage>(`${root}source-tasks/${taskId}/products/`, { params: query, signal })).data
}
export async function fetchFinanceStatements(query: FinanceStatementQuery, signal?: AbortSignal): Promise<FinanceStatementPage> {
  return (await apiClient.get<FinanceStatementPage>(`${root}statements/`, { params: query, signal })).data
}
export async function fetchFinanceStatement(id: string, signal?: AbortSignal): Promise<FinanceStatement> {
  return (await apiClient.get<{ data: FinanceStatement }>(`${root}statements/${id}/`, { signal })).data.data
}
export async function fetchFinanceStatementReceipts(id: string, page: number, signal?: AbortSignal): Promise<ReceiptPage> {
  return (await apiClient.get<ReceiptPage>(`${root}statements/${id}/receipts/`, { params: { page, page_size: 20 }, signal })).data
}
export async function createFinanceStatement(input: FinanceStatementInput, key: string): Promise<FinanceStatement> {
  return (await apiClient.post<{ data: FinanceStatement }>(`${root}statements/`, input, { headers: { 'Idempotency-Key': key } })).data.data
}
export async function updateFinanceStatement(id: string, input: FinanceStatementInput, etag: string): Promise<FinanceStatement> {
  return (await apiClient.patch<{ data: FinanceStatement }>(`${root}statements/${id}/`, input, { headers: { 'If-Match': etag } })).data.data
}
export async function voidFinanceStatement(id: string, reason: string, etag: string): Promise<FinanceStatement & { changed: boolean }> {
  return (await apiClient.post<{ data: FinanceStatement & { changed: boolean } }>(`${root}statements/${id}/void/`, { reason }, { headers: { 'If-Match': etag } })).data.data
}
export async function deleteFinanceStatement(id: string, etag: string): Promise<void> {
  await apiClient.delete(`${root}statements/${id}/`, { headers: { 'If-Match': etag } })
}
