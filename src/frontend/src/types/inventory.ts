export type RecordStatus = 'ACTIVE' | 'DISABLED'
export type WarehouseType = 'MATERIAL' | 'SEMI_FINISHED' | 'FINISHED' | 'DEFECTIVE'

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
  category: string; product_number: string; product_code: string; product_name: string; item_number: string
  specification: string; actual_color: string; inventory_quantity: number; unit_id: string; unit_code: string
  unit_name: string; warehouse_id: string; warehouse_number: string; warehouse_name: string; zone_id: string
  zone_name: string; batch_count: number; occupied_box_slots: number; latest_inbound_time: string; receipt_ids: string[]
}
export interface FinishedGoodsReceipt {
  id: string; receipt_number: string; production_task_product_id: string | null; source_type: 'PRODUCTION_ORDER' | 'SAMPLE_INVENTORY'
  source_type_display: string; source_document_number: string; task_number_snapshot: string
  order_number_snapshot: string; category_snapshot: string; product_number_snapshot: string; product_code_snapshot: string
  product_name_snapshot: string; item_number_snapshot: string; specification_snapshot: string; actual_color: string
  supplier_id: string | null; supplier_name: string | null; unit_id: string; unit_code: string; unit_name: string
  warehouse_id: string; warehouse_number: string; warehouse_name: string; zone_id: string; zone_name: string
  location_id: string; location_number: string; received_quantity: number; remaining_quantity: number
  quantity_per_box: number | null; box_count: number | null; tail_quantity: number | null; occupied_box_slots: number | null
  remaining_box_slots: number | null; remark: string; received_by_name: string; received_at: string
}
export interface EligibleProduct { product_id: string; product_number: string; product_code: string; product_name: string; item_number: string; specification: string; pinyin_search: string }
export interface EligibleOrder { production_task_product_id: string; task_number: string; order_number: string; order_quantity: string; maximum_receivable: number; received_total: number; remaining_receivable: number; actual_color_default: string; unit_id: string; unit_code: string; unit_name: string }
export interface InventoryOptions {
  warehouses: Warehouse[]
  zones: WarehouseZone[]
  locations: WarehouseLocation[]
  suppliers: { id: string; supplier_number: string; supplier_name: string }[]
  product_colors: { id: string; color_card: string; color_code: string; color_name: string }[]
  production_orders: { id: string; task_number: string; order_number: string }[]
}
export interface PaginatedInventory { count: number; results: FinishedGoodsInventoryRow[] }

export interface MaterialInventoryRow {
  stock_mode?: 'LEGACY' | 'PUBLIC_V2'; completed_craft?: string; completed_craft_code?: string
  processing_status?: string; processing_status_label?: string; tube_thickness?: string | null; cutting_length_mm?: number | null
  stock_kind?: 'RAW' | 'SEMI'; measurement_kind?: string; raw_bar_length_m?: string | null; meter_quantity?: string | null
  inventory_key: string; stock_item_id: string; material_number: string; color: string; section_type: string; section_title: string; category: string
  material: string; part_name: string; specification: string; raw_material: string; unit: string
  inventory_quantity: string
  warehouse_id: string; warehouse_number: string; warehouse_name: string; zone_id: string; zone_name: string
  location_id: string | null; location_number: string | null; inbound_count: number; latest_inbound_date: string; latest_inbound_time: string
}
export interface EligibleMaterialPurchaseOrder {
  id: string; order_number: string; production_task_id: string | null; production_task_number: string | null
  source_type: 'PRODUCTION' | 'SAMPLE'; source_number: string
  sales_order_number: string; supplier_names: string[]; remaining_line_count: number
}
export interface ProcurementInboundProductSummary {
  product_line_id: string; product_name: string; item_number: string; specification: string; color_name: string; material: string
}
export interface ProcurementInboundOrder {
  id: string; order_number: string; source_type: 'PRODUCTION' | 'SAMPLE'; source_number: string; sales_order_number: string
  supplier_names: string[]; line_count: number; remaining_line_count: number
  supplier_summary: { supplier_id: string | null; supplier_name: string; total_amount: string | null }[]
  currency_code: string
  product_summary: ProcurementInboundProductSummary[]
  pending_quality_count: number; confirmed_batch_count: number
  received_quantity: string; return_quantity: string
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
  material_attributes_snapshot?: import('./purchaseOrder').MaterialAttributeSnapshot
  raw_bar_length_m?: string | null; actual_bar_count?: number | null; remaining_bar_count?: number | null
  id: string; line_number: number; section_type: string; section_title: string; category: string
  material: string; part_name: string; specification: string; raw_material: string; unit: string
  supplier_name: string; purchased_quantity: string; remaining_quantity: string; pinyin_search: string
}
export interface MaterialReceivingOptions {
  warehouses: Pick<Warehouse, 'id' | 'warehouse_number' | 'warehouse_name'>[]
  zones: Pick<WarehouseZone, 'id' | 'warehouse' | 'zone_name'>[]
}

export interface MaterialFilterOptions extends MaterialReceivingOptions {
  sections: string[]; stock_mode?: 'LEGACY' | 'PUBLIC_V2'
  warehouses: (Pick<Warehouse, 'id' | 'warehouse_number' | 'warehouse_name'> & { warehouse_type?: WarehouseType })[]
}

export interface MaterialInventoryOptions {
  purchasing_order_count?: number
  warehouses: Warehouse[]; zones: WarehouseZone[]; locations: WarehouseLocation[]; sections: string[]
  production_orders: { id: string; task_number: string; order_number: string }[]
}
export interface MaterialInboundLine {
  measurement_kind?: string; raw_bar_length_m?: string | null; received_bar_count?: number | null; accepted_bar_count?: number | null; return_bar_count?: number | null
  id: string; purchase_order_line_id: string | null; raw_material_information_id: string | null; zone_id: string; location_id: string | null
  received_quantity: string; return_quantity: string; accepted_quantity: string; remark: string; quality_remark: string
  purchase_order_number_snapshot: string; production_task_number_snapshot: string; sales_order_number_snapshot: string
  supplier_number_snapshot: string; supplier_name_snapshot: string; bom_number_snapshot: string; product_name_snapshot: string
  section_type_snapshot: string; section_title_snapshot: string; category_snapshot: string; material_snapshot: string; part_name_snapshot: string
  specification_snapshot: string; raw_material_snapshot: string; source_unit_text_snapshot: string
  material_attributes_snapshot?: import('./purchaseOrder').MaterialAttributeSnapshot
  warehouse_id: string; warehouse_number: string; warehouse_name: string; zone_name: string; location_number: string | null
}
export interface MaterialInbound {
  id: string; inbound_number: string; purchase_order_id: string | null; purchase_order_number: string | null
  source_type: 'PURCHASE' | 'MANUAL'; source_type_display: string
  inbound_date: string; status: 'PENDING_QUALITY' | 'CONFIRMED'; status_display: string; remark: string
  received_by_name: string; quality_confirmed_by_name: string | null; quality_confirmed_at: string | null
  total_received_quantity: string; total_return_quantity: string; total_accepted_quantity: string
  created_at: string; updated_at: string; lines: MaterialInboundLine[]
}
export interface PaginatedMaterialInventory { count: number; results: MaterialInventoryRow[] }

export interface MaterialInventorySummary {
  measurement_kind?: string; meter_quantity?: string | null
  stock_item_id: string; material_number: string; material_name: string; category: string; specification: string
  color: string; unit: string; current_quantity: string; available_quantity: string; defective_quantity: string
  cumulative_inbound_quantity: string; cumulative_issued_quantity: string
  zones: { zone_id: string; warehouse_number: string; warehouse_name: string; zone_name: string; quality: string; quantity: string }[]
}
export interface MaterialOrderPurchase {
  purchase_order_id: string; purchase_order_number: string; production_task_id: string | null
  production_task_number: string; purchase_quantity: string; actual_inbound_quantity: string
  pending_inbound_quantity: string; unit: string; can_view_purchase_detail: boolean
}
export interface MaterialOrderIssue {
  material_issue_id: string; issue_number: string; production_task_id: string; production_task_number: string
  workshop: string; recipient: string; issue_at: string; issued_quantity: string; unit: string
  reviewer: string; reviewed_at: string
}
