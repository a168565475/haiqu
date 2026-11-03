export interface ReportingScope {
  schedule_product_id: string
  plan_category: 'METAL' | 'CUTTING' | 'SEWING' | 'ASSEMBLY'
  workshop_id: string
  craft_id: string
}

export type ReportingRecordScope = Omit<ReportingScope, 'craft_id'> & { craft_id?: string }

export interface ReportingOption {
  id: string
  name: string
  workshop_id?: string
  plan_category?: string | null
}

export interface ReportingProduct {
  id: string
  product_line_id: string
  production_task_id: string
  task_number: string
  order_number: string
  product_name: string
  product_number: string
  product_code?: string
  product_specification: string
  product_color: string
  planned_quantity: string
  order_quantity: string
  unit_name: string
}

export interface ReportingContext {
  schedule_product: ReportingProduct | null
  workshops: ReportingOption[]
  crafts: ReportingOption[]
  employees: ReportingOption[]
}

export interface ReportingSchemeLine {
  id: string
  work_item_id: string
  display_name: string
  operation_name: string
  craft_name: string
  production_description: string
  unit_name: string
  required_quantity: string | null
  cumulative_quantity: string
  declared_price: string
  status: 'ACTIVE' | 'VOID'
}

export interface ReportingScheme {
  id: string
  scheme_number: string
  status: string
  version: number
  revision: number
  product_line_id: string
  workshop: ReportingOption
  scope_craft: ReportingOption
  lines: ReportingSchemeLine[]
}

export interface ReportEntry {
  key: number
  scheme_line_id: string
  workshop_employee_id: string
  production_line: number | null
  quantity: string
}

export interface ReportBusinessPayload {
  production_date: string
  schedule_product_id: string
  scheme_id: string
  scheme_revision: number
  confirm_plan_completion: boolean
  lines: Array<Omit<ReportEntry, 'key'>>
}

export interface CreateReportPayload extends ReportBusinessPayload {
  client_request_id: string
}

export interface WorkReportLine {
  id: string
  line_number: number
  scheme_line_id: string
  work_item_id: string
  workshop_employee_id: string
  employee_name: string
  production_line: number | null
  display_name: string
  craft_name: string
  operation_name: string
  unit_name: string
  quantity: string
  required_quantity: string | null
  cumulative_quantity: string | null
  unit_price: string
  amount: string
}

export interface WorkReport {
  id: string
  report_number: string
  production_date: string
  production_task: { id: string; task_number: string; order_number: string }
  product: { name: string; number: string }
  schedule_product_id: string
  workshop: ReportingOption
  scope_craft: ReportingOption
  scheme_version: number
  recorder: string
  total_amount: string
  completed_plan: boolean
  updated_by: string
  lines: WorkReportLine[]
  created_at: string
  updated_at: string
}

export interface ReportPage {
  data: WorkReport[]
  meta: { page: number; page_size: number; total: number; total_pages: number }
}
