import { describe, expect, it } from 'vitest'
import { applySampleSelection, sampleSelectionLine } from './sampleCatalogSelection'
import type { SampleMaterialLine } from '@/types/sampleMaterial'

const row = (): SampleMaterialLine => ({ key: 'one', category: 'hardware', name: '', specification: '', material: '', color: '', quantity: '12', unitId: '', notes: '' })
describe('样品独立材料选择', () => {
  it('不需要BOM，保留所选属性与自选数量单位', () => {
    const input = row(), selected = sampleSelectionLine(input)
    Object.assign(selected, { material_catalog_id: 'catalog', part_name: '五金', specification: 'M8', unit: '公斤', material: '铁',
      material_selection: { catalog_version: 'v1', scope: 'BASE', processing_state: 'RAW', attributes: { specification: 'M8' }, unit_name: '公斤' } })
    const result = applySampleSelection(input, selected)
    expect(result.material_selection?.unit_name).toBe('公斤')
    expect(result.quantity).toBe('12')
    expect(result.rawMaterialId).toBeUndefined()
    expect(input.material_catalog_id).toBeUndefined()
  })
  it('更换单位清空旧数量，不能直接挪用数值', () => {
    const input = { ...row(), unitId: 'root', unitLabel: '根' }, selected = sampleSelectionLine(input)
    Object.assign(selected, { unit: '米', material_selection: { unit_id: 'meter', attributes: {} } })
    expect(applySampleSelection(input, selected).quantity).toBe('')
  })
  it('同名颜色更换色卡色号会保留新选择，不误判为原快照回读', () => {
    const input: SampleMaterialLine = { ...row(), category: 'fabric', material_catalog_id: 'catalog', name: '布料',
      unitId: 'meter', unitLabel: '米', color: '米白',
      material_selection_snapshot: { schema_version: 1, catalog_id: 'catalog', catalog_version: 'old', category_key: 'FABRIC',
        template_key: 'FABRIC', name: '布料', scope: 'BASE', processing_state: 'RAW', processing_stage: 'RAW', completed_craft: null,
        semi_kind: null, attributes: { color: '米白' }, unit_id: 'meter', unit_name: '米', display_name: '布料米白',
        product_color_id: 'color-a', color_card: 'A色卡', color_code: '101', color_name: '米白' } }
    const before = JSON.stringify(input)
    const selected = sampleSelectionLine(input)
    selected.material_selection = { catalog_version: 'current', scope: 'BASE', processing_state: 'RAW', unit_id: 'meter',
      attributes: { color: '米白' }, product_color_id: 'color-b', color_card: 'B色卡', color_code: '102', color_name: '米白' }
    const result = applySampleSelection(input, selected)
    expect(result.material_selection).toMatchObject({ product_color_id: 'color-b', color_card: 'B色卡', color_code: '102', color_name: '米白' })
    expect(result.quantity).toBe('12')
    expect(result.material_selection_snapshot?.product_color_id).toBe('color-a')
    expect(JSON.stringify(input)).toBe(before)
  })
  it('回读同一保存内容不生成待保存选择，目录版本变化也不改历史快照', () => {
    const input: SampleMaterialLine = { ...row(), category: 'tube', material_catalog_id: 'catalog', name: '旧品名', unitId: 'kg', unitLabel: '公斤',
      material_selection_snapshot: { schema_version: 1, catalog_id: 'catalog', catalog_version: 'old', category_key: 'TUBE',
        template_key: 'TUBE', name: '旧品名', scope: 'BASE', processing_state: 'RAW', processing_stage: 'RAW', completed_craft: null,
        semi_kind: null, attributes: { material: '铁', section_size: '25' }, unit_id: 'kg', unit_name: '公斤', display_name: '旧品名25' } }
    const selected = sampleSelectionLine(input)
    selected.material_selection = { catalog_version: 'current', scope: 'BASE', processing_state: 'RAW',
      attributes: { section_size: '25', material: '铁' }, unit_id: 'kg' }
    expect(applySampleSelection(input, selected)).toEqual(input)
    selected.material_selection.attributes.section_size = '32'
    expect(applySampleSelection(input, selected).material_selection!.attributes.section_size).toBe('32')
  })
})
