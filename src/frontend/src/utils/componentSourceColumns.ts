import type { ComponentSourceMaterial } from '@/types/processingMaterial'
import type { MaterialSelectionSnapshot } from '@/types/materialCatalog'

export type ComponentSourceField = keyof Pick<ComponentSourceMaterial, 'name' | 'material' | 'color' | 'fabric_spec'>

export const componentSourceColumns: { key: string; label: string; width: number; sourceField: ComponentSourceField }[] = [
  { key: 'source_name', label: '来源布料', width: 150, sourceField: 'name' },
  { key: 'source_material', label: '材质', width: 130, sourceField: 'material' },
  { key: 'source_color', label: '颜色', width: 120, sourceField: 'color' },
  { key: 'source_fabric_spec', label: '面料规格', width: 150, sourceField: 'fabric_spec' },
]

const materialSpecificationKeys = ['specification', 'size', 'section_size', 'fabric_spec', 'model', 'width', 'diameter', 'length', 'thickness', 'thread'] as const

export function materialSpecificationValue(material: {
  specification?: string | null
  material_selection_snapshot?: Pick<MaterialSelectionSnapshot, 'attributes'> | Record<string, never> | null
}): string {
  const attributes = material.material_selection_snapshot?.attributes
  const values = materialSpecificationKeys
    .map(key => attributes?.[key]?.trim())
    .filter((value): value is string => Boolean(value))
    .filter((value, index, all) => all.indexOf(value) === index)
  if (values.length) return values.join(' / ')
  return material.specification?.trim() || '—'
}

export function plannedMaterialSpecification(material: {
  specification?: string | null
  material_selection_snapshot?: Pick<MaterialSelectionSnapshot, 'attributes'> | Record<string, never> | null
}): string {
  if (material.specification?.trim()) return material.specification.trim()
  const attributes = material.material_selection_snapshot?.attributes
  // 旧单只使用自己已保存的明确规格，不从当前 BOM 或材料档案回填。
  for (const key of ['specification', 'size', 'section_size', 'fabric_spec']) {
    const value = attributes?.[key]?.trim()
    if (value) return value
  }
  return '—'
}
