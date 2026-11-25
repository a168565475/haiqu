export type WageSchemeStatus = 'DRAFT' | 'PENDING_APPROVAL' | 'APPROVED' | 'RETURNED' | 'SUPERSEDED'
type WageCountingMode = 'ORDER' | 'PIECE' | 'SET'

export interface WageSchemeSummary {
  id: string
  number: string
  status: WageSchemeStatus
  status_display: string
  can_edit: boolean
  can_change: boolean
  is_change: boolean
}

export interface WageTarget {
  schedule_product_id: string
  product_line_id: string
  task_number: string
  schedule_date: string
  product_name: string
  product_number: string
  product_specification: string
  product_color: string
  workshop_id: string
  workshop_name: string
  craft_id: string
  craft_name: string
  scheme: WageSchemeSummary | null
}

export interface WageTargetResponse {
  data: WageTarget[]
  meta?: { page: number; total_pages: number }
}

export interface WageBomOption {
  id: string
  identity: string
  name: string
  required_quantity: string | null
  problem: string
}

export interface WageOperation {
  id: string
  name: string
  product_name: string
  unit: string
}

export interface WageFormOptions {
  target: WageTarget
  order_quantity: string
  bom_options: WageBomOption[] | null
  requires_product_name: boolean
  operations: WageOperation[]
}

export interface WageLineInput {
  work_item_id?: string
  counting_mode?: WageCountingMode
  craft_id: string
  operation_id: string
  bom_line_id: string | null
  display_name: string
  declared_price: string
  previous_price: string | null
  revised_price: string | null
  production_description: string
  status: 'ACTIVE' | 'VOID'
  note: string
}

export interface WageSchemeInput {
  schedule_product_id: string
  product_line_id: string
  workshop_id: string
  craft_ids: string[]
  operation_product_name?: string
  remark: string
  lines: WageLineInput[]
}

type SavedWageLine = Omit<WageLineInput, 'bom_line_id' | 'work_item_id' | 'counting_mode'> & {
  work_item_id: string
  counting_mode: WageCountingMode
  operation_name: string
  bom_component_identity: string | null
}

export interface SavedWageScheme {
  id: string
  scheme_number: string
  status: WageSchemeStatus
  status_display: string
  can_create_change: boolean
  parent_scheme: { id: string } | null
  operation_product_name: string
  remark: string
  lines: SavedWageLine[]
}

export type WageSubmission = Pick<SavedWageScheme, 'id' | 'scheme_number' | 'status' | 'status_display'> & {
  change_target: WageTarget | null
  production_task: { task_number: string }
  product: { name: string }
  workshop: { name: string }
  scope_craft: { name: string }
}

export interface VersionedWageScheme {
  data: SavedWageScheme
  etag: string
}
