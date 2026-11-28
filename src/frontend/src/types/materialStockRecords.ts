import type { WarehouseMaterialSection } from './inventory'

export type MaterialStockRecordSection = WarehouseMaterialSection | 'OTHER'
export type MaterialStockRecordDirection = 'IN' | 'OUT'

export interface MaterialStockRecord {
  id: string
  source_type: string
  origin_id: string
  business_date: string
  task_number: string
  voucher_number: string
  movement_label: string
  origin_section_display: string
  item_name: string
  specification: string
  color: string
  actual_quantity: string
  stock_unit: string
  warehouse_name: string
  zone_name: string
  actor_name: string
  recipient_name: string
  counterparty: string
  note: string
}

export interface MaterialStockRecordPage {
  data: MaterialStockRecord[]
  total: number
  show_other: boolean
}
