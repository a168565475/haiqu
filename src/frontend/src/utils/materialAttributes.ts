import type { MaterialAttributeField, MaterialAttributeSnapshot } from '@/types/purchaseOrder'

export interface MaterialAttributeSource {
  material_selection_snapshot?: import('@/types/materialCatalog').MaterialSelectionSnapshot | Record<string, never> | null
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
  const selected = source.material_selection_snapshot
  if (selected?.schema_version === 1 && selected.attributes) {
    const labels: Record<string, string> = {
      material: '材质', color: '颜色', shape: '截面形状', section_size: '规格', thickness: '厚度', length: '长度',
      fabric_spec: '面料规格', width: selected.template_key === 'TAPE' ? '宽度' : selected.template_key === 'COTTON' ? '幅宽' : '门幅',
      gram_weight: '克重', finish: '涂层/后处理', surface_finish: '表面处理', specification: '规格', size: '尺寸',
      thread: '螺纹规格', flow_unit: '流转单位', model: '型号/图号', tube_size: '适配管材尺寸', layers: '层数',
      box_type: '箱子形状', printing: '印刷版本', bag_type: '袋型/封口方式', process: '加工做法/工艺版本',
    }
    return [{ key: 'part_name', label: '品名', value: selected.name },
      ...Object.entries(selected.attributes).flatMap(([key, value]) => [
        ...(key === 'color' ? [
          ...(selected.color_card ? [{ key: 'color_card', label: '色卡', value: selected.color_card }] : []),
          ...(selected.color_code ? [{ key: 'color_code', label: '色号', value: selected.color_code }] : []),
        ] : []),
        { key, label: labels[key] || key, value },
      ]),
      { key: 'unit', label: '数量单位', value: selected.unit_name }]
  }
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
