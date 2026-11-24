import { apiClient } from './request'
import type {
  PurchasePayable,
  PurchasePayablePage,
  PurchasePayablePricingInput,
  PurchasePayableQuery,
  PurchasePayableLinePage,
  PurchasePayableFilterOptions,
} from '@/types/financePurchasePayables'

const root = '/api/v1/finance/purchase-payables/'

export async function fetchPurchasePayables(query: PurchasePayableQuery, signal?: AbortSignal): Promise<PurchasePayablePage> {
  return (await apiClient.get<PurchasePayablePage>(root, { params: query, signal })).data
}

export async function fetchPurchasePayableLines(query: PurchasePayableQuery): Promise<PurchasePayableLinePage> {
  return (await apiClient.get<PurchasePayableLinePage>(`${root}lines/`, { params: query })).data
}

export async function fetchPurchasePayableFilterOptions(): Promise<PurchasePayableFilterOptions> {
  return (await apiClient.get<{ data: PurchasePayableFilterOptions }>(`${root}filter-options/`)).data.data
}

export async function fetchPurchasePayable(id: string, signal?: AbortSignal): Promise<PurchasePayable> {
  return (await apiClient.get<{ data: PurchasePayable }>(`${root}${id}/`, { signal })).data.data
}

export async function updatePurchasePayablePricing(id: string, input: PurchasePayablePricingInput, etag: string): Promise<PurchasePayable> {
  return (await apiClient.patch<{ data: PurchasePayable }>(`${root}${id}/pricing/`, input, { headers: { 'If-Match': etag } })).data.data
}

export async function confirmPurchasePayable(id: string, etag: string): Promise<PurchasePayable> {
  return (await apiClient.post<{ data: PurchasePayable }>(`${root}${id}/confirm/`, {}, { headers: { 'If-Match': etag } })).data.data
}

export async function voidPurchasePayable(id: string, reason: string, etag: string): Promise<PurchasePayable> {
  return (await apiClient.post<{ data: PurchasePayable }>(`${root}${id}/void/`, { reason }, { headers: { 'If-Match': etag } })).data.data
}
