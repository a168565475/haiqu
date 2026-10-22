import type { SampleMaterialLine } from './sampleMaterial'

export interface SampleWarehouseLine extends SampleMaterialLine {
  unitLabel: string
  supplyQuantity: string
  inventoryAllocations?: SampleInventoryAllocation[]
}
export interface SampleInventoryCandidate {
  balanceId: string; stockMode: 'LEGACY' | 'PUBLIC_V2'; materialNumber: string
  warehouseName: string; zoneName: string; unitLabel: string; availableQuantity: string
  rawBarLengthM: string | null; meterQuantity: string | null
}
export interface SampleInventoryAllocation extends SampleInventoryCandidate { quantity: string }
export interface SampleWarehouseInventory { lines: { lineKey: string; candidates: SampleInventoryCandidate[] }[] }
export interface SampleWarehouseDraft { lines: SampleWarehouseLine[]; notes: string }
export type SampleWarehouseLoadResult =
  | { available: true; draft: SampleWarehouseDraft; etag: string; canEdit: boolean; status: import('./sample').SampleStatus; statusLabel: string; submittedAt: string; reviewedAt: string | null }
  | { available: false; reason: string }
export type SampleSupplyResult =
  | { valid: true; gap: string; result: 'full' | 'partial' | 'none' }
  | { valid: false; gap: null; result: 'pending' | 'invalid'; message: string }
