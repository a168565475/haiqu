import type { SampleMaterialDraft, SampleMaterialUnit } from '@/types/sampleMaterial'
import { sampleMaterialCategories } from '@/types/sampleMaterial'
import { AxiosError } from 'axios'
import type { SampleMaterialField, SampleMaterialLine, SampleMaterialReferences } from '@/types/sampleMaterial'

export function materialFieldOptions(references: SampleMaterialReferences | null, line: SampleMaterialLine, field: SampleMaterialField) {
  if (!references) return []
  if (field === 'color') return references.colors || []
  if (line.category === 'accessory') {
    if (field === 'name') return references.accessories
    const product = references.accessories.find(item => item.label === line.name)
    if (field === 'specification') return product?.specifications || []
    return references.accessory[field] || []
  }
  if (line.category === 'tube' || line.category === 'fabric') return references[line.category][field] || []
  return references[line.category]?.[field] || []
}

export function materialFieldSelectionOnly(line: SampleMaterialLine, field: SampleMaterialField) {
  return field === 'color' || field === 'material' || line.category === 'tube' || (line.category === 'accessory' && field === 'specification') || (line.category === 'fabric' && field === 'specification')
}

export function sampleMaterialError(error: unknown): string {
  if (!(error instanceof AxiosError)) return error instanceof Error ? error.message : '保存失败，请重试。'
  if (error.response?.status === 412 || error.response?.status === 428) {
    const message = (error.response.data as { error?: { message?: string } })?.error?.message
    return `${message || '数据版本已变化。'} 请保留填写内容，重新读取对应品名或单据后核对。`
  }
  if (error.response?.status === 403) return '当前账号没有此操作权限。'
  const data = error.response?.data as { error?: { message?: string }; detail?: string } | undefined
  return data?.error?.message || data?.detail || '请求失败，填写内容仍保留，请检查网络后重试。'
}

export function validateSampleMaterials(draft: SampleMaterialDraft, units: SampleMaterialUnit[]): string {
  if (!draft.lines.length) return '请至少填写一项材料需求。'
  if (draft.notes.length > 2000) return '需求备注不能超过 2000 字。'
  for (const [index, line] of draft.lines.entries()) {
    const prefix = `第 ${index + 1} 项材料：`
    if (line.name.length > 300 || line.specification.length > 500 || line.material.length > 500 || line.color.length > 500 || line.notes.length > 2000) return `${prefix}填写内容超出字段长度限制。`
    if (!sampleMaterialCategories.some(category => category.key === line.category)) return `${prefix}请选择材料分区。`
    if (!line.name.trim() || !line.specification.trim()) return `${prefix}请填写材料名称和规格。`
    const catalog = !!line.material_catalog_id
    if (!catalog && !line.rawMaterialId) return `${prefix}请选择原材料。`
    if (catalog && !line.material_selection && !line.material_selection_snapshot) return `${prefix}缺少所选材料内容，请重新选料。`
    // 后端保存总米数管材时清空单位编号，固定使用“米”和 4 位小数。
    const savedMeterPipe = line.category === 'tube' && line.pipeInputMode === 'TOTAL_METERS' && line.unitLabel === '米' && !line.unitId
    const catalogPipe = catalog && line.category === 'tube'
    if (catalogPipe) {
      const materialUnit = line.material_selection ? line.unitLabel : line.material_selection_snapshot?.unit_name
      if (materialUnit !== '根') return `${prefix}请选择根制原管；本次样品需求按米填写。`
      if (!line.material_selection && line.material_selection_snapshot && line.pipeInputMode !== 'TOTAL_METERS') return `${prefix}原管材数量口径需核实，不能自动把旧数量当作米数。`
    }
    const unit = catalogPipe || savedMeterPipe ? { label: '米', decimalPlaces: 4 } : catalog && line.unitLabel ? { label: line.unitLabel, decimalPlaces: 4 } : units.find(item => item.id === line.unitId)
    if (!unit) return `${prefix}请选择有效单位。`
    const value = line.quantity.trim()
    if (!/^\d{1,14}(\.\d{1,4})?$/.test(value)) return `${prefix}数量最多 14 位整数、4 位小数。`
    if (!/^\d+(\.\d+)?$/.test(value) || !Number.isFinite(Number(value)) || Number(value) <= 0) return `${prefix}需求数量必须大于 0。`
    if (!catalog && line.category === 'tube' && unit.label !== '米') return `${prefix}管材需求单位必须是米。`
    if (unit.decimalPlaces != null && (value.split('.')[1]?.length || 0) > unit.decimalPlaces) return `${prefix}${unit.label}最多保留 ${unit.decimalPlaces} 位小数。`
  }
  return ''
}
