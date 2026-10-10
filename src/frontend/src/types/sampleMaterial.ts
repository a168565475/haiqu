// V3 材料需求使用独立录入模型；不转换成旧版报工或 BOM 明细。
export const sampleMaterialCategories = [
  { key: 'tube', label: '管材类' }, { key: 'hardware', label: '五金件' },
  { key: 'plastic', label: '塑料件类' }, { key: 'accessory', label: '辅料类' },
  { key: 'fabric', label: '面料类' }, { key: 'packaging', label: '包材类' },
] as const
export type SampleMaterialCategory = typeof sampleMaterialCategories[number]['key']
export interface SampleMaterialLine {
  key: string
  category: SampleMaterialCategory
  name: string
  specification: string
  material: string
  color: string
  quantity: string
  unitId: string
  /** 新口径管材固定按总米数填写；可选字段兼容旧样品草稿。 */
  unitLabel?: string
  pipeInputMode?: 'TOTAL_METERS'
  notes: string
  rawMaterialId?: string
  cuttingLengthMm?: string
  piecesPerBar?: string
}
export interface SampleMaterialDraft {
  lines: SampleMaterialLine[]
  notes: string
}
export interface SampleMaterialUnit { id: string; label: string; decimalPlaces?: number }
export type SampleMaterialField = 'name' | 'specification' | 'material' | 'color'
export interface SampleMaterialOption { label: string; pinyin_search?: string }
export interface SampleMaterialReferences {
  colors?: SampleMaterialOption[]
  tubeDiameters?: SampleMaterialOption[]
  tubeThicknesses?: SampleMaterialOption[]
  catalogNames?: Partial<Record<SampleMaterialCategory, string[]>>
  hardware?: Partial<Record<SampleMaterialField, SampleMaterialOption[]>>
  plastic?: Partial<Record<SampleMaterialField, SampleMaterialOption[]>>
  packaging?: Partial<Record<SampleMaterialField, SampleMaterialOption[]>>
  tube: Partial<Record<SampleMaterialField, SampleMaterialOption[]>>
  fabric: Partial<Record<SampleMaterialField, SampleMaterialOption[]>>
  accessory: Partial<Record<SampleMaterialField, SampleMaterialOption[]>>
  accessories: Array<SampleMaterialOption & { id: string; unitLabel: string; specifications: SampleMaterialOption[]; colors: SampleMaterialOption[] }>
}
export interface SampleMaterialCandidate {
  id: string; number: string; name: string; specification: string; material: string; color: string; unitId: string; unitLabel: string
}
export interface SampleMaterialProgress {
  label: string; status: string
  lines: Array<SampleMaterialLine & {
    unitLabel: string; supplyQuantity: string; arrivedQuantity: string; remainingQuantity: string
    availableQuantity?: string; issuedQuantity?: string | null; shortageQuantity?: string
  }>
}
export type SampleMaterialLoadResult =
  | { available: true; noMaterials?: boolean; progress?: SampleMaterialProgress; procurementRequest?: { id: string; submittedAt: string } | null; draft: SampleMaterialDraft; etag: string; canEdit: boolean; status: import('./sample').SampleStatus; statusLabel: string; submittedAt: string | null }
  | { available: false; reason: string }
