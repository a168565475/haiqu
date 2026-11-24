import type {
  CreateSupplierOffset, CreateSupplierPayment, EligibleSupplierPayable, EligibleSupplierPayment,
  SupplierOffset, SupplierPayment, SupplierPaymentOptions, SupplierSettlementKind,
  SupplierLedgerEntryPage,
  SupplierLedgerOption,
  SupplierLedgerQuery,
  SupplierLedgerSummaryPage,
} from '@/types/financeSupplierLedger'
import { apiClient } from './request'

const root = '/api/v1/finance/supplier-ledger/'

export async function fetchSupplierLedger(query: SupplierLedgerQuery, signal: AbortSignal) {
  return (await apiClient.get<SupplierLedgerSummaryPage>(root, { params: query, signal })).data
}

export async function fetchSupplierLedgerEntries(query: SupplierLedgerQuery & { supplier_id: string }, signal: AbortSignal) {
  return (await apiClient.get<SupplierLedgerEntryPage>(`${root}entries/`, { params: query, signal })).data
}

export async function fetchSupplierLedgerOptions(signal: AbortSignal) {
  return (await apiClient.get<{ data: SupplierLedgerOption[] }>(`${root}suppliers/`, { signal })).data.data
}

export async function fetchSupplierPaymentOptions() {
  return (await apiClient.get<{ data: SupplierPaymentOptions }>(`${root}payment-options/`)).data.data
}

export async function fetchEligibleSupplierPayments() {
  return (await apiClient.get<{ data: EligibleSupplierPayment[] }>(`${root}offset-options/`)).data.data
}

export async function fetchEligibleSupplierPayables(paymentId: string, signal: AbortSignal) {
  return (await apiClient.get<{ data: EligibleSupplierPayable[] }>(`${root}offset-payables/`, {
    params: { payment_id: paymentId }, signal,
  })).data.data
}

export async function createSupplierSettlement(kind: SupplierSettlementKind, body: CreateSupplierPayment | CreateSupplierOffset,
  etag: string, key: string) {
  return (await apiClient.post<{ data: SupplierPayment | SupplierOffset }>(`${root}${kind}/`, body, {
    headers: { 'If-Match': etag, 'Idempotency-Key': key },
  })).data.data
}

export async function fetchSupplierSettlement(kind: SupplierSettlementKind, id: string, signal: AbortSignal) {
  const response = await apiClient.get<{ data: SupplierPayment | SupplierOffset }>(`${root}${kind}/${id}/`, { signal })
  return { record: response.data.data, etag: String(response.headers.etag ?? '') }
}

export async function voidSupplierSettlement(kind: SupplierSettlementKind, id: string, reason: string, etag: string) {
  return (await apiClient.post<{ data: SupplierPayment | SupplierOffset }>(`${root}${kind}/${id}/void/`, { reason }, {
    headers: { 'If-Match': etag },
  })).data.data
}
