import { apiClient } from './request'
import type { DataResponse } from '@/types/referenceData'
import type { PurchaseTrackingArrival, PurchaseTrackingCoverage, PurchaseTrackingFilterOptions, PurchaseTrackingPage, PurchaseTrackingPolicy, PurchaseTrackingPolicyInput, PurchaseTrackingQuery } from '@/types/purchaseTracking'

const basePath = '/api/v1/purchase-tracking/'
const policyPath = '/api/v1/purchase-tracking-policy/'

export async function fetchPurchaseTrackingArrivals(query: PurchaseTrackingQuery = {}, signal?: AbortSignal): Promise<PurchaseTrackingPage<PurchaseTrackingArrival>> {
  return (await apiClient.get<PurchaseTrackingPage<PurchaseTrackingArrival>>(`${basePath}arrivals/`, { params: query, signal })).data
}

export async function fetchPurchaseTrackingCoverage(query: PurchaseTrackingQuery = {}, signal?: AbortSignal): Promise<PurchaseTrackingPage<PurchaseTrackingCoverage>> {
  return (await apiClient.get<PurchaseTrackingPage<PurchaseTrackingCoverage>>(`${basePath}coverage/`, { params: query, signal })).data
}

export async function fetchPurchaseTrackingFilterOptions(signal?: AbortSignal): Promise<PurchaseTrackingFilterOptions> {
  return (await apiClient.get<DataResponse<PurchaseTrackingFilterOptions>>(`${basePath}filter-options/`, { signal })).data.data
}

export async function fetchPurchaseTrackingPolicy(signal?: AbortSignal): Promise<PurchaseTrackingPolicy> {
  return (await apiClient.get<DataResponse<PurchaseTrackingPolicy>>(policyPath, { signal })).data.data
}

export async function updatePurchaseTrackingPolicy(payload: PurchaseTrackingPolicyInput, etag: string): Promise<PurchaseTrackingPolicy> {
  return (await apiClient.patch<DataResponse<PurchaseTrackingPolicy>>(policyPath, payload, { headers: { 'If-Match': etag } })).data.data
}
