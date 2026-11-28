export type TrackingStage =
  | 'steel_purchase' | 'metal_issue' | 'metal_completion'
  | 'coating_dispatch' | 'coating_receipt'
  | 'fabric_purchase' | 'fabric_arrival' | 'sewn_receipt'
  | 'plastic_purchase' | 'plastic_receipt' | 'hardware_purchase' | 'hardware_receipt'
  | 'packaging_purchase' | 'packaging_receipt'
  | 'assembly_first' | 'assembly_completion' | 'finished_receipt'

export interface TrackingMilestone {
  date: string | null
  batch_count: number
  note: string
}

export interface MaterialTrackingRow {
  id: string
  task_number: string
  product_name: string
  order_quantity: string
  order_unit: string
  color: string
  stages: Record<TrackingStage, TrackingMilestone>
  coating_factories: string[]
  assembly_lines: number[]
  finished_quantities: { unit: string; quantity: string }[]
  bom: { id: string; file_name: string } | null
  has_packaging_requirements: boolean
}

export interface MaterialTrackingList {
  data: MaterialTrackingRow[]
  meta: { page: number; page_size: number; total: number; total_pages: number }
}

export interface MaterialTrackingDetail {
  batches: {
    kind: TrackingStage
    date: string | null
    number: string
    party: string
    material: string
    quantity: string | null
    unit: string
    note: string
  }[]
  fabrics: { material: string; required: string; unit: string; arrived_on: string | null; total_received: string }[]
  packaging_requirements: string
}
