import { apiClient } from './request'
import type { DataResponse } from '@/types/referenceData'
import type { PurchaseOrderReadDetail } from '@/types/purchaseOrderReadDetail'

export async function fetchPurchaseOrderReadDetail(id: string): Promise<PurchaseOrderReadDetail> {
  if (!/^[\da-f]{8}-[\da-f]{4}-[\da-f]{4}-[\da-f]{4}-[\da-f]{12}$/i.test(id)) {
    throw new Error('采购订单编号格式不正确。')
  }
  const { data } = await apiClient.get<DataResponse<PurchaseOrderReadDetail>>(`/api/v1/purchase-orders/${id}/details/`)
  return data.data
}
