import type { CuttingAttributes, TubeOrderDetail, TubeSourceKind } from './tubeOutsourcing'

export interface TubeReceiptCandidate {
  id: string; order_number: string; task_number: string; task_order_number: string
  product_number: string; item_number: string; product_name: string; color: string
  source_kind: TubeSourceKind; source_label: string; actual_dispatch_date: string | null
  expected_return_date: string; total_quantity: string; factory_names: string[]
}
export interface TubeReceiptCandidates {
  items: TubeReceiptCandidate[]; total: number; page: number; page_size: number
}
export interface TubeReceiptLine extends CuttingAttributes {
  id: string; order_line_id: string; component_identity: string; part_name: string
  material: string; specification: string; thickness: string; cutting_length_mm: string
  raw_color: string; spray_color: string; factory_id: string; factory_name: string
  dispatched_quantity: string; received_quantity: string; shortage_quantity: string
  shortage_reason: string; zone_id: string | null; zone_name: string; stock_movement_id: string | null
}
export interface TubeReceipt {
  category?: 'tube' | 'cutting'; output_unit?: '支' | '套'; craft_id?: string; craft_name?: string
  id: string; receipt_number: string; order_id: string; order_number: string; status: 'COMPLETED'
  source_kind: TubeSourceKind; source_label: string; client_request_id: string
  receipt_date: string; warehouse_id: string | null; warehouse_name: string; confirmed_at: string
  actor_name: string; remark: string; total_dispatched_quantity: string; total_received_quantity: string
  total_shortage_quantity: string; etag: string; created: boolean; lines: TubeReceiptLine[]
}
export interface TubeReceiptPreview {
  order: TubeOrderDetail; etag: string; can_receive: boolean; blockers: string[]; actor_name: string; today: string
  warehouses: { id: string; name: string }[]
  zones: { id: string; warehouse_id: string; warehouse: string; name: string }[]
  receipt: TubeReceipt | null
}
export interface TubeReceiptInput {
  client_request_id: string; receipt_date: string; warehouse_id: string | null; remark: string
  lines: { order_line_id: string; received_quantity: string; shortage_reason: string; zone_id: string | null }[]
}
export interface TubeReceiptPending { order_id: string; etag: string; payload: TubeReceiptInput }
