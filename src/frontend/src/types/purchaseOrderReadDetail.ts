import type { PurchaseOrderDetail, PurchaseOrderStatus } from './purchaseOrder'
import type { PurchaseReturn } from './purchaseReturn'

export type PurchaseReadLine = PurchaseOrderDetail['lines'][number] & {
  receipt_quantity_mode?: 'ROOTS' | null
  color: string
  received_quantity: string
  accepted_quantity: string
  return_quantity: string
  received_weight_kg?: string | null
  accepted_weight_kg?: string | null
  return_weight_kg?: string | null
  received_bar_count?: number | null
  accepted_bar_count?: number | null
  return_bar_count?: number | null
  bar_weight_kg?: string | null
}

export interface PurchaseReadInboundLine {
  piece_unit?: string; received_piece_count?: string | null; accepted_piece_count?: string | null; return_piece_count?: string | null
  material_catalog_id?: string | null
  material_selection_snapshot?: import('./materialCatalog').MaterialSelectionSnapshot | Record<string, never>
  measurement_kind?: string
  section_type_snapshot?: string
  section_title_snapshot?: string
  calculation_snapshot?: Record<string, unknown>
  raw_bar_length_m?: string | null
  bar_weight_kg?: string | null
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
  received_weight_kg?: string | null
  accepted_weight_kg?: string | null
  return_weight_kg?: string | null
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
  material_section?: import('./inventory').PurchaseReceivingSection | ''
  material_section_display?: string
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
  display_status?: PurchaseOrderStatus
  lines: PurchaseReadLine[]
  completed_by_name: string
  inbounds: PurchaseReadInbound[]
  returns: PurchaseReturn[]
}
