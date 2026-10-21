import type { PurchaseOrderDetail } from './purchaseOrder'
import type { PurchaseReturn } from './purchaseReturn'

export type PurchaseReadLine = PurchaseOrderDetail['lines'][number] & {
  color: string
  received_quantity: string
  accepted_quantity: string
  return_quantity: string
  received_bar_count?: number | null
  accepted_bar_count?: number | null
  return_bar_count?: number | null
}

export interface PurchaseReadInboundLine {
  measurement_kind?: string
  raw_bar_length_m?: string | null
  received_bar_count?: number | null
  accepted_bar_count?: number | null
  return_bar_count?: number | null
  id: string
  purchase_order_line_id: string
  part_name_snapshot: string
  specification_snapshot: string
  material_snapshot: string
  supplier_name_snapshot: string
  source_unit_text_snapshot: string
  received_quantity: string
  accepted_quantity: string
  return_quantity: string
  quality_remark: string
  warehouse_name: string
  zone_name: string
  location_number: string
  material_attributes_snapshot?: import('./purchaseOrder').MaterialAttributeSnapshot
}

export interface PurchaseReadInbound {
  id: string
  inbound_number: string
  inbound_date: string
  status: 'PENDING_QUALITY' | 'CONFIRMED'
  status_display: string
  remark: string
  received_by_name: string
  quality_confirmed_by_name: string
  quality_confirmed_at: string | null
  created_at: string
  lines: PurchaseReadInboundLine[]
}

export interface PurchaseOrderReadDetail extends Omit<PurchaseOrderDetail, 'lines'> {
  lines: PurchaseReadLine[]
  completed_by_name: string
  inbounds: PurchaseReadInbound[]
  returns: PurchaseReturn[]
}
