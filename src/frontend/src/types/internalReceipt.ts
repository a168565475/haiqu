export interface ReceiptAttributes {
  part_name: string; category: string; material: string; color: string; unit_name: string
  specification?: string; tube_diameter?: string; tube_thickness?: string; cutting_length_mm?: number; thickness?: string
}
export interface ReceiptPreviewLine {
  bom_line_id: string; component_key: string; usage: string; attributes: ReceiptAttributes; stage: string
  required: string; received: string; can_receive: string; input_remaining: string | null; input_supported: string | null
}
export interface ReceiptPreview {
  schedule_product_id: string; plan_category: 'METAL' | 'SEWING'; etag: string; production_order: string
  product: string; order_quantity: string; actor: string; receipt_date: string; lines: ReceiptPreviewLine[]
  excluded: string[]; zones: { id: string; warehouse: string; name: string }[]
}
export interface ReceiptPayload {
  request_id: string; schedule_product_id: string; plan_category: 'METAL' | 'SEWING'; zone_id: string
  receipt_date: string; remark: string; lines: { bom_line_id: string; quantity: string }[]
}
export interface SemiReceiptRecord {
  id: string; receipt_number: string; source: 'INTERNAL' | 'EXTERNAL'; source_display: string
  production_order: string; product: string; attributes: ReceiptAttributes; stage: string
  quantity: string; unit: string; receipt_date: string; status: string; warehouse: string; zone: string; actor: string; remark: string
  source_detail?: Record<string, string | null>
  submitted_by?: string; submitted_at?: string | null; confirmed_by?: string; confirmed_at?: string | null
  stock_movement_id?: string | null
  receipt_id?: string; etag?: string; can_delete?: boolean
}

export interface InternalReceiptResult {
  receipt_id: string; record_ids: string[]; receipt_number: string; status: string; replayed: boolean
}

export interface MetalReceiptOperation {
  name: string; quantity: string; work_item_id: string; operation_id: string
  scheme_id: string; scheme_revision: number
}

export interface MetalReceiptScheme {
  id: string; scheme_number: string; version: number; status: string
  effective_from: string; effective_to: string | null
}

export interface MetalReceiptBasis {
  basis_ready: boolean; blockers: string[]; as_of: string; issued: string
  reported_minimum: string | null; dispatched: string; reserved: string
  first_output_limit: string | null; current_remaining: string; can_receive: string
  operations: MetalReceiptOperation[]; schemes: MetalReceiptScheme[]; future_blockers: string[]
}

export interface MetalReceiptLine extends Omit<ReceiptPreviewLine, 'input_remaining' | 'input_supported'> {
  component_identity: string; specification: string; metal_processing: MetalReceiptBasis
}

export interface MetalReceiptPreview extends Omit<ReceiptPreview, 'lines' | 'zones' | 'plan_category'> {
  plan_category: 'METAL'; order_number: string; schedule_number: string; product_number: string
  item_number: string; product_unit: string; product_color: string; lines: MetalReceiptLine[]
  zones: { id: string; warehouse: string; warehouse_id: string; name: string }[]
  metal_processing: { future_blockers: string[]; blockers: string[]; as_of: string }
}

// 旧金工页的数字输入会将本地待核对记录中的 quantity 保存为 number，重试须原样保留。
export interface MetalReceiptPayload extends Omit<ReceiptPayload, 'lines'> {
  lines: { bom_line_id: string; quantity: string | number }[]
}
