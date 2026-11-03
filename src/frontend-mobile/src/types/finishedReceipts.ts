export interface FinishedReceiptPreview {
  schedule_product_id: string; schedule_number: string; production_task_product_id: string
  task_number: string; order_number: string; product_number: string; product_name: string
  item_number: string; specification: string; actual_color: string; unit_id: string; unit_name: string
  order_quantity: number; tolerance_percent: string; maximum_receivable: number
  received_total: number; remaining_receivable: number; order_maximum: number; reported_minimum: number
  reporting_basis_ready: boolean
  reporting_operations: { work_item_id: string; operation: string; reported_quantity: string }[]
  receipt_date: string; actor_name: string; etag: string
}
export interface FinishedReceiptOptions {
  warehouses: { id: string; warehouse_number: string; warehouse_name: string; warehouse_type: string; status: string }[]
  zones: { id: string; warehouse: string; zone_name: string; status: string }[]
  locations: { id: string; zone: string; warehouse_id: string; location_number: string; status: string; remaining_box_slots: number | null }[]
}
export interface FinishedReceiptPayload {
  request_id: string; schedule_product_id: string; location_id: string; receipt_date: string
  received_quantity: number; quantity_per_box: number | null; actual_color: string; remark: string
}
export interface PendingFinishedReceipt { payload: FinishedReceiptPayload; etag: string }
export interface FinishedReceiptResult { id: string; receipt_number: string; status: 'PENDING' | 'CONFIRMED'; replayed: boolean }
