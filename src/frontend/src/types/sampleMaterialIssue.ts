export type SampleMaterialIssueStatus = 'NOT_STARTED' | 'PENDING_CONFIRMATION' | 'ISSUED'

export interface SampleMaterialIssuePipeBatch {
  balanceId: string
  warehouseName: string
  zoneName: string
  rawBarLengthM: string
  barCount: number
  meterQuantity: string
}

export interface SampleMaterialIssueLine {
  id: string | null
  lineKey: string
  category: string
  name: string
  specification: string
  material: string
  color: string
  unitLabel: string
  requestedQuantity: string
  warehouseQuantity: string
  procurementQuantity: string
  arrivedQuantity: string
  availableQuantity: string
  issuedQuantity: string | null
  shortageQuantity: string
  barCount: number | null
  pipeBatches: SampleMaterialIssuePipeBatch[]
}

export interface SampleMaterialIssueResult {
  available: boolean
  reason?: string
  status?: SampleMaterialIssueStatus
  statusLabel?: string
  issueId?: string | null
  etag?: string
  canInitiate?: boolean
  canConfirm?: boolean
  initiatedAt?: string | null
  confirmedAt?: string | null
  blockers?: string[]
  lines?: SampleMaterialIssueLine[]
}
