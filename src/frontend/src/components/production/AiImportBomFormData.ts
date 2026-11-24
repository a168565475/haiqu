import type { BomLineInput, BomSectionInput, TubeCalculationInput } from '@/types/bom'
import type { MaterialCatalog, MaterialFieldDefinition, MaterialSelectionInput, PublicMaterialOptions } from '@/types/materialCatalog'
import { blankLine, decimalFraction, fixedSectionDefinitions, halfUpFixedText } from '@/views/boms/bomEditorHelpers'
import { applyMaterialSelection, bomCatalogCategories } from '@/components/products/materialSelection'
import { cuttingCalculation } from '@/utils/bomCuttingQuantities'

export interface AiBomLine extends BomLineInput {
  ai_line_key: string
  ai_original_text: string
  ai_source: Record<string, unknown>
  ai_pending: string[]
  ai_catalog?: { id: string; version: string; category_key: string; template_key: string }
  ai_tube_formula_key?: string
  ai_reference_override?: boolean
}
export interface AiBomSection extends BomSectionInput { lines: AiBomLine[] }
export interface AiBomDraft extends Record<string, unknown> {
  product_key: string
  product_label: string
  production_task_product_id: string
  order_quantity: string
  sections: AiBomSection[]
  pending_lines: AiBomLine[]
  reference_lines?: AiBomLine[]
}
export interface AiTaskProduct { id: string; client_key?: string; product_name_snapshot?: string; specification_snapshot?: string; quantity?: string }

export const erpBomFieldLabels: Record<string, string> = {
  unit_consumption: '单耗', total_consumption: '原表总需求', length_value: '切割长度（mm）',
  tube_shape: '截面形状', tube_diameter: '管材规格', tube_thickness: '厚度', tube_cut_piece_count: '切割支数',
  tube_coating_color: '喷塑颜色', material: '材质', specification: '规格', unit: '单位',
  hardware_color: '五金颜色', hardware_flow_unit: '五金流转单位', plastic_color: '塑料件颜色',
  accessory_color: '辅料颜色', packaging_color: '包材颜色', fabric_width: '门幅',
  fabric_color_name: '面料颜色', fabric_color_card: '色卡', fabric_color_code: '色号',
  units_per_box: '多少成品用一份', cutting_pieces_per_set: '裁片量（片/套）', cutting_sets_per_product: '每成品套数',
  powder_coating_color: '五金喷塑颜色', powder_coating_unit_area_sqm: '喷塑单个面积（㎡）',
  unit_material_weight_kg: '单个材料重量（kg）', raw_material: '原材料', hardness: '硬度',
  coating_unit_area_sqm: '喷塑单位面积（㎡）', purchase_unit_weight_kg: '采购单位重量（kg）', long_material_unit_weight_kg: '原材料单根重量（kg）',
  original_material_length: '原材料长度', source_raw_bar_length_m: '原材料长度（m）',
  source_purchase_allowance_percent: '采购余量比例', fabric_meters_per_set: '每套耗米',
  fabric_meters_per_piece: '每片耗米', cutting_color: '裁剪颜色', notes: '备注',
  catalog_size: '材料尺寸', catalog_model: '材料型号', catalog_thread: '螺纹规格',
  catalog_width: '材料宽度', catalog_thickness: '材料厚度',
  catalog_fabric_spec: '面料规格', catalog_gram_weight: '克重', catalog_finish: '涂层/后处理',
  catalog_tube_size: '适配管材尺寸', catalog_layers: '纸箱层数', catalog_box_type: '箱型',
  catalog_printing: '印刷版本/唛头', catalog_bag_type: '袋型/封口方式', catalog_process: '加工做法/工艺版本',
}
export const erpBomFieldNames = Object.keys(erpBomFieldLabels).filter(key => !key.startsWith('catalog_'))
export const tubeMetricFields = ['coating_unit_area_sqm', 'purchase_unit_weight_kg', 'long_material_unit_weight_kg'] as const

export function erpFieldValues(value: unknown): Record<string, unknown> {
  if (!Array.isArray(value)) return recordValue(value)
  const fields: Record<string, unknown> = {}
  for (const item of value.map(recordValue)) {
    if (typeof item.field !== 'string') continue
    fields[item.field] = Object.hasOwn(fields, item.field)
      ? { value: null, status: 'CONFLICT', note: '同一字段重复，请核对原始识别内容。' } : item.value
  }
  return fields
}

export function recordValue(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
}
export function extractedText(value: unknown): string {
  const field = recordValue(value)
  if (Object.keys(field).length) return field.status === 'EXTRACTED' && field.value != null ? String(field.value) : ''
  return value == null ? '' : String(value)
}
function sourceText(source: Record<string, unknown>): string {
  const labels: Record<string, string> = { part_name: '品名', material: '材质', specification: '规格', quantity: '原表数量', unit: '单位', notes: '备注' }
  const fields = { ...Object.fromEntries(Object.keys(labels).map(key => [key, source[key]])), ...erpFieldValues(source.erp_fields) }
  const lines = Object.entries(fields).flatMap(([key, value]) => {
    const field = recordValue(value)
    const text = field.value == null ? extractedText(value) : String(field.value)
    if (!text && !field.note) return []
    return [`${labels[key] || erpBomFieldLabels[key] || key}：${text}${field.status === 'CONFLICT' ? '（冲突）' : field.status === 'UNREADABLE' ? '（未读清）' : ''}${field.note ? `；${field.note}` : ''}`]
  })
  const rawField = recordValue(source.raw_content)
  const raw = rawField.value == null ? extractedText(source.raw_content) : String(rawField.value)
  return [raw, ...lines].filter(Boolean).join('\n')
}

export function recognizedSection(source: Record<string, unknown>): string {
  const title = extractedText(source.section).trim()
  if (fixedSectionDefinitions.some(item => item.title === title)) return title
  const aliases: Record<string, string> = { 型材: '管材类', 型材类: '管材类', 管材: '管材类', 五金: '五金件', 五金类: '五金件', 塑料件: '塑料件类', 面料: '面料类', 包材: '包材类', 辅料: '辅料类', 裁片: '裁剪明细' }
  if (aliases[title]) return aliases[title]
  const name = extractedText(source.part_name)
  const material = extractedText(source.material).trim()
  const specification = extractedText(source.specification)
  // 旧结果仅对名称明确的材料归类；“椅面”“扶手”等部件名须交由真实材料目录确定。
  if (/(钢管|铝管|铁管|圆管|方管|椭圆管|异型管|型材)/.test(`${name} ${specification}`)) return '管材类'
  if (/(纸箱|纸盒|包装袋|PE袋|OPP袋|气泡袋|唛头)/i.test(name)) return '包材类'
  if (/(塑料|塑胶|注塑)/.test(`${name} ${material}`) || /^(PP|ABS|POM|PA6|PA66|聚丙烯|聚甲醛)$/i.test(material)) return '塑料件类'
  if (/(铆钉|螺丝|螺栓|螺母|垫圈|垫片|弹簧)/.test(name)) return '五金件'
  if (/(牛津布|涤纶布|网布|帆布|面料)/.test(name)) return '面料类'
  if (/(魔术贴|拉链|松紧带|织带|缝纫线|喷胶棉|填充棉)/.test(name)) return '辅料类'
  return ''
}

export function makeAiBomLine(source: Record<string, unknown>, index: number): AiBomLine {
  const line: AiBomLine = { ...blankLine(), ai_line_key: String(source.line_key || `line-${index + 1}`),
    ai_original_text: sourceText(source), ai_source: JSON.parse(JSON.stringify(source)), ai_pending: [] }
  for (const key of ['part_name', 'material', 'specification', 'unit', 'notes'] as const) line[key] = extractedText(source[key])
  const fields = erpFieldValues(source.erp_fields)
  for (const key of erpBomFieldNames) {
    if (fields[key] != null) (line as unknown as Record<string, unknown>)[key] = extractedText(fields[key])
  }
  const conflicts = Object.entries({ ...source, ...fields }).filter(([, field]) => recordValue(field).status === 'CONFLICT').map(([key]) => erpBomFieldLabels[key] || key)
  if (conflicts.length) line.ai_pending.push(`原表字段冲突：${conflicts.join('、')}`)
  const unreadable = Object.entries({ ...source, ...fields }).filter(([, field]) => recordValue(field).status === 'UNREADABLE').map(([key]) => erpBomFieldLabels[key] || key)
  if (unreadable.length) line.ai_pending.push(`原表字段未读清：${unreadable.join('、')}`)
  const section = recognizedSection(source)
  const quantity = extractedText(source.quantity)
  if (source.quantity_basis === 'UNIT_CONSUMPTION' && quantity && line.unit.trim()) {
    if (section === '包材类' && !Object.hasOwn(fields, 'units_per_box')) {
      const amount = decimalFraction(quantity)
      if (amount && amount.numerator > 0n && amount.denominator * 10000n % amount.numerator === 0n) {
        line.units_per_box = halfUpFixedText(amount.denominator, amount.numerator, 4).replace(/\.?0+$/, '')
        line.ai_original_text += `\n用量换算：按原表每成品 ${quantity}${line.unit}，对应每份用于 ${line.units_per_box} 个成品。`
      } else line.ai_pending.push('包材用量：原表单耗无法精确换算为最多四位小数的成品基数，请核对。')
    } else if (section && section !== '裁剪明细' && section !== '包材类' && !Object.hasOwn(fields, 'unit_consumption')) line.unit_consumption = quantity
  }
  if (section === '管材类') clearTubeMetrics(line)
  return line
}

export function tubeCalculationInput(line: BomLineInput): TubeCalculationInput {
  return { tube_shape: line.tube_shape, tube_diameter: line.tube_diameter, tube_thickness: line.tube_thickness,
    length_value: line.length_value, tube_cut_piece_count: line.tube_cut_piece_count,
    ...(line.source_raw_bar_length_m?.trim() ? { source_raw_bar_length_m: line.source_raw_bar_length_m.trim() } : {}) }
}
export function tubeCalculationKey(line: BomLineInput): string { return JSON.stringify(tubeCalculationInput(line)) }
export function clearTubeMetrics(line: AiBomLine) {
  for (const field of tubeMetricFields) line[field] = ''
  line.manual_tube_metrics = false
  line.recalculate_tube_metrics = false
  line.expected_tube_formula_version = undefined
  line.tube_calculation_preview = undefined
  line.ai_tube_formula_key = undefined
  line.ai_pending = [...line.ai_pending.filter(item => !item.startsWith('管材公式：')), '管材公式：待按 ERP 公式计算']
}

export function rememberCatalog(line: AiBomLine, catalog: MaterialCatalog) {
  line.ai_catalog = { id: catalog.id, version: catalog.updated_at, category_key: catalog.category_key, template_key: catalog.template_key }
}

export function isReferenceLine(line: AiBomLine): boolean {
  return !line.ai_reference_override && !line.material_catalog_id && !line.material_selection && recordValue(line.ai_source.erp_match).status === 'REFERENCE'
}

export function latestErpMatch(result: Record<string, unknown>, productKey: string, lineKey: string): Record<string, unknown> | null {
  const boms = (Array.isArray(result.boms) ? result.boms.map(recordValue) : []).filter(bom => bom.product_key === productKey)
  if (!productKey || !lineKey || boms.length !== 1) return null
  const lines = (Array.isArray(boms[0]!.lines) ? boms[0]!.lines as unknown[] : []).map(recordValue).filter(line => line.line_key === lineKey)
  if (lines.length !== 1) return null
  const match = recordValue(lines[0]!.erp_match)
  return ['MATCHED', 'PARTIAL', 'NOT_FOUND', 'CONFLICT', 'REFERENCE'].includes(String(match.status)) ? match : null
}

export function copyLatestErpMatch(line: AiBomLine, result: Record<string, unknown>, productKey: string): boolean {
  const match = latestErpMatch(result, productKey, line.ai_line_key)
  if (!match || line.ai_reference_override && match.status === 'REFERENCE') return false
  if ((line.material_catalog_id || line.material_selection) && !Object.keys(erpColorUpdates(line, match)).length) return false
  line.ai_source = { ...line.ai_source, erp_match: JSON.parse(JSON.stringify(match)) }
  return true
}

export function erpColorUpdates(line: AiBomLine, match: Record<string, unknown>): Partial<Record<'tube_coating_color' | 'powder_coating_color', string>> {
  const catalog = recordValue(match.catalog)
  if (match.status !== 'MATCHED' || !catalog.id || catalog.spray_enabled !== true
    || bomCatalogCategories[String(match.section)] !== catalog.category_key
    || line.material_catalog_id && line.material_catalog_id !== catalog.id) return {}
  const allowed: Array<'tube_coating_color' | 'powder_coating_color'> = catalog.category_key === 'TUBE' ? ['tube_coating_color', 'powder_coating_color']
    : catalog.category_key === 'HARDWARE' ? ['powder_coating_color'] : []
  const fields = erpFieldValues(line.ai_source.erp_fields)
  if (!allowed.some(key => extractedText(fields[key] ?? line.ai_source[key]))) return {}
  const updates = recordValue(match.field_updates)
  return Object.fromEntries(allowed.flatMap(key => {
    const value = updates[key]
    const original = fields[key] ?? line.ai_source[key]
    if (['CONFLICT', 'UNREADABLE'].includes(String(recordValue(original).status)) || typeof value !== 'string' || !value.trim() || value.length > 200
      || (line[key] || '') !== extractedText(original) || line[key] === value.trim()) return []
    return [[key, value.trim()]]
  }))
}

function applyErpColorUpdates(line: AiBomLine, match: Record<string, unknown>) {
  const updates = erpColorUpdates(line, match)
  if (!Object.keys(updates).length) return
  const fields = erpFieldValues(line.ai_source.erp_fields)
  const keys = recordValue(match.catalog).category_key === 'TUBE' ? ['tube_coating_color', 'powder_coating_color'] : ['powder_coating_color']
  const requirements = [...new Set(keys.map(key => extractedText(fields[key] ?? line.ai_source[key])).filter(Boolean))]
  Object.assign(line, updates)
  for (const requirement of requirements) if (!line.notes.includes(requirement)) line.notes = [line.notes, `原表喷塑要求：${requirement}`].filter(Boolean).join('\n')
}

export function applyErpMatch(line: AiBomLine): string {
  const match = recordValue(line.ai_source.erp_match)
  applyErpColorUpdates(line, match)
  if (line.material_catalog_id || line.material_selection) return ''
  if (!match.status) return ''
  if (match.status === 'REFERENCE' && line.ai_reference_override) return ''
  const pending = line.ai_pending.filter(item => !item.startsWith('ERP对应：'))
  const note = typeof match.note === 'string' ? match.note.trim() : ''
  if (match.status !== 'MATCHED') {
    line.ai_pending = [...pending, `ERP对应：${note || (match.status === 'REFERENCE' ? '汇总或说明，仅供核对，不计入材料。' : '材料对应尚未完成，请核对。')}`]
    return ''
  }
  const catalog = recordValue(match.catalog)
  const selection = recordValue(match.selection)
  const section = typeof match.section === 'string' ? match.section : ''
  const attributes = recordValue(selection.attributes)
  const cutting = catalog.category_key === 'FABRIC_SEMI'
  if (![catalog.id, catalog.updated_at, catalog.name, catalog.template_key].every(value => typeof value === 'string' && value)
    || !Array.isArray(catalog.units) || catalog.units.some(unit => typeof recordValue(unit).unit_id !== 'string')
    || !bomCatalogCategories[section] || bomCatalogCategories[section] !== catalog.category_key
    || !selection.catalog_version || !['BASE', 'SPRAY'].includes(String(selection.scope))
    || !Object.keys(attributes).length || Object.values(attributes).some(value => typeof value !== 'string')
    || !(selection.unit_id || selection.unit_name)
    || (cutting ? selection.processing_state !== 'PROCESSED' || selection.semi_kind !== 'CUTTING' || !recordValue(selection.completed_craft).id : selection.processing_state !== 'RAW')) {
    line.ai_pending = [...pending, 'ERP对应：材料类别、属性、单位或工艺不完整，请核对。']
    return ''
  }
  // 目录身份使用后端已核验的选择；原表品名、原文及制造用量仍属于当前行。
  const partName = line.part_name
  applyMaterialSelection(line, catalog as unknown as MaterialCatalog, JSON.parse(JSON.stringify(selection)) as MaterialSelectionInput)
  line.part_name = partName
  if (typeof match.unit_name === 'string' && match.unit_name.trim()) line.unit = match.unit_name
  rememberCatalog(line, catalog as unknown as MaterialCatalog)
  line.ai_pending = pending.filter(item => !item.startsWith('ERP材料：') && !item.startsWith('ERP属性：'))
  return section
}

export function separateReferenceLines(draft: AiBomDraft) {
  const references = draft.reference_lines || []
  const keepMaterial = (line: AiBomLine) => {
    if (!isReferenceLine(line)) return true
    applyErpMatch(line)
    references.push(line)
    return false
  }
  draft.sections.forEach(section => { section.lines = section.lines.filter(keepMaterial) })
  draft.pending_lines = draft.pending_lines.filter(keepMaterial)
  draft.reference_lines = references
}
export function isCuttingSource(line: AiBomLine): boolean {
  const selection = line.material_selection ?? line.material_selection_snapshot
  if (!line.material_catalog_id || selection?.processing_state !== 'RAW' || !isMeterUnit(line.unit)) return false
  const snapshot = line.material_selection_snapshot?.catalog_id === line.material_catalog_id ? line.material_selection_snapshot : undefined
  const current = line.ai_catalog?.id === line.material_catalog_id && line.ai_catalog.version === selection.catalog_version ? line.ai_catalog : snapshot
  return current?.category_key === 'FABRIC' || current?.category_key === 'AUXILIARY' && current.template_key === 'COTTON'
}

function linkSourceLines(draft: AiBomDraft) {
  const lines = [...draft.sections.flatMap(section => section.lines), ...draft.pending_lines]
  for (const line of draft.sections.find(section => section.title === '裁剪明细')?.lines || []) {
    const sourceKey = extractedText(line.ai_source.source_line_key)
    if (!sourceKey) continue
    const matches = lines.filter(item => item !== line && item.ai_line_key === sourceKey && !draft.sections.find(section => section.title === '裁剪明细')?.lines.includes(item))
    if (matches.length === 1) line.fabric_source_client_key = matches[0]!.client_key
    else line.ai_pending.push('来源原料：未找到本 BOM 中唯一的原料行，请核对。')
  }
}

export function makeAiBomDrafts(result: Record<string, unknown>, saved: Array<Record<string, unknown>> | null): AiBomDraft[] {
  if (saved) return saved.map(item => {
    const draft = recordValue(item)
    const sections = Array.isArray(draft.sections) ? draft.sections.map(recordValue) : []
    const restore = (value: unknown): AiBomLine => {
      const line = recordValue(value)
      return { ...blankLine(), ...JSON.parse(JSON.stringify(line)), ai_line_key: String(line.ai_line_key || line.client_key || ''),
        // 只清除旧版自动拼接的机器来源块，保留用户已调整的其余原文。
        ai_original_text: String(line.ai_original_text || '').replace(/ ?\[src_[a-f0-9]{64}(?:、src_[a-f0-9]{64})*\]/gi, ''), ai_source: recordValue(line.ai_source),
        ai_pending: Array.isArray(line.ai_pending) ? line.ai_pending.map(String) : [] } as AiBomLine
    }
    const restored: AiBomDraft = { ...JSON.parse(JSON.stringify(draft)), product_key: String(draft.product_key || ''), product_label: String(draft.product_label || ''),
      production_task_product_id: String(draft.production_task_product_id || ''), order_quantity: String(draft.order_quantity || ''),
      sections: fixedSectionDefinitions.map(section => {
        const lines = sections.find(item => item.title === section.title)?.lines
        return { ...section, lines: (Array.isArray(lines) ? lines : []).map(restore) }
      }),
      pending_lines: (Array.isArray(draft.pending_lines) ? draft.pending_lines : []).map(restore),
      reference_lines: (Array.isArray(draft.reference_lines) ? draft.reference_lines : []).map(restore) }
    separateReferenceLines(restored)
    return restored
  })
  const products = Array.isArray(result.products) ? result.products.map(recordValue) : []
  const boms = Array.isArray(result.boms) ? result.boms.map(recordValue) : []
  return boms.map((bom, index) => {
    const productKey = String(bom.product_key || '')
    const productsMatched = products.filter(item => item.product_key === productKey)
    const product = productsMatched.length === 1 ? productsMatched[0]! : {}
    const draft: AiBomDraft = { product_key: productKey, product_label: extractedText(product.name) || `BOM ${index + 1}`,
      production_task_product_id: '', order_quantity: extractedText(product.quantity),
      sections: fixedSectionDefinitions.map(section => ({ ...section, lines: [] })), pending_lines: [] }
    ;(Array.isArray(bom.lines) ? bom.lines : []).map(recordValue).forEach((source, lineIndex) => {
      const line = makeAiBomLine(source, lineIndex)
      const matchedSection = applyErpMatch(line)
      const section = draft.sections.find(item => item.title === (matchedSection || recognizedSection(source)))
      if (section) section.lines.push(line)
      else draft.pending_lines.push(line)
    })
    separateReferenceLines(draft)
    linkSourceLines(draft)
    return draft
  })
}

export function linkTaskProducts(drafts: AiBomDraft[], products: AiTaskProduct[]) {
  for (const draft of drafts) {
    if (draft.production_task_product_id) continue
    const matches = products.filter(item => draft.product_key && item.client_key === draft.product_key)
    if (matches.length === 1) draft.production_task_product_id = matches[0]!.id
  }
}

function normalized(value: string): string { return value.trim().toLowerCase().replace(/\s+/g, '').replace(/[×＊]/g, '*') }
export function materialNameMatches(left: string, right: string): boolean { return normalized(left) === normalized(right) }
export function isMeterUnit(unit: string): boolean { return ['米', 'm'].includes(unit.trim().toLowerCase()) }
function unitMatches(source: string, candidate: string): boolean {
  const left = normalized(source), right = normalized(candidate)
  if (left === right) return true
  if (['pcs', 'pc'].includes(left) && ['个', '件', '只', 'pcs', 'pc'].includes(right)) return true
  return [['米', 'm'], ['千克', '公斤', 'kg'], ['克', 'g']].some(group => group.includes(left) && group.includes(right))
}
export function fabricUnitIssue(line: BomLineInput): string {
  if (line.unit.trim() && !isMeterUnit(line.unit)) return `原表单位为${line.unit}，请核对后填写米制单耗。`
  if (!line.unit.trim() && line.unit_consumption.trim()) return '原表单耗单位未明确，请核对后填写米制单耗。'
  return ''
}
export function prepareFabricMeterSelection(line: AiBomLine): string {
  const issue = fabricUnitIssue(line)
  if (issue) {
    line.unit_consumption = ''
    line.ai_pending = [...line.ai_pending.filter(item => !item.startsWith('面料单位：')), `面料单位：${issue}`]
  }
  return issue
}

/** 缺少候选时保留识别值，供用户核对和选料。 */
export function applyRecognizedCatalog(line: AiBomLine, catalog: MaterialCatalog, options: Pick<PublicMaterialOptions, 'values' | 'units'> & { fields: MaterialFieldDefinition[] }): boolean {
  if (catalog.category_key === 'FABRIC_SEMI') {
    const matchCatalog = recordValue(recordValue(line.ai_source.erp_match).catalog)
    return matchCatalog.id === catalog.id && applyErpMatch(line) === '裁剪明细'
  }
  if (catalog.category_key === 'FABRIC' && fabricUnitIssue(line)) return false
  const color = catalog.category_key === 'TUBE' ? '' : catalog.category_key === 'FABRIC' ? line.fabric_color_name
    : catalog.category_key === 'HARDWARE' ? line.hardware_color : catalog.category_key === 'PLASTIC' ? line.plastic_color
      : catalog.category_key === 'PACKAGING' ? line.packaging_color : line.accessory_color
  const recognized = erpFieldValues(line.ai_source.erp_fields)
  const explicit = Object.fromEntries(['size', 'model', 'thread', 'width', 'thickness', 'fabric_spec', 'gram_weight', 'finish', 'tube_size', 'layers', 'box_type', 'printing', 'bag_type', 'process'].map(key => [key, extractedText(recognized[`catalog_${key}`])]))
  const hasExplicitIdentity = ['size', 'model', 'thread'].some(key => explicit[key])
  const input: Record<string, string> = { material: line.material, shape: line.tube_shape,
    section_size: catalog.category_key === 'TUBE' ? line.tube_diameter || line.specification : '',
    thickness: explicit.thickness || (catalog.category_key === 'TUBE' ? line.tube_thickness : ''),
    specification: hasExplicitIdentity ? '' : line.specification,
    fabric_spec: catalog.category_key === 'FABRIC' ? explicit.fabric_spec || line.specification : '',
    width: explicit.width || (catalog.category_key === 'FABRIC' ? line.fabric_width : ''), color,
    flow_unit: line.hardware_flow_unit, size: explicit.size || '', model: explicit.model || '', thread: explicit.thread || '',
    ...Object.fromEntries(['gram_weight', 'finish', 'tube_size', 'layers', 'box_type', 'printing', 'bag_type', 'process'].map(key => [key, explicit[key] || ''])) }
  // 泛称“规格”只能落到一个有依据的身份字段，不能同时充当尺寸、型号和螺纹。
  if (!hasExplicitIdentity && !options.fields.some(field => field.key === 'specification') && !['TUBE', 'FABRIC'].includes(catalog.category_key)) {
    const targets = ['size', 'model', 'thread'].filter(key => options.values.some(item => item.field_key === key && materialNameMatches(item.value, line.specification)))
    if (targets.length === 1) input[targets[0]!] = line.specification
  }
  const attributes: Record<string, string> = {}
  let colorRow: PublicMaterialOptions['values'][number] | undefined
  for (const field of options.fields.filter(item => item.kind !== 'unit').sort((left, right) => Number(right.key === 'shape') - Number(left.key === 'shape'))) {
    const value = input[field.key]
    if (!value) continue
    let candidates = options.values.filter(item => item.field_key === field.key && materialNameMatches(item.value, value))
    if (field.key === 'section_size') {
      const shape = options.values.find(item => item.field_key === 'shape' && item.value === attributes.shape)
      candidates = candidates.filter(item => !!shape && item.parent_id === shape.id)
    }
    if (field.key === 'color' && catalog.category_key === 'FABRIC') {
      candidates = candidates.filter(item => (!line.fabric_color_code || item.color_code === line.fabric_color_code) && (!line.fabric_color_card || item.color_card === line.fabric_color_card))
    }
    const values = [...new Set(candidates.map(item => item.value))]
    if (values.length !== 1 || (field.key === 'color' && catalog.category_key === 'FABRIC' && candidates.length !== 1)) continue
    attributes[field.key] = values[0]!
    if (field.key === 'color') colorRow = candidates[0]
  }
  const unmatched = options.fields.filter(field => field.kind !== 'unit' && input[field.key] && !attributes[field.key]).map(field => field.label)
  unmatched.push(...Object.entries(explicit).filter(([key, value]) => value && !options.fields.some(field => field.key === key)).map(([key]) => erpBomFieldLabels[`catalog_${key}`] || key))
  line.ai_pending = line.ai_pending.filter(item => !item.startsWith('ERP属性：'))
  if (unmatched.length) {
    line.ai_pending.push(`ERP属性：${unmatched.join('、')}未匹配，保留原值待选择。`)
    return false
  }
  const required: Record<string, string[]> = { TUBE: ['material', 'shape', 'section_size', 'thickness'], FABRIC: ['material', 'fabric_spec', 'width', 'color'] }
  const identity: Record<string, string[]> = { HARDWARE: ['specification', 'size', 'thread'], PLASTIC: ['specification', 'model', 'size'], CARTON: ['size', 'model'], BAG: ['size', 'model'], PACKAGING_GENERAL: ['specification', 'model'], TAPE: ['specification', 'width'], COTTON: ['specification', 'thickness', 'width'], AUXILIARY_GENERAL: ['specification'] }
  const requiredKeys = required[catalog.template_key]
  if (requiredKeys ? requiredKeys.some(key => !attributes[key]) : !(identity[catalog.template_key] || []).some(key => attributes[key])) return false
  const unitName = catalog.category_key === 'TUBE' ? '根' : catalog.category_key === 'FABRIC' ? '米' : line.unit
  const units = options.units.filter(item => unitMatches(unitName, item.unit_name))
  if (units.length !== 1) return false
  const selection: MaterialSelectionInput = { catalog_version: catalog.updated_at, scope: 'BASE', processing_state: 'RAW', attributes, unit_id: units[0]!.id }
  if (catalog.category_key === 'FABRIC' && colorRow) Object.assign(selection, { product_color_id: colorRow.product_color_id || null, color_card: colorRow.color_card || '', color_code: colorRow.color_code || '', color_name: colorRow.color_name || colorRow.value })
  applyMaterialSelection(line, catalog, selection)
  rememberCatalog(line, catalog)
  line.unit = units[0]!.unit_name
  return true
}

export function buildAiBomPlans(drafts: AiBomDraft[], products: AiTaskProduct[]): Array<Record<string, unknown>> {
  const used = new Set<string>()
  return drafts.map(draft => {
    if (draft.pending_lines.length) throw new Error(`${draft.product_label} 还有 ${draft.pending_lines.length} 行材料未选择分区。`)
    const match = products.find(item => item.id === draft.production_task_product_id)
    if (!match) throw new Error(`${draft.product_label} 请先选择当前生产任务中的产品。`)
    if (used.has(match.id)) throw new Error('多个 BOM 对应了同一条任务产品，请分别确认产品。')
    used.add(match.id)
    const sections = draft.sections.map(section => ({ ...section, lines: section.lines.map(line => {
      if (!line.part_name.trim()) throw new Error(`${section.title} 有材料缺少品名。`)
      if (!line.material_catalog_id || !line.material_selection) throw new Error(`${line.part_name} 请先对应 ERP 材料品名、属性和单位。`)
      if (!Object.keys(line.material_selection.attributes).length || !(line.material_selection.unit_id || line.material_selection.unit_name)) throw new Error(`${line.part_name} 请补齐材料属性和单位。`)
      if (line.source_raw_bar_length_m?.trim()) {
        const length = decimalFraction(line.source_raw_bar_length_m)
        if (!length || length.numerator <= 0n) throw new Error(`${line.part_name} 原材料长度（m）必须为正数，请在“调整材料”中修改。`)
        if (length.numerator * 1000n % length.denominator !== 0n) throw new Error(`${line.part_name} 原材料长度（m）最多保留 3 位小数，请在“调整材料”中核对原值 ${line.source_raw_bar_length_m} 后填写；原文仍保留。`)
      }
      if (section.title === '管材类' && (!line.tube_calculation_preview || line.ai_tube_formula_key !== tubeCalculationKey(line))) throw new Error(`${line.part_name} 请先补齐规格并完成 ERP 管材公式计算。`)
      if (section.title === '包材类') {
        const amount = decimalFraction(line.units_per_box)
        if (!amount || amount.numerator <= 0n || amount.numerator * 10000n % amount.denominator !== 0n) throw new Error(`${line.part_name} 请填写正数用量（多少成品用一份），最多 4 位小数。`)
      }
      if (section.title === '面料类' && fabricUnitIssue(line)) throw new Error(`${line.part_name} ${fabricUnitIssue(line)}`)
      if (section.title === '裁剪明细') {
        const source = draft.sections.flatMap(item => item.lines).find(item => item.client_key === line.fabric_source_client_key)
        if (!source || !isCuttingSource(source)) throw new Error(`${line.part_name} 请先选择本 BOM 中已对应的米制来源面料或棉类原料。`)
        const selection = line.material_selection
        if (selection.processing_state !== 'PROCESSED' || selection.semi_kind !== 'CUTTING' || !selection.completed_craft?.id) throw new Error(`${line.part_name} 请重新选择具有有效裁剪工艺的裁片品名。`)
        const quantities = cuttingCalculation(line, draft.order_quantity)
        if (quantities.mode === 'incomplete' || quantities.mode === 'invalid') throw new Error(`${line.part_name} ${quantities.error}`)
      }
      const expected = bomCatalogCategories[section.title]
      if (line.material_selection_snapshot?.category_key && line.material_selection_snapshot.category_key !== expected) throw new Error(`${line.part_name} 的材料类别与分区不一致，请重新选料。`)
      const result = { ...line } as Record<string, unknown>
      for (const key of Object.keys(result)) if (key.startsWith('ai_') || key.startsWith('catalog_') || key === 'material_quantity' || key === 'material_selection_snapshot' || key.endsWith('_preview') || key === 'pending_raw_material' || ['fabric_meters_per_set', 'fabric_meters_per_piece'].includes(key)) delete result[key]
      for (const key of ['cutting_pieces_per_set', 'cutting_sets_per_product']) if (result[key] === '' || result[key] == null) delete result[key]
      // 此入口只提交新材料目录身份，不混用旧原料来源。
      for (const key of Object.keys(result)) if (key.startsWith('source_') && key.endsWith('_id')) delete result[key]
      return result
    }) }))
    return { production_task_product_id: match.id, sections }
  })
}
