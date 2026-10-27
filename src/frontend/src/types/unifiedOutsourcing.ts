import type { OutsourcingOptions, OutsourcingOrder, OutsourcingOrderStatus } from './outsourcing'

export type UnifiedOutsourcingSourceKind = 'RAW' | 'METAL' | 'REWORK' | 'UNSELECTED' | 'RAW_PIPE' | 'PUBLIC_SEMI' | 'TUBE_METAL' | 'PUBLIC_CUTTING' | 'SEWING'
export type UnifiedOutsourcingSourceGroup = 'RAW' | 'TUBE_PUBLIC' | 'TUBE_METAL' | 'OLD_METAL' | 'REWORK' | 'UNSELECTED' | 'CUTTING_PUBLIC' | 'SEWING'
export type UnifiedOutsourcingStatus = OutsourcingOrderStatus | 'PENDING_HANDOFF'

export interface OutsourcingQuantitySummary {
  quantity: string
  unit: string
}

export interface UnifiedOutsourcingOrder extends Omit<OutsourcingOrder, 'status' | 'delivery_date' | 'planned_amount'> {
  warehouse_actions?: ('dispatch' | 'return' | 'raw')[]
  record_type: 'ORIGINAL' | 'REWORK' | 'TUBE'
  row_key: string
  source_kind: UnifiedOutsourcingSourceKind
  source_label: string
  status: UnifiedOutsourcingStatus
  delivery_date: string | null
  planned_amount: string | null
  dispatched_quantities: OutsourcingQuantitySummary[]
  returned_quantities: OutsourcingQuantitySummary[]
  detail_access: 'REGULAR' | 'METAL' | 'TUBE'
  receipt_state?: 'NOT_RECEIVED' | 'RECORDED' | 'MISSING'
  shortage_quantities?: OutsourcingQuantitySummary[]
  source_issue_line_id?: string | null
}

export interface UnifiedOutsourcingOptions {
  crafts: OutsourcingOptions['crafts']
  factories: OutsourcingOptions['factories']
  statuses: Array<{ value: UnifiedOutsourcingStatus; label: string }>
  source_groups?: Array<{ value: UnifiedOutsourcingSourceGroup; label: string }>
}
