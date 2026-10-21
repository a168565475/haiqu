import type { OutsourcingOptions, OutsourcingOrder } from './outsourcing'

export interface P4UnsprayedReturn {
  id: string
  handoff_id: string
  source_id: string
  original_order_id: string
  returned_pieces: number
  received_by_employee_id: string
  storage_location: string
  return_date: string
  remark: string
  inventory_effect: 'NONE'
  completed_rework_pieces?: number
  remaining_rework_pieces?: number
  reworks?: P4Rework[]
  post_closure?: boolean
}

export interface P4OriginalHandoff {
  id: string
  original_order_id: string
  original_order_number?: string
  factory_id: string
  factory_name?: string
  handoff_pieces: number
  handoff_date: string
  returned_unsprayed_pieces: number
  remaining_return_pieces?: number
  return_blockers?: string[] | Record<string, string | string[]>
  unsprayed_returns?: P4UnsprayedReturn[]
  original_order_status?: string
}

export interface P4Source {
  issue_line_id: string
  source_id: string | null
  issue_number: string
  production_task_id: string
  product_line_id: string
  component_identity: string
  part_name: string
  unit: string
  issued_pieces: number
  completed_pieces: number
  dispatched_pieces: number
  reserved_pieces: number
  unfinished_pieces: number
  unallocated_pieces: number
  available_pieces: number
  remaining_completion_pieces: number
  status: 'OPEN' | 'CLOSED'
  version: number
  bar_count: number
  meters: string
  can_register: boolean
  can_close: boolean
  blockers: string[] | Record<string, string | string[]>
  etag: string | null
  source_snapshot?: Record<string, unknown>
  conversion_snapshot?: Record<string, unknown>
  completions?: Array<{ id: string; good_pieces: number; completion_date: string; actor_name: string; created_at: string }>
  closure?: { remark: string; quantities: Record<string, unknown>; actor_name: string; created_at: string } | null
  original_handoffs?: P4OriginalHandoff[]
}

export interface P4HandoffDetail extends P4OriginalHandoff {
  source_id: string
  original_order_id: string
  original_order_number: string
  factory_id: string
  factory_name: string
  remaining_return_pieces: number
  good_return_context: P4OriginalGoodReturnContext
  source_etag: string | null
  original_order_closure?: P4OriginalOrderClosure | null
}

export interface P4OriginalGoodReturnContext {
  etag: string | null
  original_order_id: string
  original_order_number: string
  original_order_status: string
  allocation_id: string | null
  part_name: string
  factory_id: string
  factory_name: string
  unit: string
  handoff_pieces: number
  returned_good_pieces: number
  returned_unsprayed_pieces: number
  remaining_return_pieces: number
  can_return: boolean
  blockers: string[]
  post_closure?: boolean
  closure?: P4OriginalOrderClosure | null
  good_returns: Array<{
    id: string
    return_number: string
    good_pieces: number
    zone_id: string
    zone_name: string
    received_by_employee_id: string | null
    received_by_employee_name: string
    return_date: string
    remark: string
    actor_name: string
    created_at: string
    post_closure?: boolean
  }>
}

export interface P4OriginalOrderQuantities {
  planned_pieces: number
  cancelled_pending_pieces: number
  effective_planned_pieces: number
  pending_handoff_pieces: number
  handoff_pieces: number
  returned_good_pieces: number
  returned_unsprayed_pieces: number
  remaining_return_pieces: number
}

export interface P4OriginalOrderPart extends P4OriginalOrderQuantities {
  allocation_id: string
  product_line_id: string
  part_name: string
  factory_id: string
  factory_name: string
  product_name: string
  product_number: string
  specification: string
  can_cancel_pending: boolean
}

export interface P4OriginalOrderClosure {
  id: string
  remark: string
  actor_employee_id: string
  actor_name: string
  created_at: string
  quantity_snapshot: { parts: P4OriginalOrderPart[]; totals: P4OriginalOrderQuantities }
}

export interface P4OriginalOrderContext {
  original_order_id: string
  original_order_number: string
  original_order_status: string
  etag: string
  parts: P4OriginalOrderPart[]
  totals: P4OriginalOrderQuantities
  can_close: boolean
  blockers: string[]
  closure: P4OriginalOrderClosure | null
  post_closure_returns: Array<{
    id: string
    kind: 'GOOD' | 'UNSPRAYED'
    allocation_id: string
    part_name: string
    factory_name: string
    pieces: number
    return_date: string
    remark: string
    actor_name: string
    created_at: string
  }>
  pending_cancellations: Array<{
    id: string
    allocation_id: string
    part_name: string
    factory_name: string
    cancelled_pieces: number
    remark: string
    actor_employee_id: string
    actor_name: string
    created_at: string
  }>
}

export interface P4Rework {
  id: string
  unsprayed_return_id: string
  source_id: string
  completed_pieces: number
  allocated_pieces: number
  remaining_allocatable_pieces: number
  completion_date: string
  external_order_ids: string[]
}

export interface P4ExternalOrder {
  unit_price?: string | null
  planned_amount?: string | null
  id: string
  order_number: string
  source_id: string
  rework_id: string
  original_return_id: string
  factory_id: string
  factory_name: string
  craft_id: string
  craft_name: string
  allocated_pieces: number
  handoff_pieces: number
  returned_good_pieces: number
  remaining_return_pieces: number
  status: 'PENDING_HANDOFF' | 'PROCESSING' | 'COMPLETED' | 'CLOSED'
  version: number
  etag: string
  handoff: { id: string; handoff_pieces: number; handoff_date: string } | null
  good_returns: Array<{ id: string; return_number: string; good_pieces: number; zone_id: string; return_date: string; post_closure: boolean; remark: string }>
  closure: { id: string; remark: string; quantity_snapshot: Record<string, unknown>; created_at: string } | null
  allocation_context?: {
    rework_completed_pieces: number
    other_allocated_pieces: number
    max_allocatable_pieces: number
    remaining_allocatable_pieces: number
    can_adjust: boolean
    blockers: string[]
    part_name?: string
    issue_number?: string
  }
  allocation_history?: Array<{
    id: string
    before_pieces: number
    after_pieces: number
    actor_employee_id: string
    actor_name: string
    created_at: string
  }>
}

export interface P4SemiStock {
  production_task_id: string
  product_line_id: string
  bom_line_id: string
  component_identity: string
  part_name: string
  unit: string
  available_pieces: string
  pieces_per_bar?: number
  raw_bar_length_m?: string
  whole_bar_required: false
  batch_selection: false
  zones: Array<{ zone_id: string; zone_name: string; available_pieces: string }>
}

export interface P4Options extends OutsourcingOptions {
  original_orders: OutsourcingOrder[]
}
