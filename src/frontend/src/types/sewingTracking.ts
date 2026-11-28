import type { DeliveryReminder, ReminderFilters } from './deliveryReminders'

export interface SewingTrackingQuantity {
  unit: string
  quantity: string | null
}

export interface SewingTrackingUnitPrice {
  amount: string
  unit: string
}

export interface SewingTrackingRow {
  id: string
  task_number: string
  process: 'SEWING' | 'SCREEN_PRINTING'
  product_name: string
  part_name: string
  product_image_url: string
  color: string
  factory_name: string
  factory_phone: string
  unit_prices: SewingTrackingUnitPrice[]
  planned_dispatch_dates: string[]
  dispatch_dates: string[]
  expected_return_dates: string[]
  last_receipt_date: string | null
  sent: SewingTrackingQuantity[]
  received: SewingTrackingQuantity[]
  transferred: SewingTrackingQuantity[]
  factory_remaining: SewingTrackingQuantity[]
  not_sent: SewingTrackingQuantity[]
  reminder: DeliveryReminder | null
}

export interface SewingTrackingQuery extends ReminderFilters {
  task_number: string
  page: number
  page_size: number
}

export interface SewingTrackingPage {
  data: SewingTrackingRow[]
  meta: { total: number; page: number; page_size: number; total_pages: number }
}
