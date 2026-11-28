import type { DeliveryReminder, ReminderFilters } from './deliveryReminders'

export type PowderCoatingDirection = 'dispatch' | 'receipt'

export interface PowderCoatingRow {
  id: string
  task_number: string
  factory_name: string
  part_name: string
  specification: string
  spray_color: string
  order_id: string
  business_date: string
  quantity: string
  unit: string
  source: 'TUBE' | 'REGULAR' | 'METAL' | 'REWORK'
  voucher_number: string
  expected_return_date: string | null
  reminder: Pick<DeliveryReminder, 'status' | 'label'> | null
}

export interface PowderCoatingQuery extends ReminderFilters {
  task_number: string
  direction: PowderCoatingDirection
  page: number
  page_size: number
}
