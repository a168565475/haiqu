export type OutsourcingMovementDirection = 'dispatch' | 'receipt'
export type OutsourcingMovementProcess = 'SEWING' | 'SCREEN_PRINTING'

export interface OutsourcingMovementRow {
  id: string
  task_number: string
  business_date: string
  process: OutsourcingMovementProcess
  factory_name: string
  item_name: string
  quantity: string
  unit: string
  voucher_number: string
  direct_transfer: boolean
}
