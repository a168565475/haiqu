import { apiClient } from './request'
import type { Receipt, ReceiptAccountPage, ReceiptDepositPage, ReceiptInput, ReceiptPage, ReceiptQuery, ReceiptUpload } from '@/types/financeReceipts'

const base = '/api/v1/finance/'
export async function deleteFinanceReceipt(id: string, etag: string): Promise<void> {
  await apiClient.delete(`${base}receipts/${id}/`, { headers: { 'If-Match': etag } })
}
export async function fetchFinanceReceipts(query: ReceiptQuery, signal?: AbortSignal): Promise<ReceiptPage> {
  return (await apiClient.get<ReceiptPage>(`${base}receipts/`, { params: query, signal })).data
}
export async function fetchFinanceReceipt(id: string, signal?: AbortSignal): Promise<Receipt> {
  return (await apiClient.get<{ data: Receipt }>(`${base}receipts/${id}/`, { signal })).data.data
}
export async function createFinanceReceipt(input: ReceiptInput, key: string, statementEtag: string): Promise<Receipt> {
  return (await apiClient.post<{ data: Receipt }>(`${base}receipts/`, input,
    { headers: { 'Idempotency-Key': key, 'If-Match': statementEtag } })).data.data
}
export async function voidFinanceReceipt(id: string, reason: string, etag: string): Promise<Receipt & { changed: boolean }> {
  return (await apiClient.post<{ data: Receipt & { changed: boolean } }>(`${base}receipts/${id}/void/`, { reason },
    { headers: { 'If-Match': etag } })).data.data
}
export async function fetchReceiptAccounts(query: { q?: string; page: number; page_size: number }, signal?: AbortSignal): Promise<ReceiptAccountPage> {
  return (await apiClient.get<ReceiptAccountPage>(`${base}account-options/`, { params: query, signal })).data
}
export async function uploadReceiptFile(statementId: string, file: File, uploadKey: string): Promise<ReceiptUpload> {
  const body = new FormData()
  body.append('statement_id', statementId)
  body.append('upload_key', uploadKey)
  body.append('file', file)
  return (await apiClient.post<{ data: ReceiptUpload }>(`${base}receipt-uploads/`, body, { timeout: 120000 })).data.data
}
export async function fetchReceiptUploads(statementId: string, signal?: AbortSignal): Promise<ReceiptUpload[]> {
  return (await apiClient.get<{ data: ReceiptUpload[] }>(`${base}receipt-uploads/`, { params: { statement_id: statementId }, signal })).data.data
}
export async function discardReceiptUpload(id: string): Promise<ReceiptUpload> {
  return (await apiClient.delete<{ data: ReceiptUpload }>(`${base}receipt-uploads/${id}/`)).data.data
}
export async function fetchReceiptUploadContent(id: string): Promise<Blob> {
  return (await apiClient.get<Blob>(`${base}receipt-uploads/${id}/content/`, { responseType: 'blob', timeout: 30000 })).data
}
export async function fetchReceiptAttachment(receiptId: string, fileId: string): Promise<Blob> {
  return (await apiClient.get<Blob>(`${base}receipts/${receiptId}/attachments/${fileId}/`, { responseType: 'blob', timeout: 30000 })).data
}
export async function fetchFinanceAvailableDeposits(statementId: string, query: { q?: string; include_unavailable?: boolean; page: number; page_size: number }, signal?: AbortSignal): Promise<ReceiptDepositPage> {
  return (await apiClient.get<ReceiptDepositPage>(`${base}statements/${statementId}/available-deposits/`, { params: query, signal })).data
}
