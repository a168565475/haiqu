import type { FinishedGoodsReceipt } from './inventory'
export interface AssemblyPreview {
  schedule_product_id:string; schedule_number:string; production_task_product_id:string; task_number:string; order_number:string
  product_number:string; product_name:string; item_number:string; specification:string; actual_color:string
  unit_id:string; unit_name:string; order_quantity:number; tolerance_percent:string; maximum_receivable:number
  received_total:number; remaining_receivable:number; order_maximum:number; reported_minimum:number
  reporting_basis_ready:boolean; reporting_operations:{work_item_id:string;operation:string;reported_quantity:string}[]
  receipt_date:string; actor_name:string; etag:string
}
export interface AssemblyPayload {
  request_id:string; schedule_product_id:string; location_id:string; receipt_date:string; received_quantity:number
  quantity_per_box:number|null; actual_color:string; remark:string
}
export type FinishedRecord = Omit<FinishedGoodsReceipt,'source_type'> & {
  source_type:'PRODUCTION_ORDER'|'SAMPLE_INVENTORY'|'ASSEMBLY'; receipt_date:string; schedule_number:string; status?: 'PENDING'|'CONFIRMED'
  confirmed_by_name?: string; confirmed_at?: string | null
  etag?: string; can_delete?: boolean
  received_before:number|null; received_after:number|null; maximum_receivable:number|null
}
export interface AssemblyCandidate { id:string; schedule_number:string; task_number:string; product_number:string; product_name:string; specification:string; unit_name:string; order_quantity:number; received_total:number }
export interface FinishedLocation { location_id:string; location_number:string; quantity:number; slots:number|null; unknown_packaging:number }
