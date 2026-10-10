import type { PageMeta } from './referenceData'

export type ProductionTaskStatus = 'DRAFT' | 'PENDING_VALIDATION' | 'READY' | 'IN_PRODUCTION' | 'PAUSED' | 'COMPLETED' | 'CANCELLED'
export type ProductionOrderSource = 'NEW' | 'REPEAT'
export type ProductionDeliveryMethod = 'SINGLE' | 'SPLIT'
export type ProductionTaskBomSyncMode = 'SYNC' | 'KEEP'
export type ProductionTaskBomStatus = 'NOT_CREATED' | 'PARTIAL' | 'PENDING_CONFIRMATION' | 'VERIFIED'
export type ProductionTaskPurchaseStatus =
  | 'NOT_STARTED'
  | 'REQUEST_DRAFT'
  | 'REQUEST_SUBMITTED'
  | 'REQUEST_ALLOCATING'
  | 'REQUEST_FULLY_ALLOCATED'
  | 'REQUEST_CANCELLED'
  | 'REQUEST_MIXED'
  | 'ORDER_DRAFT'
  | 'ORDER_SUBMITTED'
  | 'ORDER_PURCHASING'
  | 'ORDER_COMPLETED'

export interface ValueOption<T = string | boolean> { value: T; label: string }
export interface EmployeeOption { id: string; employee_code: string; display_name: string }
export interface CustomerOption { id: string; account_code: string; account_name: string }
export interface CurrencyOption { id: string; code: string; name: string; symbol: string }
export interface UnitOption { id: string; unit_code: string; unit_name: string }
export interface ColorOption { id: string; color_card: string; color_code: string; color_name: string }
export interface ProductOption {
  id: string
  product_number: string
  product_code: string
  item_number: string
  product_name: string
  specification: string
  default_unit_id: string
}
export interface ProductionTaskDetailTemplate { key: string; type: string; category: string }

export interface ProductionTaskOptions {
  order_sources: ValueOption<ProductionOrderSource>[]
  delivery_methods: ValueOption<ProductionDeliveryMethod>[]
  statuses: ValueOption<ProductionTaskStatus>[]
  boolean_options: ValueOption<boolean>[]
  customers: CustomerOption[]
  employees: EmployeeOption[]
  products: ProductOption[]
  currencies: CurrencyOption[]
  units: UnitOption[]
  colors: ColorOption[]
  detail_template: ProductionTaskDetailTemplate[]
}

export type ProductionTaskFilterOptions = Pick<ProductionTaskOptions,
  'order_sources' | 'delivery_methods' | 'statuses' | 'customers' | 'employees' | 'products'>

export interface ProductionTaskDetailInput {
  client_key: string
  template_key: string
  detail_type: string
  category_label: string
  is_selected: boolean
  description: string
}

export interface ProductionTaskDetail extends ProductionTaskDetailInput {
  id: string
  line_number: number
  image_name: string | null
}

export interface ProductionTaskProductInput {
  client_key: string
  product_id: string | null
  product_color_id: string | null
  color_code: string
  customer_product_name?: string
  customer_specification?: string
  customer_color?: string
  quantity: string
  unit_id: string
  currency_id: string
  unit_price: string
  exchange_rate: string
  special_requirements: string
  packaging_method: string
  retained_image_ids: string[]
  details: ProductionTaskDetailInput[]
}

export interface ProductionTaskProductUpdateDraft {
  payload: ProductionTaskProductInput
  productImages: File[]
  detailImages: Record<string, File | null>
}

export interface ProductionDeliveryBatchInput { quantity: string; delivery_date: string; note: string }

export interface ProductionTaskInput {
  bom_sync_mode?: ProductionTaskBomSyncMode
  bom_sync_token?: string
  contract_number_token?: string
  contract_number: string
  order_source: ProductionOrderSource
  order_number: string
  customer_account_id: string
  order_date: string
  delivery_date: string
  salesperson_id: string
  follower_ids: string[]
  currency_id: string
  includes_tax: boolean
  order_tolerance_percent: string
  is_repeat_order: boolean
  preproduction_sample_required: boolean
  delivery_method: ProductionDeliveryMethod
  special_requirements_html: string
  freight_amount: string
  other_fee_amount: string
  products: ProductionTaskProductInput[]
  delivery_batches: ProductionDeliveryBatchInput[]
}

export interface ProductionTaskPatchInput {
  bom_sync_mode?: ProductionTaskBomSyncMode
  bom_sync_token?: string
  delivery_date?: string
  // 仅用于日期修改，可与 delivery_date 同批提交，不能混入其他编辑字段。
  delivery_batch_dates?: Array<{ id: string; delivery_date: string }>
  follower_ids?: string[]
  special_requirements_html?: string
  products?: ProductionTaskProductInput[]
  delivery_batches?: ProductionDeliveryBatchInput[]
}

export interface ProductionTaskProduct {
  id: string
  line_number: number
  product_id: string | null
  source_delivery_batch_line_id: string | null
  source_sales_order_line_id: string | null
  product_number: string
  product_code: string
  item_number: string
  product_name: string
  specification: string
  customer_product_name?: string
  customer_specification?: string
  customer_color?: string
  image_name: string | null
  images: ProductionTaskProductImage[]
  product_color_id: string | null
  color_card: string
  color_name: string
  color_code: string
  quantity: number
  unit_id: string
  unit_code: string
  unit_name: string
  currency_id: string
  currency_code: string
  unit_price: string
  total_amount: string
  exchange_rate: string
  local_unit_price: string
  local_total_amount: string
  special_requirements: string
  packaging_method: string
  details: ProductionTaskDetail[]
}

export interface ProductionTaskProductImage {
  id: string
  name: string
  content_type: string
  size_bytes: number
}

export interface ProductionTask {
  id: string
  task_number: string
  contract_number: string
  order_source: ProductionOrderSource
  order_source_display: string
  order_number: string
  customer_id: string
  customer_code: string
  customer_name: string
  order_date: string
  delivery_date: string
  salesperson: EmployeeOption
  followers: EmployeeOption[]
  currency_id?: string
  currency_code?: string
  includes_tax?: boolean
  order_tolerance_percent?: string
  is_repeat_order?: boolean
  preproduction_sample_required?: boolean
  delivery_method: ProductionDeliveryMethod
  delivery_method_display: string
  special_requirements_html?: string
  freight_amount: string
  other_fee_amount: string
  product_total_amount: string
  total_amount: string
  status: ProductionTaskStatus
  status_display: string
  bom_status?: ProductionTaskBomStatus
  bom_status_display?: string
  purchase_status?: ProductionTaskPurchaseStatus
  purchase_status_display?: string
  status_reason?: string
  total_quantity: string
  batch_total_quantity: string
  quantity_difference: string
  products: ProductionTaskProduct[]
  delivery_batches?: Array<ProductionDeliveryBatchInput & { id: string; line_number: number }>
  created_at: string
  updated_at: string
  submitted_at?: string | null
  sales_order_id?: string | null
  sales_order_delivery_batch_id?: string | null
  sales_order_line_id?: string | null
  source_sales_order_number?: string | null
  source_delivery_batch_number?: string | null
  is_historical_unlinked?: boolean
  planned_start_date?: string | null
  planned_end_date?: string | null
  production_priority?: 'URGENT' | 'HIGH' | 'NORMAL' | 'LOW'
  production_batch_number?: string
  planner?: EmployeeOption | null
  actual_quantity?: string
  actual_good_quantity?: string
  excess_quantity?: string
  run_batches?: Array<{
    id: string
    batch_number: string
    planned_quantity: string
    actual_quantity: string
    good_quantity: string
    status: 'PLANNED' | 'IN_PROGRESS' | 'COMPLETED' | 'CANCELLED'
    status_display: string
    note: string
  }>
  current_boms?: Array<{
    id: string
    product_line_id: string
    bom_number: string
    version_number: number
    status: 'PENDING_CONFIRMATION' | 'VERIFIED'
    status_display: string
    product_code: string
    product_name: string
    color_name: string
    color_code: string
    order_quantity: string
    is_order_quantity_outdated: boolean
    confirmed_by_name: string
    confirmed_at: string | null
  }>
  pmc_confirmation?: {
    actor_employee_id: string | null
    actor_name: string
    confirmed_at: string
  } | null
  audit_timeline?: Array<{
    id: string
    action: string
    action_display: string
    actor_employee_id: string | null
    actor_name: string
    occurred_at: string
    status: string
    reason: string
  }>
}

export interface ProductionOrderFromSalesCommonInput {
  request_key?: string
  planned_start_date?: string | null
  planned_end_date?: string | null
  production_priority: 'URGENT' | 'HIGH' | 'NORMAL' | 'LOW'
  production_batch_number: string
  planner_id: string | null
}

export type ProductionOrderFromSalesInput = ProductionOrderFromSalesCommonInput & (
  | {
      delivery_batch_line_id: string
      quantity: number
      product_color_id?: string | null
      delivery_batch_id?: never
      lines?: never
    }
  | {
      delivery_batch_id: string
      lines: Array<{
        delivery_batch_line_id: string
        product_color_id: string
        quantity: number
        special_requirements?: string
        packaging_method?: string
      }>
      delivery_batch_line_id?: never
      quantity?: never
      product_color_id?: never
    }
)

export interface ProductionTaskPmcDecisionInput {
  decision: 'CONFIRM' | 'RETURN'
  planned_start_date?: string | null
  planned_end_date?: string | null
  production_priority?: 'URGENT' | 'HIGH' | 'NORMAL' | 'LOW'
  production_batch_number?: string
  planner_id?: string | null
  reason?: string
}

export interface ProductionTaskQuery {
  page?: number
  page_size?: number
  search?: string
  status?: ProductionTaskStatus | ''
  order_source?: ProductionOrderSource | ''
  delivery_method?: ProductionDeliveryMethod | ''
  contract_number?: string
  customer_id?: string
  product_id?: string
  salesperson_id?: string
  follower_id?: string
  delivery_from?: string
  delivery_to?: string
  quantity_pending?: boolean
  due_within_days?: number
  ordering?: string
}

export interface ProductionTaskStats {
  all: number
  draft: number
  pending_validation: number
  ready: number
  in_production: number
  completed: number
  paused: number
  cancelled: number
  split_delivery: number
}
export interface PaginatedProductionTasks { data: ProductionTask[]; meta: PageMeta }
export interface VersionedProductionTask { data: ProductionTask; etag: string }
export interface ReservedContractNumber { contract_number: string; token: string }
