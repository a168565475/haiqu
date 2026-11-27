export type RecordStatus = 'ACTIVE' | 'DISABLED'
export type WarehouseType = 'MATERIAL' | 'SEMI_FINISHED' | 'FINISHED' | 'DEFECTIVE'

export type ManualMaterialReceivingLine = {
  zone_id: string
  location_id?: string | null
  received_quantity?: string | number
  received_bar_count?: string | number
  received_weight_kg?: string | number
  raw_bar_length_m?: string | number
  remark?: string
} & ({
  material_catalog_id: string
  material_selection: import('./materialCatalog').MaterialSelectionInput
  raw_material_id?: never
} | {
  // 兼容浏览器中历史待核对请求；新单使用材料目录选料。
  raw_material_id: string
  material_catalog_id?: never
  material_selection?: never
})

export interface ManualMaterialReceivingPayload {
  client_request_id: string
  inbound_date: string
  remark: string
  items: ManualMaterialReceivingLine[]
}

export type MaterialTransferDirection = 'IN' | 'OUT'
export interface MaterialTransferLinePayload {
  material_catalog_id: string
  material_selection: import('./materialCatalog').MaterialSelectionInput
  zone_id: string
  quantity?: string
  raw_bar_count?: string
  raw_bar_length_m?: string
}
export interface MaterialTransferPayload {
  client_request_id: string
  direction: MaterialTransferDirection
  transfer_date: string
  remark: string
  items: MaterialTransferLinePayload[]
}
export interface MaterialTransferLineRecord {
  line_key: string
  material_catalog_id: string
  material_selection_snapshot: import('./materialCatalog').MaterialSelectionSnapshot
  quantity: string
  raw_bar_length_m: string | null
  weight_quantity?: string | null
  zone_id: string
  direction: MaterialTransferDirection
  catalog_name: string
  unit_name: string
  zone_name: string
  warehouse_name: string
}
export interface MaterialTransferRecord {
  id: string
  transfer_number: string
  direction: MaterialTransferDirection
  direction_display: string
  transfer_date: string
  remark: string
  operated_by_name: string
  created_at: string
  lines: MaterialTransferLineRecord[]
}

export interface Warehouse {
  id: string; warehouse_number: string; warehouse_name: string; warehouse_type: WarehouseType
  warehouse_type_display: string; address: string; status: RecordStatus; status_display: string
  responsible_person_name: string; contact_phone: string; zone_count: number; location_count: number
  capacity_box_slots_total: number | null; occupied_box_slots: number; updated_at: string
}
export interface WarehouseZone {
  id: string; warehouse: string; warehouse_number: string; warehouse_name: string; zone_name: string
  status: RecordStatus; status_display: string; location_count: number; capacity_box_slots_total: number | null
  occupied_box_slots: number; updated_at: string
}
export interface WarehouseLocation {
  id: string; zone: string; warehouse_id: string; warehouse_number: string; warehouse_name: string
  zone_name: string; location_number: string; capacity_box_slots: number | null; unique_key: string
  warehouse_type: WarehouseType; warehouse_type_display: string; status: RecordStatus; status_display: string
  occupied_box_slots: number; remaining_box_slots: number | null; updated_at: string
}
export interface FinishedGoodsInventoryRow {
  inventory_key: string; product_id: string | null
  product_catalog_id?: string | null; product_selection_key?: string
  task_number: string; category: string; product_number: string; product_code: string; product_name: string; item_number: string
  specification: string; actual_color: string; inventory_quantity: number; unit_id: string; unit_code: string
  unit_name: string; warehouse_id: string; warehouse_number: string; warehouse_name: string; zone_id: string
  zone_name: string; batch_count: number; occupied_box_slots: number; latest_inbound_time: string; receipt_ids: string[]
}
export interface FinishedGoodsReceipt {
  id: string; receipt_number: string; production_task_product_id: string | null; source_type: 'PRODUCTION_ORDER' | 'SAMPLE_INVENTORY'; status?: 'PENDING' | 'CONFIRMED'
  source_type_display: string; source_document_number: string; task_number_snapshot: string
  order_number_snapshot: string; category_snapshot: string; product_number_snapshot: string; product_code_snapshot: string
  product_name_snapshot: string; item_number_snapshot: string; specification_snapshot: string; material_snapshot?: string; actual_color: string
  supplier_id: string | null; supplier_name: string | null; unit_id: string; unit_code: string; unit_name: string
  warehouse_id: string | null; warehouse_number: string | null; warehouse_name: string | null; zone_id: string | null; zone_name: string | null
  location_id: string | null; location_number: string | null; received_quantity: number; remaining_quantity: number
  quantity_per_box: number | null; box_count: number | null; tail_quantity: number | null; occupied_box_slots: number | null
  remaining_box_slots: number | null; remark: string; received_by_name: string; received_at: string
}
export interface InventoryOptions {
  warehouses: Warehouse[]
  zones: WarehouseZone[]
  locations: WarehouseLocation[]
  suppliers: { id: string; supplier_number: string; supplier_name: string }[]
  product_colors: { id: string; color_card: string; color_code: string; color_name: string }[]
  production_orders: { id: string; task_number: string; order_number: string }[]
  employees?: InventoryEmployeeOption[]
}
export interface PaginatedInventory { count: number; results: FinishedGoodsInventoryRow[] }
export interface InventoryEmployeeOption { id: string; display_name: string; employee_code?: string }
export interface FinishedGoodsOutboundLine {
  id: string; receipt_id: string; receipt_number: string; outbound_quantity: number; quantity_per_box: number
  box_count: number; tail_quantity: number; before_quantity: number; after_quantity: number
  task_number_snapshot?: string; product_code_snapshot?: string; product_name_snapshot?: string; material_snapshot?: string
  item_number_snapshot?: string; specification_snapshot?: string; actual_color?: string; unit_name?: string
  warehouse_name?: string; location_number?: string
  order_quantity?: number | null; received_quantity?: number; warehouse_id?: string
}
export interface FinishedGoodsOutbound {
  id: string; outbound_number: string; task_number_snapshot?: string; production_task_number?: string
  responsible_employee_id?: string | null; responsible_employee_name?: string; responsible_name_snapshot?: string; receiver_name?: string
  shipment_date?: string | null; loading_fee?: string | number | null; other_fee?: string | number | null
  remark: string; outbound_by_name?: string; outbound_at: string; loading_images?: Array<{ id?: string; url: string; name?: string }>
  lines: FinishedGoodsOutboundLine[]
}
export type FinishedGoodsOutboundDetail = FinishedGoodsOutbound

export interface MaterialInventoryRow {
  material_catalog_id?: string | null; material_selection_snapshot?: import('./materialCatalog').MaterialSelectionSnapshot
  inventory_attributes?: Record<string, string | number | null>
  balance_id?: string; identity_key?: string
  stock_mode?: 'LEGACY' | 'PUBLIC_V2'; completed_craft?: string; completed_craft_code?: string
  processing_status?: string; processing_status_label?: string; tube_thickness?: string | null; cutting_length_mm?: number | null
   stock_kind?: 'RAW' | 'SEMI'; measurement_kind?: string; raw_bar_length_m?: string | null; meter_quantity?: string | null; weight_quantity?: string | null; weight_quantity_kg?: string | null
  inventory_key: string; stock_item_id: string; material_number: string; color: string; section_type: string; section_title: string; category: string
  material: string; part_name: string; specification: string; raw_material: string; unit: string
  inventory_quantity: string
  warehouse_id: string; warehouse_number: string; warehouse_name: string; zone_id: string; zone_name: string
  location_id: string | null; location_number: string | null; inbound_count: number; latest_inbound_date: string; latest_inbound_time: string
}
export interface EligibleMaterialPurchaseOrder {
  id: string; order_number: string; production_task_id: string | null; production_task_number: string | null
  batch_number: number | null
  source_type: 'PRODUCTION' | 'SAMPLE'; source_number: string
  sales_order_number: string; supplier_names: string[]; remaining_line_count: number
}
export interface ProcurementInboundProductSummary {
  product_line_id: string; product_name: string; item_number: string; specification: string; color_name: string; material: string
}
export type PurchaseReceivingSection = 'A' | 'B' | 'C' | 'D'

export interface ProcurementInboundOrder {
  id: string; order_number: string; source_type: 'PRODUCTION' | 'SAMPLE'; source_number: string; sales_order_number: string
  production_task_number: string
  batch_number: number | null
  supplier_names: string[]; line_count: number; remaining_line_count: number
  receiving_sections?: { id: PurchaseReceivingSection; name: string }[]
  supplier_summary: { supplier_id: string | null; supplier_name: string; total_amount: string | null }[]
  currency_code: string
  product_summary: ProcurementInboundProductSummary[]
  pending_quality_count: number; confirmed_batch_count: number
  received_quantity: string | null; return_quantity: string | null
  received_weight_quantity: string | null; return_weight_quantity: string | null; weight_unit: boolean; quantity_unit?: string
  receipt_progress_percent?: string | null
  receiving_status: 'PENDING_RECEIPT' | 'PARTIAL_RECEIVED' | 'RECEIPT_COMPLETE' | 'COMPLETED'
  workflow_status: 'PENDING_RECEIPT' | 'PARTIAL_RECEIVED' | 'PENDING_QUALITY' | 'PENDING_PROCUREMENT_CONFIRMATION' | 'PENDING_RETURN' | 'COMPLETED'
  return_status: 'NONE' | 'QUALITY_GENERATED' | 'PROCUREMENT_CONFIRMED' | 'COMPLETED'
  workflow_status_display: string; updated_at: string
}
export interface ManualMaterialOption {
  id: string; material_number: string; category_id: string; category_name: string
  material_name: string; specification: string; material: string; color_name: string; unit_name: string
}
export interface ManualMaterialOptions {
  categories: { id: string; name: string }[]
  materials: ManualMaterialOption[]
}
export interface EligibleMaterialLine {
  receipt_quantity_mode?: 'ROOTS' | null
  measurement_kind?: string; piece_unit?: string; quantity_unit?: string; unit_weight_kg?: string | null
  suggested_warehouse_id?: string | null
  material_catalog_id?: string | null; material_selection_snapshot?: import('./materialCatalog').MaterialSelectionSnapshot | Record<string, never>
  material_attributes_snapshot?: import('./purchaseOrder').MaterialAttributeSnapshot
   raw_bar_length_m?: string | null; raw_bar_weight_kg?: string | null; actual_bar_count?: number | null; remaining_bar_count?: number | null; weight_unit?: boolean; remaining_weight_kg?: string | null
  id: string; line_number: number; section_type: string; section_title: string; category: string
  material: string; part_name: string; specification: string; raw_material: string; unit: string
  supplier_name: string; purchased_quantity: string; remaining_quantity: string; pinyin_search: string
}
export interface EligibleMaterialLinesResponse {
  data: EligibleMaterialLine[]
  material_section_display?: string
}
export type PurchaseReceiptStatus = 'PENDING_QUALITY' | 'CONFIRMED' | 'RETURNED'
export type ReceiptRecordSource = 'PURCHASE' | 'TRANSFER'
export interface PurchaseReceiptRecord {
  id: string
  source: ReceiptRecordSource
  production_task_number: string
  inbound_number: string
  purchase_order_number: string
  material_section_display: string
  product_summary: (Omit<ProcurementInboundProductSummary, 'product_line_id'> & { product_line_id: string | null })[]
  supplier_names: string[]
  batch_number: number | null
  inbound_date: string
  received_by_name: string
  quality_confirmed_by_name: string
  quality_confirmed_at: string | null
  line_count: number
  status: PurchaseReceiptStatus
  can_quality_confirm: boolean
}
export type ReceiptRecordDetail =
  | { source: 'PURCHASE'; data: import('./purchaseOrderReadDetail').PurchaseReadInbound & { purchase_order_id: string; sample_number?: string } }
  | { source: 'TRANSFER'; data: MaterialTransferRecord }
export interface PurchaseReceiptRecordsPage {
  data: PurchaseReceiptRecord[]
  total: number
}
export interface MaterialReceivingOptions {
  warehouses: (Pick<Warehouse, 'id' | 'warehouse_number' | 'warehouse_name'> & { warehouse_type?: WarehouseType })[]
  zones: Pick<WarehouseZone, 'id' | 'warehouse' | 'zone_name'>[]
}
export interface SampleMaterialReceivingPayload {
  purchase_order_id: string
  client_request_id: string
  inbound_date: string
  remark: string
  items: Array<{ purchase_order_line_id: string; zone_id: string; remark: string; received_weight_kg?: string; received_bar_count?: string }>
}

export interface MaterialInventorySection {
  key: string
  label: string
  fields: { key: string; label: string }[]
}

export interface MaterialFilterOptions extends MaterialReceivingOptions {
  sections: string[]; stock_mode?: 'LEGACY' | 'PUBLIC_V2'
  bom_sections?: Record<'RAW' | 'SEMI', MaterialInventorySection[]>
  warehouses: (Pick<Warehouse, 'id' | 'warehouse_number' | 'warehouse_name'> & { warehouse_type?: WarehouseType })[]
}

export interface MaterialInventoryOptions {
  purchasing_order_count?: number
  warehouses: Warehouse[]; zones: WarehouseZone[]; locations: WarehouseLocation[]; sections: string[]
  production_orders: { id: string; task_number: string; order_number: string }[]
}
export interface MaterialInboundLine {
  piece_unit?: string; quantity_unit?: string; received_piece_count?: string | null; accepted_piece_count?: string | null; return_piece_count?: string | null
  material_catalog_id?: string | null
  material_selection_snapshot?: import('./materialCatalog').MaterialSelectionSnapshot | Record<string, never>
  calculation_snapshot?: Record<string, unknown>
  measurement_kind?: string; raw_bar_length_m?: string | null; bar_weight_kg?: string | null; received_bar_count?: number | null; accepted_bar_count?: number | null; return_bar_count?: number | null
  id: string; purchase_order_line_id: string | null; raw_material_information_id: string | null; zone_id: string; location_id: string | null
   received_quantity: string; received_weight_kg?: string | null; return_quantity: string; accepted_quantity: string; accepted_weight_kg?: string | null; return_weight_kg?: string | null; remark: string; quality_remark: string
  purchase_order_number_snapshot: string; production_task_number_snapshot: string; sales_order_number_snapshot: string
  supplier_number_snapshot: string; supplier_name_snapshot: string; bom_number_snapshot: string; product_name_snapshot: string
  section_type_snapshot: string; section_title_snapshot: string; category_snapshot: string; material_snapshot: string; part_name_snapshot: string
  specification_snapshot: string; raw_material_snapshot: string; source_unit_text_snapshot: string
  material_attributes_snapshot?: import('./purchaseOrder').MaterialAttributeSnapshot
  warehouse_id: string; warehouse_number: string; warehouse_name: string; zone_name: string; location_number: string | null
}
export interface MaterialInbound {
  id: string; inbound_number: string; purchase_order_id: string | null; purchase_order_number: string | null
  sample_number?: string
  source_type: 'PURCHASE' | 'MANUAL'; source_type_display: string
  inbound_date: string; status: 'PENDING_QUALITY' | 'CONFIRMED'; status_display: string; remark: string
  material_section?: PurchaseReceivingSection | ''; material_section_display?: string
  received_by_name: string; quality_confirmed_by_name: string | null; quality_confirmed_at: string | null
  total_received_quantity: string; total_return_quantity: string; total_accepted_quantity: string
  created_at: string; updated_at: string; lines: MaterialInboundLine[]
}
export interface PaginatedMaterialInventory { count: number; results: MaterialInventoryRow[] }

export interface MaterialInventorySummary {
   measurement_kind?: string; meter_quantity?: string | null; weight_quantity?: string | null; weight_quantity_kg?: string | null
  available_weight_quantity?: string | null
  stock_item_id: string; material_number: string; material_name: string; category: string; specification: string
  color: string; unit: string; current_quantity: string; available_quantity: string; defective_quantity: string
  cumulative_inbound_quantity: string; cumulative_issued_quantity: string
  zones: { zone_id: string; warehouse_number: string; warehouse_name: string; zone_name: string; quality: string; quantity: string; bar_weight_kg?: string | null; weight_quantity?: string | null; weight_quantity_kg?: string | null }[]
}
export interface MaterialOrderPurchase {
  bar_counts?: { ordered: number; accepted: number | null; pending: number | null } | null
   purchase_order_id: string; purchase_order_number: string; production_task_id: string | null
  production_task_number: string; purchase_quantity: string; actual_inbound_quantity: string | null
  pending_inbound_quantity: string | null; weight_quantity_kg?: string | null; weight_unit?: boolean; unit: string; can_view_purchase_detail: boolean
}
export interface MaterialOrderIssue {
  material_issue_id: string; issue_number: string; production_task_id: string; production_task_number: string
  workshop: string; recipient: string; issue_at: string; issued_quantity: string; unit: string
  reviewer: string; reviewed_at: string
}
