import type { SampleMaterialLine } from './sampleMaterial'

export interface SampleWarehouseLine extends SampleMaterialLine {
  unitLabel: string
  supplyQuantity: string
}
export interface SampleWarehouseDraft { lines: SampleWarehouseLine[]; notes: string }
export type SampleWarehouseLoadResult =
  | { available: true; draft: SampleWarehouseDraft; etag: string; canEdit: boolean; status: import('./sample').SampleStatus; statusLabel: string; submittedAt: string; reviewedAt: string | null }
  | { available: false; reason: string }
export type SampleSupplyResult =
  | { valid: true; gap: string; result: 'full' | 'partial' | 'none' }
  | { valid: false; gap: null; result: 'pending' | 'invalid'; message: string }
