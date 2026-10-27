import type { PageMeta } from './referenceData'

export type FactoryStatus = 'ACTIVE' | 'DISABLED'
export type OutsourcingOrderStatus = 'PENDING_DISPATCH' | 'PROCESSING' | 'PARTIAL_RETURN' | 'COMPLETED' | 'CLOSED' | 'CANCELLED'

export interface OutsourcingCraftOption {
  id: string
  name: string
  outsourcing_code?: 'SEWING' | 'CUTTING' | 'POWDER_COATING' | 'EMBROIDERY' | 'SCREEN_PRINTING'
}

export interface OutsourcingFactory {
  id: string
  factory_number: string
  name: string
  crafts: OutsourcingCraftOption[]
  processing_type: string
  estimated_output: string | null
  estimated_output_unit: string
  estimated_output_period: string
  contact_name: string
  contact_phone: string
  address: string
  remark: string
  payment_cycle: 'MONTHLY'
  payment_cycle_display: string
  status: FactoryStatus
  status_display: string
  version: number
  created_at: string
  updated_at: string
  related_orders?: OutsourcingOrder[]
}

export interface OutsourcingFactoryInput {
  craft_ids: string[]
  name: string
  processing_type: string
  estimated_output: string | null
  estimated_output_unit: string
  estimated_output_period: string
  contact_name: string
  contact_phone: string
  address: string
  remark: string
  payment_cycle: 'MONTHLY'
}

export interface OutsourcingFactoryOption {
  id: string
  name: string
  crafts: OutsourcingCraftOption[]
}

export interface OutsourcingOrder {
  id: string
  direct_handoff?: boolean
  direct_handoff_lock_reason?: string
  can_delete: boolean
  can_revoke_dispatched: boolean
  order_number: string
  schedule_id: string
  schedule_number: string
  production_task_number: string
  craft: OutsourcingCraftOption
  delivery_date: string
  status: OutsourcingOrderStatus
  status_display: string
  product: Record<string, string | null>
  product_count: number
  processing_count: number
  returned_processing_count: number | null
  factory_names: string[]
  factory_count: number
  planned_amount: string
  factory_allocated_quantity: string | null
  factory_allocated_unit: string | null
  factory_allocation_count: number | null
  factory_returned_quantity: number | null
  factory_remaining_quantity: number | null
  updated_at: string
}

export interface OutsourcingOptions {
  crafts: OutsourcingCraftOption[]
  factories: OutsourcingFactoryOption[]
  statuses: Array<{ value: OutsourcingOrderStatus; label: string }>
  bom_confirmation_rule: 'LATEST_VERIFIED'
  material_overage_rule: 'SHARED_CONFIRMED_ALLOWANCE'
  semi_finished_zones: Array<{ id: string; name: string }>
  defective_zones: Array<{ id: string; name: string }>
  receivers: Array<{ id: string; name: string; employee_code: string }>
}

export interface OutsourcingDispatchCandidate {
  available_input_quantity: string
  available_meters: string | null
  raw_bar_length_m: string | null
  inbound_line_id: string
  inbound_number: string
  inbound_date: string
  zone_id: string
  warehouse_name: string
  zone_name: string
  location_name: string
  source_unit: string
  material_unit: string
  same_unit: boolean
  accepted_quantity: string
  available_quantity: string
}

import type { BomAttributeField } from './bomAttributes'

export interface OutsourcingDispatchContext {
  stock_mode?: 'LEGACY' | 'PUBLIC_V2'
  order_id: string
  order_number: string
  materials: Array<{
    material_item_id: string
    conversion_snapshot: OutsourcingConversion
    factory_name: string
    material_number: string
    material_name: string
    specification: string
    color: string
    bom_attributes?: BomAttributeField[]
    planned_issue_quantity: string
    unit: string
    procurement_required_quantity: string | null
    procurement_unit: string
    procurement_conversion: boolean
    suggested_conversion_factor: string
    conversion_evidence: string
    identity_resolved: boolean
    planned_batches?: Array<{ inbound_line_id: string; quantity: string }>
    candidates: OutsourcingDispatchCandidate[]
    zones: Array<{
      zone_id: string
      warehouse_name: string
      zone_name: string
      available_quantity: string
      available_input_quantity: string
      available_meters: string | null
    }>
    required_quantity: string
    internal_issued_quantity: string
    outsourcing_issued_quantity: string
    pending_issue_quantity: string
    order_remaining: string
    available_stock: string
    max_issue_quantity: string
    quota_error: string
  }>
}

export interface OutsourcingOrderDetailAllocation {
  id: string
  factory_id: string
  factory_name: string
  allocated_quantity: string
  unit: string
  unit_price: string
  planned_amount: string
  remark: string
  returned_quantity: string | null
  remaining_quantity: string | null
  materials: Array<{
    id: string
    bom_line_id: string
    material_number: string
    name: string
    unit_consumption?: string | null
    material?: string
    specification: string
    color: string
    bom_attributes?: BomAttributeField[]
    category_label: string
    unit: string
    reference_required_quantity: string | null
    planned_issue_quantity: string
    planned_batches?: Array<{ inbound_line_id: string; quantity: string }>
    difference_reason: string
    remark: string
  }>
}

export interface OutsourcingOrderDetail {
  stock_mode?: 'LEGACY' | 'PUBLIC_V2'
  id: string
  direct_handoff?: boolean
  direct_handoff_lock_reason?: string
  direct_handoff_summary?: Array<{
    allocation_id: string | null
    part_name: string
    factory_id: string
    factory_name: string
    unit: string
    handoff_pieces: number
    returned_good_pieces: number
    returned_unsprayed_pieces: number
    remaining_return_pieces: number
  }>
  order_number: string
  schedule_id: string
  schedule_number: string
  production_task_id: string
  production_task_number: string
  sales_order_number: string
  customer_name: string
  order_date: string | null
  craft: OutsourcingCraftOption
  delivery_date: string
  status: OutsourcingOrderStatus
  status_display: string
  remark: string
  version: number
  created_by: { id: string; name: string }
  created_at: string
  updated_at: string
  planned_amount: string
  factory_names: string[]
  products: Array<{
    id: string
    schedule_product_id: string
    image_file_id: string | null
    unit_name: string
    bom_id: string
    bom_number: string
    bom_version: number
    product: Record<string, string | null>
    order_quantity: number
    planned_quantity: number
    processing_items: Array<{
      id: string
      bom_line_id: string
      part_name: string
      category: string
      specification: string
      color: string
      bom_attributes?: BomAttributeField[]
      quantity: string
      unit: string
      processing_requirement: string
      allocations: OutsourcingOrderDetailAllocation[]
    }>
  }>
  can_cancel: boolean
  can_delete: boolean
  can_revoke_dispatched: boolean
  can_confirm_dispatch: boolean
  can_confirm_return: boolean
  can_return_raw: boolean
  can_reconcile: boolean
  can_complete: boolean
  dispatch: null | {
    id: string
    dispatch_number: string | null
    dispatch_date: string
    confirmed_at: string
    confirmed_by: string
    line_count: number
    remark: string
    lines: Array<{
      id: string
      material_item_id: string
      inbound_line_id: string | null
      inbound_number: string
      warehouse_name: string
      zone_name: string
      location_name: string
      source_quantity: string
      issued_piece_count: number | null
      issued_meters: string | null
      source_unit: string
      material_quantity: string
      material_unit: string
    }>
  }
  returns: Array<{
    id: string
    return_number: string
    factory_id: string | null
    factory_name: string
    return_date: string
    delivery_note_number: string
    zone_id: string | null
    zone_name: string
    defective_zone_id: string | null
    defective_zone_name: string
    received_by: string
    confirmed_at: string
    confirmed_by: string
    remark: string
    lines: Array<{
      id: string
      allocation_id: string
      returned_quantity: string
      unit: string
      component: string
      specification: string
      color: string
      bom_attributes?: BomAttributeField[]
      quality: 'AVAILABLE' | 'DEFECTIVE'
      quality_display: string
      balance_id: string
    }>
  }>
}

export interface Paginated<T> {
  data: T[]
  meta: PageMeta
}

export interface VersionedFactory {
  data: OutsourcingFactory
  etag: string
}

export interface VersionedOutsourcingOrder {
  data: OutsourcingOrderDetail
  etag: string
}

export interface OutsourcingConversion {
  schema_version: number
  kind: 'PIPE' | 'FABRIC' | 'OTHER'
  quantity_basis?: 'OUTPUT_SETS'
  raw_input_unit?: string
  pieces_per_bar?: number
  raw_bar_length_m?: string
  cutting_length_mm?: number
  fabric_meters_per_set?: string
  material_line_id?: string
  raw_material_id?: string
}
export interface OutsourcingRawPosition {
  dispatch_line_id: string; allocation_id: string; factory_id: string; factory_name: string
  material_name: string; component: string; inbound_number: string; zone_name: string; unit: string
  dispatched: string; returned: string; input: string; loss: string; remaining: string
  conversion_snapshot: OutsourcingConversion
  bom_attributes?: BomAttributeField[]
}
export interface OutsourcingOutputPosition {
  allocation_id: string; factory_id: string; factory_name: string; component: string; specification?: string; unit: string
  planned: string; capacity: string; good: string; defective: string; scrap: string; remaining: string
  color?: string; bom_attributes?: BomAttributeField[]
}
export interface OutsourcingReconciliation {
  raw_materials: OutsourcingRawPosition[]; outputs: OutsourcingOutputPosition[]
  blockers: string[]; can_complete: boolean
  records: Array<{ id: string; kind: string; quantity: string; unit: string; reason: string; actor: string; confirmed_at: string }>
  raw_returns: Array<{ id: string; dispatch_line_id: string; quantity: string; meters: string | null; reason: string; actor: string; confirmed_at: string }>
}
export interface OutsourcingReconciliationInput {
  allocation_id: string; dispatch_line_id: string | null
  kind: 'RAW_INPUT' | 'RAW_LOSS' | 'OUTPUT_SCRAP'; quantity: string; reason: string
}
