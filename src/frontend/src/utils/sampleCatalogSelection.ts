import type { BomLineInput } from '@/types/bom'
import type { SampleMaterialCategory, SampleMaterialLine } from '@/types/sampleMaterial'
import { blankLine } from '@/views/boms/bomEditorHelpers'

export const sampleCatalogTitles: Record<SampleMaterialCategory, string> = {
  tube: '管材类', hardware: '五金件', plastic: '塑料件类', accessory: '辅料类', fabric: '面料类', packaging: '包材类',
}

export function sampleSelectionLine(row: SampleMaterialLine): BomLineInput {
  return { ...blankLine(), material_catalog_id: row.material_catalog_id,
    material_selection: row.material_selection ? JSON.parse(JSON.stringify(row.material_selection)) : undefined,
    material_selection_snapshot: row.material_selection_snapshot ? JSON.parse(JSON.stringify(row.material_selection_snapshot)) : undefined,
    part_name: row.name, specification: row.specification, material: row.material, unit: row.unitLabel || '' }
}

export function applySampleSelection(row: SampleMaterialLine, selected: BomLineInput): SampleMaterialLine {
  const selection = selected.material_selection
  const snapshot = selected.material_selection_snapshot
  const saved = row.material_selection_snapshot
  // 面板回读会从快照补齐选择输入；相同内容仍沿原快照，不视作用户重新选料。
  if (selection && saved && !row.material_selection && selected.material_catalog_id === row.material_catalog_id
    && selection.scope === saved.scope && selection.processing_state === saved.processing_state
    && (selection.semi_kind || null) === (saved.semi_kind || null)
    && (selection.completed_craft?.id || null) === (saved.completed_craft?.id || null)
    && (selection.completed_craft?.craft_type || null) === (saved.completed_craft?.craft_type || null)
    && (selection.completed_craft?.code || null) === (saved.completed_craft?.code || null)
    && (selection.unit_id === saved.unit_id || (!selection.unit_id && selection.unit_name === saved.unit_name))
    && (['product_color_id', 'color_card', 'color_code', 'color_name'] as const)
      .every(key => (selection[key] || '') === (saved[key] || ''))
    && Object.keys(selection.attributes).length === Object.keys(saved.attributes).length
    && Object.entries(selection.attributes).every(([key, value]) => saved.attributes[key] === value)) return { ...row }
  const attrs = selection?.attributes || snapshot?.attributes || {}
  const unitId = selection ? selection.unit_id || '' : snapshot?.unit_id || ''
  const unitName = selection?.unit_name || selected.unit || snapshot?.unit_name || ''
  const changedUnit = row.category !== 'tube' && !!(row.unitLabel || row.unitId) && (unitId !== row.unitId || unitName !== row.unitLabel)
  const retiredPipeQuantity = row.category === 'tube' && !!saved && !row.material_selection && row.pipeInputMode !== 'TOTAL_METERS'
  return { ...row, material_catalog_id: selected.material_catalog_id || undefined,
    material_selection: selection ? JSON.parse(JSON.stringify(selection)) : undefined,
    material_selection_snapshot: snapshot ? JSON.parse(JSON.stringify(snapshot)) : undefined,
    name: selected.part_name, specification: selected.specification, material: selected.material,
    color: attrs.color || '', unitId, unitLabel: unitName, quantity: changedUnit || retiredPipeQuantity ? '' : row.quantity,
    rawMaterialId: undefined, pipeInputMode: row.category === 'tube' ? 'TOTAL_METERS' : undefined, cuttingLengthMm: undefined, piecesPerBar: undefined }
}

