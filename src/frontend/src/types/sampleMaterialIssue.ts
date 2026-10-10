export type SampleMaterialIssueStatus = 'NOT_STARTED' | 'PENDING_CONFIRMATION' | 'ISSUED'

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
  arrivedQuantity: string
  availableQuantity: string
  issuedQuantity: string | null
  shortageQuantity: string
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
  lines?: SampleMaterialIssueLine[]
}
