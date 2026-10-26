export type TubeSourceKind = 'METAL' | 'PUBLIC_SEMI' | 'RAW_PIPE' | 'PUBLIC_CUTTING' | 'SEWING'

export interface CuttingAttributes {
  pieces_per_set?: string | null
  fabric_material?: string
  fabric_specification?: string
  fabric_color?: string
  completed_craft_name?: string
}

export interface TubeProduct {
  craft_ids?: string[]
  id: string
  schedule_product_id: string
  schedule_number: string
  product_number: string
  item_number: string
  product_name: string
  quantity: string
  unit: string
  color: string
  specification: string
  specification_display: string
  material: string
  image_file_id: string | null
  image_url: string
}
export interface TubeTask { id: string; task_number: string; order_number: string; products: TubeProduct[] }
export interface TubeFactory { id: string; name: string }
export interface TubeZone {
  id: string; name: string; warehouse_id: string; warehouse_name: string
  warehouse_type: 'MATERIAL' | 'SEMI_FINISHED'
}
export interface TubeOptions {
  crafts?: Array<{ id: string; name: string; outsourcing_code: 'POWDER_COATING' | 'EMBROIDERY' | 'SCREEN_PRINTING' | 'CUTTING' | 'SEWING' }>
  tasks: TubeTask[]
  factories: TubeFactory[]
  zones: TubeZone[]
  source_kinds: Array<{ value: TubeSourceKind; label: string }>
}
export interface TubeSourceRow extends CuttingAttributes {
  current_reported_minimum?: string | null
  operations?: TubeReportOperation[]
  component_identity: string; bom_line_id: string; part_name: string; material: string
  specification: string; thickness: string; cutting_length_mm: string; raw_color: string; spray_color: string
  order_required: string; stock_quantity: string | null; stock_unit: string | null; max_quantity: string
  pieces_per_bar: string | null; raw_bar_length_m: string | null; blockers: string[]
}
export interface TubeMaterialZone {
  zone_id: string; zone_name: string; warehouse_id: string; warehouse_name: string; available_quantity: string
}
export interface TubeMaterialRow {
  bom_line_id: string; material_number: string; name: string; specification: string; material: string; color: string
  unit: string; required_quantity: string; order_remaining: string; available_stock: string; max_quantity: string
  blockers: string[]; zones: TubeMaterialZone[]
}
export interface TubeMaterialInput {
  bom_line_id: string; factory_id: string; quantity: string; zone_id: string
}
export interface TubeMaterialDetail extends Omit<TubeMaterialRow, 'required_quantity' | 'order_remaining' | 'available_stock' | 'max_quantity' | 'blockers' | 'zones'> {
  unit_consumption?: string | null
  id: string; component_identity: string | null; order_line_id: string | null; part_name: string; factory_id: string; factory_name: string
  quantity: string; zone_id: string; zone_name: string; warehouse_id: string; warehouse_name: string
}
export interface TubeSourceContext {
  category?: 'tube' | 'cutting'; craft_id?: string; material_category?: string; output_unit?: '支' | '套'
  source_revision: string; source_kind: TubeSourceKind; schedule_product_id: string; product_line_id: string
  task_id: string; task_number: string; order_number: string; schedule_number: string
  product_number: string; item_number: string; product_name: string; quantity: string; unit: string; color: string
  specification: string; specification_display: string; material: string; image_file_id: string | null; image_url: string
  craft_name: string; zone_id: string | null; ready: boolean; blockers: string[]
  tasks: TubeTask[]; factories: TubeFactory[]; zones: TubeZone[]; rows: TubeSourceRow[]
  material_rows?: TubeMaterialRow[]; material_source_revision?: string
}
export interface TubeOrderInput {
  craft_id?: string
  client_request_id: string; source_revision: string; schedule_product_id: string; source_kind: TubeSourceKind
  zone_id: string | null; planned_dispatch_date: string; expected_return_date: string; remark: string
  lines: Array<{ component_identity: string; quantity: string; factory_id: string; unit_price: string }>
  materials?: TubeMaterialInput[]; material_source_revision?: string
}
// 已提交但结果未知的旧请求须按原内容核对，不能补价或重写五金的绑定方式。
export interface TubePendingOrderInput extends Omit<TubeOrderInput, 'lines' | 'materials'> {
  lines: Array<{ component_identity: string; quantity: string; factory_id: string; unit_price?: string }>
  materials?: Array<TubeMaterialInput | { bom_line_id: string; component_identity: string; quantity: string; zone_id: string }>
}
export interface TubeOrderResult {
  category?: 'tube' | 'cutting'; craft_id?: string; craft_name?: string; output_unit?: '支' | '套'
  id: string; order_number: string; status: string; version: number; etag: string; created: boolean
  client_request_id: string; source_kind: TubeSourceKind; schedule_product_id: string; product_line_id: string
  planned_dispatch_date: string; expected_return_date: string; total_quantity: string
  total_stock_quantity: string | null; total_meters: string | null
  planned_amount: string | null
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
export interface TubeDetailLine extends CuttingAttributes {
  pieces_per_product?: string | null
  tube_diameter?: string | null
  order_required?: string | null
  id: string
  component_identity: string
  part_name: string
  factory_id: string
  factory_name: string
  quantity: string
  unit_price: string | null
  planned_amount: string | null
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
  updated_at?: string
  planned_quantity?: string
  specification?: string
  material?: string
  materials?: TubeMaterialDetail[]
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
