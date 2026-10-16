import type { PageMeta } from './referenceData'

export type ReturnOrderStatus = 'QUALITY_GENERATED' | 'PROCUREMENT_CONFIRMED' | 'COMPLETED'
export interface PurchaseReturnLine {
  material_attributes_snapshot?: import('./purchaseOrder').MaterialAttributeSnapshot
  return_bar_count?: number | null; raw_bar_length_m?: string | null
  id: string; inbound_line_id: string; purchase_order_line_id: string
  product_name: string; material: string; part_name: string; specification: string
  color: string; unit: string; quantity: string; quality_remark: string
}
export interface PurchaseReturn {
  id: string; return_number: string; purchase_order_id: string; order_number: string
  production_task_number: string; inbound_id: string; inbound_number: string
  supplier_id: string; supplier_number: string; supplier_name: string
  status: ReturnOrderStatus; status_display: string; generated_by_name: string
  confirmed_by_name: string; completed_by_name: string; created_at: string
  confirmed_at: string | null; completed_at: string | null; updated_at: string
  lines: PurchaseReturnLine[]
}
export interface ReturnQuery {
  q?: string; purchase_order_id?: string; supplier_id?: string; status?: ReturnOrderStatus
  page?: number; page_size?: number; ordering?: 'updated_at' | '-updated_at'
}
export interface ReturnOptions { suppliers: { id: string; supplier_number: string; supplier_name: string }[] }
export interface ReturnList { data: PurchaseReturn[]; meta: PageMeta }
