import type { MaterialAttributeField, MaterialAttributeSnapshot } from '@/types/purchaseOrder'

export interface MaterialAttributeSource {
  material_attributes_snapshot?: MaterialAttributeSnapshot | null
  section_type?: string | null
  section_title?: string | null
  section_type_snapshot?: string | null
  section_title_snapshot?: string | null
  part_name?: string | null
  material?: string | null
  specification?: string | null
  raw_material?: string | null
  part_name_snapshot?: string | null
  material_snapshot?: string | null
  specification_snapshot?: string | null
  raw_material_snapshot?: string | null
}

function text(value: unknown): string {
  return value === null || value === undefined ? '' : String(value).trim()
}

export function materialAttributeFields(source: MaterialAttributeSource): MaterialAttributeField[] {
  const snapshotFields = source.material_attributes_snapshot?.fields
  if (Array.isArray(snapshotFields) && snapshotFields.length) {
    return snapshotFields.filter((field) => text(field?.label) && text(field?.value)
      && field.key !== 'tube_coating_color' && text(field.label) !== '喷塑颜色').map((field) => ({
      key: text(field.key), label: text(field.label), value: text(field.value),
    }))
  }
  const partName = text(source.part_name ?? source.part_name_snapshot)
  const material = text(source.material ?? source.material_snapshot)
  const specification = text(source.specification ?? source.specification_snapshot)
  const rawMaterial = text(source.raw_material ?? source.raw_material_snapshot)
  const fields: MaterialAttributeField[] = []
  if (partName) fields.push({ key: 'part_name', label: '品名', value: partName })
  if (material) fields.push({ key: 'material', label: '材质', value: material })
  if (specification) fields.push({ key: 'specification', label: '规格', value: specification })
  if (rawMaterial && rawMaterial !== material && rawMaterial !== partName) {
    fields.push({ key: 'raw_material', label: '原材料', value: rawMaterial })
  }
  return fields
}

export function materialAttributeText(source: MaterialAttributeSource): string {
  return materialAttributeFields(source).map((field) => `${field.label}：${field.value}`).join('\n') || '暂无物料属性'
}

export function materialSpecificationValue(source: MaterialAttributeSource): string {
  const fields = materialAttributeFields(source)
  const title = text(source.section_title ?? source.section_title_snapshot)
  const sectionType = text(source.section_type ?? source.section_type_snapshot)
  const preferredKey = title.includes('面料')
    ? 'specification'
    : (title.includes('型材') || title.includes('管材') || sectionType === 'PROFILE')
      ? 'part_name'
      : 'part_name'
  return fields.find((field) => field.key === preferredKey)?.value
    || fields.find((field) => field.key === 'part_name' || field.key === 'specification')?.value
    || '—'
}
