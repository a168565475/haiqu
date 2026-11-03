export type SemiReceiptCategory = 'METAL' | 'SEWING'
export interface SemiMaterialSnapshot { catalog_id?: string; name?: string; unit_name?: string; processing_stage?: string; attributes?: Record<string, string> }
export interface SemiReceiptBasis {
  basis_ready: boolean; blockers: string[]; as_of: string; issued: string; reported_minimum: string | null
  dispatched: string; reserved: string; first_output_limit: string | null; current_remaining: string; can_receive: string
  operations: { name: string; quantity: string; work_item_id: string; operation_id: string; scheme_id: string; scheme_revision: number }[]
  schemes: { id: string; scheme_number: string; version: number; status: string; effective_from: string; effective_to: string | null }[]
  future_blockers: string[]
}
export interface SemiReceiptLine {
  bom_line_id: string; component_key: string; component_identity?: string; usage: string; stage: string
  attributes: { part_name: string; category?: string; material: string; color: string; unit_name: string; specification?: string; tube_diameter?: string; tube_thickness?: string; cutting_length_mm?: string | number; thickness?: string }
  specification?: string; required: string | null; received: string; can_receive: string
  input_remaining?: string | null; input_supported?: string | null; directly_committed?: string
  processing_not_enabled_reason?: string; input_material_selection_snapshot?: SemiMaterialSnapshot | null; output_material_selection_snapshot?: SemiMaterialSnapshot | null
  metal_processing?: SemiReceiptBasis
}
export interface SemiReceiptPreview {
  schedule_product_id: string; plan_category: SemiReceiptCategory; etag: string; production_order: string
  product: string; order_quantity: string; actor: string; receipt_date: string; lines: SemiReceiptLine[]
  excluded: string[]; zones: { id: string; warehouse: string; name: string; warehouse_id?: string }[]
  order_number?: string; schedule_number?: string; product_number?: string; item_number?: string; product_unit?: string; product_color?: string; processing_state?: string
  metal_processing?: { future_blockers: string[]; blockers: string[]; as_of: string }
}
export interface SemiReceiptPayload {
  request_id: string; schedule_product_id: string; plan_category: SemiReceiptCategory; zone_id: string
  receipt_date: string; remark: string; lines: { bom_line_id: string; quantity: string | number }[]
}
export interface PendingSemiReceipt { payload: SemiReceiptPayload; etag: string; conflict?: boolean }
export interface SemiReceiptResult { receipt_id: string; record_ids: string[]; receipt_number: string; status: 'PENDING' | 'CONFIRMED'; replayed: boolean }
