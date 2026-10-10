export type TubeSourceKind = 'METAL' | 'PUBLIC_SEMI' | 'RAW_PIPE'

export interface TubeProduct {
  id: string
  schedule_product_id: string
  schedule_number: string
  product_number: string
  item_number: string
  product_name: string
  quantity: string
  unit: string
  color: string
}
export interface TubeTask { id: string; task_number: string; order_number: string; products: TubeProduct[] }
export interface TubeFactory { id: string; name: string }
export interface TubeZone {
  id: string; name: string; warehouse_id: string; warehouse_name: string
  warehouse_type: 'MATERIAL' | 'SEMI_FINISHED'
}
export interface TubeOptions {
  tasks: TubeTask[]
  factories: TubeFactory[]
  zones: TubeZone[]
  source_kinds: Array<{ value: TubeSourceKind; label: string }>
}
export interface TubeSourceRow {
  component_identity: string; bom_line_id: string; part_name: string; material: string
  specification: string; thickness: string; cutting_length_mm: string; raw_color: string; spray_color: string
  order_required: string; stock_quantity: string | null; stock_unit: string | null; max_quantity: string
  pieces_per_bar: string | null; raw_bar_length_m: string | null; blockers: string[]
}
export interface TubeSourceContext {
  source_revision: string; source_kind: TubeSourceKind; schedule_product_id: string; product_line_id: string
  task_id: string; task_number: string; order_number: string; schedule_number: string
  product_number: string; item_number: string; product_name: string; quantity: string; unit: string; color: string
  craft_name: string; zone_id: string | null; ready: boolean; blockers: string[]
  tasks: TubeTask[]; factories: TubeFactory[]; zones: TubeZone[]; rows: TubeSourceRow[]
}
export interface TubeOrderInput {
  client_request_id: string; source_revision: string; schedule_product_id: string; source_kind: TubeSourceKind
  zone_id: string | null; planned_dispatch_date: string; expected_return_date: string; remark: string
  lines: Array<{ component_identity: string; quantity: string; factory_id: string }>
}
export interface TubeOrderResult {
  id: string; order_number: string; status: string; version: number; etag: string; created: boolean
  client_request_id: string; source_kind: TubeSourceKind; schedule_product_id: string; product_line_id: string
  planned_dispatch_date: string; expected_return_date: string; total_quantity: string
  total_stock_quantity: string | null; total_meters: string | null
}

export interface TubeReportOperation {
  work_item_id: string
  operation_id: string
  name: string
  scheme_id: string
  scheme_revision: number | string
  scheme_number?: string
  scheme_version?: number | string
  quantity: string
}
export interface TubeDetailLine {
  id: string
  component_identity: string
  part_name: string
  factory_id: string
  factory_name: string
  quantity: string
  stock_quantity: string | null
  meters: string | null
  material: string
  specification: string
  thickness: string
  cutting_length_mm: string
  raw_color: string
  spray_color: string
  pieces_per_bar: string | null
  raw_bar_length_m: string | null
  current_reported_minimum: string | null
  report_as_of?: string | null
  operations: TubeReportOperation[]
  basis_blockers: string[]
}
export interface TubeOrderAction {
  id: string
  kind: 'DISPATCH' | 'CANCEL'
  client_request_id: string
  confirmed_at: string
  actor_name: string
}
export interface TubeOrderDetail extends TubeOrderResult {
  source_label: string
  task_order_number: string
  task_number: string
  schedule_number: string
  product_number: string
  item_number: string
  product_name: string
  quantity: string
  unit: string
  color: string
  zone_id: string | null
  zone_name: string
  warehouse_name: string
  craft_name: string
  remark: string
  created_at: string
  created_by_name: string
  actual_dispatch_date: string | null
  dispatched_at: string | null
  dispatched_by_name: string
  cancelled_at: string | null
  cancelled_by_name: string
  cancel_remark: string
  permissions: { can_dispatch: boolean; can_cancel: boolean }
  lines: TubeDetailLine[]
  action?: TubeOrderAction
}
export interface TubeDispatchInput { client_request_id: string; actual_dispatch_date: string }
export interface TubeCancelInput { client_request_id: string; remark: string }
export interface TubePendingAction {
  order_id: string
  kind: 'DISPATCH' | 'CANCEL'
  etag: string
  payload: TubeDispatchInput | TubeCancelInput
}
