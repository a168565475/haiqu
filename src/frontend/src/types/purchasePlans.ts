import type { DeliveryReminder, ReminderFilters } from './deliveryReminders'

export type PurchasePlanCategory = 'TUBE' | 'FABRIC'

export interface PurchasePlanAmount {
  quantity: string
  unit: string
}

export interface PurchasePlanRow {
  id: string
  task_id: string
  task_number: string
  product_name: string
  task_quantity: number
  bom_number: string
  name: string
  material: string
  specification: string
  thickness: string
  cutting_length: string
  raw_length: string
  hardness: string
  coating: string
  fabric_width: string
  fabric_color: string
  required: PurchasePlanAmount | null
  ordered: PurchasePlanAmount[]
  received: PurchasePlanAmount[]
  progress: string
  note: string
  reminder: DeliveryReminder | null
}

export interface PurchasePlanMovement {
  id: string
  number: string
  date: string | null
  amount: PurchasePlanAmount | null
  equivalents: PurchasePlanAmount[]
  status: string
  days: number | null
}

export interface PurchasePlanBatch {
  id: string
  order_number: string
  batch_number: number | null
  supplier: string
  sheet_numbers: string[]
  ordered_on: string | null
  expected_on: string | null
  complete_on: string | null
  ordered: PurchasePlanAmount | null
  ordered_equivalents: PurchasePlanAmount[]
  received: PurchasePlanAmount | null
  remaining: PurchasePlanAmount | null
  progress: string
  unit_price: PurchasePlanAmount | null
  currency: string
  shared: boolean
  products: string[]
  bom_numbers: string[]
  arrivals: PurchasePlanMovement[]
  returns: PurchasePlanMovement[]
  reminder: DeliveryReminder | null
}

export interface PurchasePlanDetail extends PurchasePlanRow {
  batches: PurchasePlanBatch[]
  source_versions: { bom_number: string; required: PurchasePlanAmount | null }[]
  purchase_reminders: DeliveryReminder[]
}

export interface PurchasePlanQuery extends ReminderFilters {
  category: PurchasePlanCategory
  task_number: string
  q: string
  page: number
  page_size: number
}

export interface PurchasePlanPage {
  data: PurchasePlanRow[]
  total: number
}
