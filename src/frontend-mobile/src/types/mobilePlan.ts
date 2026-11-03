export interface MobileProgress {
  status: string
  percentage: number | null
  reported_quantity?: string | null
  required_quantity?: string | null
}
export interface MobileCraft {
  id: string; name: string; can_report: boolean; can_open_report: boolean; reason: string
  progress: MobileProgress | null
}
export interface MobilePlan {
  key: string
  schedule_product_id: string; schedule_id: string; schedule_number: string
  production_task_id: string; product_line_id: string; task_number: string
  product: {
    name: string; number: string; specification: string; color: string; material: string
    quantity: string; order_quantity: string; unit: string; image_url: string | null
  }
  plan_category: string; plan_category_label: string; workshop: { id: string; name: string }
  plan_date: string | null; task_status: string; task_status_display: string
  can_issue: boolean; issue_reason: string; can_report: boolean; can_open_report: boolean; report_reason: string
  can_view_issues: boolean; can_view_reports: boolean
  can_receive_finished: boolean; finished_receipt_reason: string
  can_receive_semi: boolean; semi_receipt_reason: string
  progress: MobileProgress | null; reporting_crafts: MobileCraft[]
}
export interface MobilePlanList {
  data: MobilePlan[]
  meta: { page: number; page_size: number; total: number; total_pages: number }
}

export interface MobileWorkshopOption {
  id: string
  name: string
}

export interface MobileContext {
  workshop_filter: {
    enabled: boolean
    options: MobileWorkshopOption[]
    default_id: string | null
  }
}
