import type { AxiosResponse } from 'axios'
import { apiClient } from './request'
import type { DataResponse } from '@/types/referenceData'
import type { MaterialInventorySummary, MaterialOrderIssue, MaterialOrderPurchase, MaterialReceivingOptions, MaterialFilterOptions } from '@/types/inventory'
import type { EligibleMaterialLine, EligibleMaterialPurchaseOrder, EligibleOrder, EligibleProduct, FinishedGoodsReceipt, InventoryOptions, ManualMaterialOptions, MaterialInbound, MaterialInventoryOptions, PaginatedInventory, PaginatedMaterialInventory, ProcurementInboundOrder, Warehouse, WarehouseLocation, WarehouseZone } from '@/types/inventory'

const root = '/api/v1/'
function versioned<T>(response: AxiosResponse<DataResponse<T>>) { return { data: response.data.data, etag: String(response.headers.etag || '') } }
export async function fetchFinishedGoodsInventory(params: Record<string, unknown>) { const { data } = await apiClient.get<PaginatedInventory>(`${root}finished-goods-inventory/`, { params }); return data }
export async function fetchInventoryOptions() { const { data } = await apiClient.get<DataResponse<InventoryOptions>>(`${root}finished-goods-inventory/options/`); return data.data }
export async function fetchEligibleProducts() { const { data } = await apiClient.get<DataResponse<EligibleProduct[]>>(`${root}finished-goods-inventory/eligible-products/`); return data.data }
export async function fetchEligibleOrders(productId: string) { const { data } = await apiClient.get<DataResponse<EligibleOrder[]>>(`${root}finished-goods-inventory/eligible-orders/`, { params: { product_id: productId } }); return data.data }
export async function fetchReceipts(receiptIds?: string[]) { const { data } = await apiClient.get<DataResponse<FinishedGoodsReceipt[]>>(`${root}finished-goods-inventory/receipts/`, { params: receiptIds?.length ? { receipt_ids: receiptIds.join(',') } : {} }); return data.data }
export async function fetchOutboundBatches(receiptIds: string[]) { const { data } = await apiClient.get<DataResponse<FinishedGoodsReceipt[]>>(`${root}finished-goods-inventory/outbound-batches/`, { params: { receipt_ids: receiptIds.join(',') } }); return data.data }
export async function createFinishedGoodsReceipt(payload: Record<string, unknown>) { const { data } = await apiClient.post<DataResponse<FinishedGoodsReceipt>>(`${root}finished-goods-inventory/receipts/`, payload); return data.data }
export async function createFinishedGoodsReceipts(items: Record<string, unknown>[]) { const { data } = await apiClient.post<DataResponse<FinishedGoodsReceipt[]>>(`${root}finished-goods-inventory/batch-receipts/`, { items }); return data.data }
export async function createFinishedGoodsOutbound(payload: Record<string, unknown>) { const { data } = await apiClient.post(`${root}finished-goods-inventory/outbounds/`, payload); return data.data }
export async function fetchMaterialInventory(params: Record<string, unknown>) { const { data } = await apiClient.get<PaginatedMaterialInventory>(`${root}material-inventory/`, { params }); return data }
export async function fetchMaterialInventorySummary(stockItemId: string) { const { data } = await apiClient.get<DataResponse<MaterialInventorySummary>>(`${root}material-inventory/${stockItemId}/summary/`); return data.data }
export async function fetchMaterialOrderPurchases(stockItemId: string) { const { data } = await apiClient.get<DataResponse<MaterialOrderPurchase[]>>(`${root}material-inventory/${stockItemId}/order-purchases/`); return data.data }
export async function fetchMaterialOrderIssues(stockItemId: string) { const { data } = await apiClient.get<DataResponse<MaterialOrderIssue[]>>(`${root}material-inventory/${stockItemId}/order-issues/`); return data.data }
export async function fetchMaterialInventoryOptions() { const { data } = await apiClient.get<DataResponse<MaterialInventoryOptions>>(`${root}material-inventory/options/`); return data.data }
export async function fetchMaterialReceivingOptions() {
  const { data } = await apiClient.get<DataResponse<MaterialReceivingOptions>>(`${root}material-inventory/options/`, { params: { scope: 'receiving' } })
  return data.data
}
export async function fetchMaterialFilterOptions() {
  const { data } = await apiClient.get<DataResponse<MaterialFilterOptions>>(`${root}material-inventory/options/`, { params: { scope: 'filters' } })
  return data.data
}
export async function fetchFinishedGoodsFilterOptions() {
  const { data } = await apiClient.get<DataResponse<MaterialReceivingOptions>>(`${root}finished-goods-inventory/options/`, { params: { scope: 'filters' } })
  return data.data
}
export async function fetchEligibleMaterialPurchaseOrders(params: Record<string, unknown> = {}) { const { data } = await apiClient.get<DataResponse<EligibleMaterialPurchaseOrder[]>>(`${root}material-inventory/eligible-purchase-orders/`, { params }); return data.data }
export async function fetchProcurementInboundOrders(params: Record<string, unknown> = {}) { const { data } = await apiClient.get<DataResponse<ProcurementInboundOrder[]>>(`${root}material-inventory/procurement-inbound-orders/`, { params }); return data.data }
export async function fetchEligibleMaterialLines(purchaseOrderId: string) { const { data } = await apiClient.get<DataResponse<EligibleMaterialLine[]>>(`${root}material-inventory/eligible-lines/`, { params: { purchase_order_id: purchaseOrderId } }); return data.data }
export async function fetchManualMaterialOptions(params: Record<string, unknown> = {}) { const { data } = await apiClient.get<DataResponse<ManualMaterialOptions>>(`${root}material-inventory/manual-material-options/`, { params }); return data.data }
export async function fetchMaterialReceipts(params: Record<string, unknown> = {}) { const { data } = await apiClient.get<DataResponse<MaterialInbound[]>>(`${root}material-inventory/receipts/`, { params }); return data.data }
export async function createMaterialReceipt(payload: Record<string, unknown>) { const { data } = await apiClient.post<DataResponse<MaterialInbound>>(`${root}material-inventory/receipts/`, payload); return data.data }
export async function createMaterialBatchReceipt(payload: Record<string, unknown>) { const { data } = await apiClient.post<DataResponse<MaterialInbound>>(`${root}material-inventory/batch-receipts/`, payload); return data.data }
export async function createMaterialReceiving(payload: Record<string, unknown>) { const { data } = await apiClient.post<DataResponse<MaterialInbound>>(`${root}material-inventory/receivings/`, payload); return data.data }
export async function createManualMaterialReceipt(payload: Record<string, unknown>) { const { data } = await apiClient.post<DataResponse<MaterialInbound>>(`${root}material-inventory/manual-receipts/`, payload); return data.data }
export async function fetchMaterialQualityBatches(params: Record<string, unknown> = {}) { const { data } = await apiClient.get<DataResponse<MaterialInbound[]>>(`${root}material-inventory/quality-batches/`, { params }); return data.data }
export async function fetchMaterialQualityBatch(inboundId: string) { const { data } = await apiClient.get<DataResponse<MaterialInbound>>(`${root}material-inventory/quality-batches/${inboundId}/`); return data.data }
export async function confirmMaterialQuality(inboundId: string, payload: Record<string, unknown>) { const { data } = await apiClient.post<DataResponse<MaterialInbound>>(`${root}material-inventory/quality-batches/${inboundId}/confirm/`, payload); return data.data }
export async function fetchMaterialInboundDetails(params: Record<string, unknown> = {}) { const { data } = await apiClient.get<DataResponse<MaterialInbound[]>>(`${root}material-inventory/inbound-details/`, { params }); return data.data }
async function fetchAll<T>(path: string, params: Record<string, unknown>) {
  const first = await apiClient.get<{ data: T[]; meta: { total_pages: number } }>(path, { params: { page: 1, page_size: 100, ...params } })
  const pages = [first.data.data]
  for (let page = 2; page <= first.data.meta.total_pages; page += 1) {
    const response = await apiClient.get<{ data: T[] }>(path, { params: { page, page_size: 100, ...params } })
    pages.push(response.data.data)
  }
  return pages.flat()
}
export function fetchWarehouses(params: Record<string, unknown> = {}) { return fetchAll<Warehouse>(`${root}warehouses/`, params) }
export function fetchZones(params: Record<string, unknown> = {}) { return fetchAll<WarehouseZone>(`${root}warehouse-zones/`, params) }
export function fetchLocations(params: Record<string, unknown> = {}) { return fetchAll<WarehouseLocation>(`${root}warehouse-locations/`, params) }
export async function saveWarehouse(id: string | null, payload: Record<string, unknown>, etag = '') { const response = id ? await apiClient.patch<DataResponse<Warehouse>>(`${root}warehouses/${id}/`, payload, { headers: { 'If-Match': etag } }) : await apiClient.post<DataResponse<Warehouse>>(`${root}warehouses/`, payload); return versioned(response) }
export async function saveZone(id: string | null, payload: Record<string, unknown>, etag = '') { const response = id ? await apiClient.patch<DataResponse<WarehouseZone>>(`${root}warehouse-zones/${id}/`, payload, { headers: { 'If-Match': etag } }) : await apiClient.post<DataResponse<WarehouseZone>>(`${root}warehouse-zones/`, payload); return versioned(response) }
export async function saveLocation(id: string | null, payload: Record<string, unknown>, etag = '') { const response = id ? await apiClient.patch<DataResponse<WarehouseLocation>>(`${root}warehouse-locations/${id}/`, payload, { headers: { 'If-Match': etag } }) : await apiClient.post<DataResponse<WarehouseLocation>>(`${root}warehouse-locations/`, payload); return versioned(response) }
export async function fetchVersioned<T>(path: string) { return versioned(await apiClient.get<DataResponse<T>>(`${root}${path}`)) }
