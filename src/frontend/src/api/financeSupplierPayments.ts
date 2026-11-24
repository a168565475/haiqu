import type { CreateSupplierPayment, SupplierLedgerOption, SupplierLedgerQuery, SupplierPaymentOptions } from '@/types/financeSupplierLedger'
import type {
  ApplicationPayableMonth, CreateSupplierPaymentApplication, SupplierPaymentApplicationDetail, SupplierPaymentApplicationRow,
  SupplierDuePayable, SupplierDuePayableSummary, SupplierPaymentPage, SupplierPaymentRecord,
} from '@/types/financeSupplierPayments'
import { apiClient } from './request'

const paymentRoot = '/api/v1/finance/supplier-payments/'
const applicationRoot = '/api/v1/finance/supplier-payment-applications/'

export async function fetchSupplierPaymentRecords(params: SupplierLedgerQuery, signal: AbortSignal) {
  return (await apiClient.get<SupplierPaymentPage<SupplierPaymentRecord>>(paymentRoot, { params, signal })).data
}

export async function fetchSupplierDuePayables(params: SupplierLedgerQuery, signal: AbortSignal) {
  return (await apiClient.get<SupplierPaymentPage<SupplierDuePayableSummary>>(
    paymentRoot + 'due-payables/', { params, signal },
  )).data
}

export async function fetchSupplierDuePayableDetails(params: SupplierLedgerQuery, signal: AbortSignal) {
  return (await apiClient.get<SupplierPaymentPage<SupplierDuePayable>>(
    paymentRoot + 'due-payable-details/', { params, signal },
  )).data
}

export async function fetchSupplierPaymentApplications(params: SupplierLedgerQuery, signal: AbortSignal) {
  return (await apiClient.get<SupplierPaymentPage<SupplierPaymentApplicationRow>>(applicationRoot, { params, signal })).data
}

export async function fetchSupplierPaymentSuppliers(signal: AbortSignal) {
  return (await apiClient.get<{ data: SupplierLedgerOption[] }>(paymentRoot + 'suppliers/', { signal })).data.data
}

export async function fetchApplicationPayables(supplierId: string, signal: AbortSignal, dueThroughMonth?: string) {
  return (await apiClient.get<{ data: ApplicationPayableMonth[] }>(applicationRoot + 'eligible-payables/', {
    params: { supplier_id: supplierId, due_through_month: dueThroughMonth }, signal,
  })).data.data
}

export async function fetchSupplierPaymentApplication(id: string, signal: AbortSignal) {
  const response = await apiClient.get<{ data: SupplierPaymentApplicationDetail }>(applicationRoot + id + '/', { signal })
  return { record: response.data.data, etag: String(response.headers.etag ?? '') }
}

export async function submitSupplierPaymentApplication(body: CreateSupplierPaymentApplication, key: string) {
  return (await apiClient.post<{ data: SupplierPaymentApplicationDetail }>(applicationRoot, body, {
    headers: { 'Idempotency-Key': key },
  })).data.data
}

export async function withdrawSupplierPaymentApplication(id: string, reason: string, etag: string) {
  const response = await apiClient.post<{ data: SupplierPaymentApplicationDetail }>(
    applicationRoot + id + '/withdraw/', { reason }, { headers: { 'If-Match': etag } },
  )
  return { record: response.data.data, etag: String(response.headers.etag ?? '') }
}

export async function fetchStandalonePaymentOptions() {
  return (await apiClient.get<{ data: SupplierPaymentOptions }>(paymentRoot + 'payment-options/')).data.data
}

export async function registerStandalonePayment(body: CreateSupplierPayment & { application_id?: string }, etag: string, key: string) {
  return (await apiClient.post<{ data: SupplierPaymentRecord }>(paymentRoot, body, {
    headers: { 'If-Match': etag, 'Idempotency-Key': key },
  })).data.data
}

export async function fetchStandalonePayment(id: string, signal: AbortSignal) {
  const response = await apiClient.get<{ data: SupplierPaymentRecord }>(paymentRoot + id + '/', { signal })
  return { record: response.data.data, etag: String(response.headers.etag ?? '') }
}

export async function voidStandalonePayment(id: string, reason: string, etag: string) {
  return (await apiClient.post<{ data: SupplierPaymentRecord }>(paymentRoot + id + '/void/', { reason }, {
    headers: { 'If-Match': etag },
  })).data.data
}
