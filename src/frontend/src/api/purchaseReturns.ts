import { apiClient } from './request'
import type { DataResponse } from '@/types/referenceData'
import type { PurchaseReturn, ReturnList, ReturnOptions, ReturnQuery } from '@/types/purchaseReturn'

const basePath = '/api/v1/purchase-returns/'
export async function fetchPurchaseReturns(query: ReturnQuery): Promise<ReturnList> {
  return (await apiClient.get<ReturnList>(basePath, { params: query })).data
}
export async function fetchReturnOptions(): Promise<ReturnOptions> {
  return (await apiClient.get<DataResponse<ReturnOptions>>(`${basePath}filter-options/`)).data.data
}
export async function fetchPurchaseReturn(id: string) {
  const response = await apiClient.get<DataResponse<PurchaseReturn>>(`${basePath}${encodeURIComponent(id)}/`)
  return { data: response.data.data, etag: typeof response.headers.etag === 'string' ? response.headers.etag : '' }
}
export async function advancePurchaseReturn(id: string, action: 'confirm' | 'complete', etag: string): Promise<PurchaseReturn> {
  if (!id || !etag.trim()) throw new Error('缺少退货单编号或版本，请刷新后重试。')
  return (await apiClient.post<DataResponse<PurchaseReturn>>(`${basePath}${encodeURIComponent(id)}/${action}/`, {}, { headers: { 'If-Match': etag } })).data.data
}
