import type {
  BomDetail,
  BomLine,
  BomLineInput,
  BomSection,
  BomSectionInput,
  BomSectionType,
} from '@/types/bom'
import { pipePlanForBomLine } from '@/utils/materialFlow'

export interface FixedSectionDefinition {
  title: string
  section_type: BomSectionType
}

export const fixedSectionDefinitions: FixedSectionDefinition[] = [
  { title: '管材类', section_type: 'PROFILE' },
  { title: '五金件', section_type: 'ACCESSORY' },
  { title: '塑料件类', section_type: 'ACCESSORY' },
  { title: '辅料类', section_type: 'FABRIC' },
  { title: '面料类', section_type: 'FABRIC' },
  { title: '包材类', section_type: 'ACCESSORY' },
  { title: '裁剪明细', section_type: 'FABRIC' },
]

export function createDraftKey() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID()
  const bytes = new Uint8Array(16)
  if (globalThis.crypto?.getRandomValues) globalThis.crypto.getRandomValues(bytes)
  else for (let index = 0; index < bytes.length; index += 1) bytes[index] = Math.floor(Math.random() * 256)
  bytes[6] = ((bytes[6] || 0) & 0x0f) | 0x40
  bytes[8] = ((bytes[8] || 0) & 0x3f) | 0x80
  const hex = Array.from(bytes, (value) => value.toString(16).padStart(2, '0')).join('')
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
}

export function blankLine(defaultUnit = ''): BomLineInput {
  return {
    client_key: createDraftKey(),
    category: '', material: '', part_name: '', specification: '', raw_material: '', length_value: '',
    unit_consumption: '', total_consumption: '', unit: defaultUnit, hardness: '', original_material_length: '',
    branch_count: '', budget_quantity: '', inventory_quantity: '', weight_grams: '', cut_piece_quantity: '',
    purchase_consumption: '', source_order_quantity: '', total_purchase_quantity: '', notes: '',
    tube_shape: '', tube_diameter: '', tube_thickness: '', tube_coating_color: '',
    coating_unit_area_sqm: '', purchase_unit_weight_kg: '', tube_cut_piece_count: '',
    source_inventory_material_id: null,
    source_raw_material_id: null, hardware_material_number: '', hardware_color: '', hardware_flow_unit: '',
    unit_material_weight_kg: '', powder_coating_color: '', powder_coating_unit_area_sqm: '',
    plastic_material_number: '', plastic_color: '',
    source_packaging_material_id: null, packaging_material_number: '', packaging_color: '', units_per_box: '',
    source_cutting_material_id: null, cutting_material_number: '', cutting_item_type: '',
    cutting_item_type_display: '', cutting_category: '', cutting_color: '', images: [],
    draft_key: '', draft_images: [],
    source_accessory_product_name_id: null, source_accessory_specification_id: null,
    source_accessory_color_id: null, source_accessory_material_id: null, accessory_color: '',
    source_fabric_material_id: null, source_fabric_specification_id: null,
    source_fabric_width_id: null, source_product_color_id: null, fabric_width: '',
    fabric_color_card: '', fabric_color_code: '', fabric_color_name: '',
  }
}

export function editableLine(line: BomLine): BomLineInput {
  return {
    id: line.id,
    category: line.category,
    material: line.material,
    part_name: line.part_name,
    specification: line.specification,
    raw_material: line.raw_material,
    length_value: line.length_value,
    unit_consumption: line.unit_consumption,
    total_consumption: line.total_consumption,
    unit: line.unit,
    hardness: line.hardness,
    original_material_length: line.original_material_length,
    branch_count: line.branch_count,
    budget_quantity: line.budget_quantity,
    inventory_quantity: line.inventory_quantity,
    weight_grams: line.weight_grams,
    cut_piece_quantity: line.cut_piece_quantity,
    purchase_consumption: line.purchase_consumption,
    source_order_quantity: line.source_order_quantity,
    total_purchase_quantity: line.total_purchase_quantity,
    notes: line.notes,
    tube_shape: line.tube_shape,
    tube_diameter: line.tube_diameter,
    tube_thickness: line.tube_thickness,
    tube_coating_color: line.tube_coating_color,
    coating_unit_area_sqm: line.coating_unit_area_sqm,
    purchase_unit_weight_kg: line.purchase_unit_weight_kg,
    tube_cut_piece_count: line.tube_cut_piece_count,
    source_inventory_material_id: line.source_inventory_material_id || null,
    fabric_source_line_id: line.fabric_source_line_id || null,
    fabric_meters_per_set: line.fabric_meters_per_set || null,
    cutting_pieces_per_set: line.cutting_pieces_per_set ?? null,
    fabric_meters_per_piece: line.fabric_meters_per_piece ?? null,
    cutting_sets_per_product: line.cutting_sets_per_product ?? null,
    source_raw_material_id: line.source_raw_material_id || null,
    hardware_material_number: line.hardware_material_number || '',
    hardware_color: line.hardware_color || '',
    hardware_flow_unit: line.hardware_flow_unit || '',
    unit_material_weight_kg: line.unit_material_weight_kg || '',
    powder_coating_color: line.powder_coating_color || '',
    powder_coating_unit_area_sqm: line.powder_coating_unit_area_sqm || '',
    plastic_material_number: line.plastic_material_number || '',
    plastic_color: line.plastic_color || '',
    source_packaging_material_id: line.source_packaging_material_id || null,
    packaging_material_number: line.packaging_material_number || '',
    packaging_color: line.packaging_color || '',
    units_per_box: line.units_per_box || '',
    source_cutting_material_id: line.source_cutting_material_id || null,
    cutting_material_number: line.cutting_material_number || '',
    cutting_item_type: line.cutting_item_type || '',
    cutting_item_type_display: line.cutting_item_type_display || '',
    cutting_category: line.cutting_category || '',
    cutting_color: line.cutting_color || '',
    images: [...(line.images || [])],
    draft_key: '',
    draft_images: [],
    source_accessory_product_name_id: line.source_accessory_product_name_id || null,
    source_accessory_specification_id: line.source_accessory_specification_id || null,
    source_accessory_color_id: line.source_accessory_color_id || null,
    source_accessory_material_id: line.source_accessory_material_id || null,
    accessory_color: line.accessory_color || '',
    source_fabric_material_id: line.source_fabric_material_id || null,
    source_fabric_specification_id: line.source_fabric_specification_id || null,
    source_fabric_width_id: line.source_fabric_width_id || null,
    source_product_color_id: line.source_product_color_id || null,
    fabric_width: line.fabric_width || '',
    fabric_color_card: line.fabric_color_card || '',
    fabric_color_code: line.fabric_color_code || '',
    fabric_color_name: line.fabric_color_name || '',
  }
}

export function editableSection(section: BomSection): BomSectionInput {
  const lines = section.lines.map((line) => {
    const editable = editableLine(line)
    if (section.section_type === 'PROFILE') {
      if (!editable.unit) editable.unit = 'PCS'
      editable.tube_cut_piece_count = String(editable.tube_cut_piece_count || '').trim()
    }
    return editable
  })
  return {
    id: section.id,
    section_type: section.section_type,
    title: section.title,
    lines: lines.length || section.section_type !== 'PROFILE' ? lines : [blankLine('根')],
  }
}

export function defaultTubeSection(): BomSectionInput {
  return { section_type: 'PROFILE', title: '管材类', lines: [blankLine('根')] }
}

export function emptyFixedSection(definition: FixedSectionDefinition): BomSectionInput {
  return definition.section_type === 'PROFILE'
    ? defaultTubeSection()
    : { section_type: definition.section_type, title: definition.title, lines: [] }
}

export function matchingFixedTitle(section: BomSectionInput, usedTitles: Set<string>) {
  if (section.section_type === 'PROFILE') return '管材类'
  const title = section.title.replace(/\s+/g, '')
  const keywordMatches = [
    { title: '裁剪明细', pattern: /裁剪|裁片/ },
    { title: '塑料件类', pattern: /塑料/ },
    { title: '包材类', pattern: /包材|包装/ },
    { title: '五金件', pattern: /五金|配件/ },
    { title: '面料类', pattern: /面料|面辅料/ },
    { title: '辅料类', pattern: /辅料/ },
  ]
  const keywordMatch = keywordMatches.find((item) => item.pattern.test(title) && !usedTitles.has(item.title))
  if (keywordMatch) return keywordMatch.title
  const candidates = section.section_type === 'FABRIC'
    ? ['面料类', '辅料类', '裁剪明细']
    : ['五金件', '塑料件类', '包材类']
  return candidates.find((candidate) => !usedTitles.has(candidate)) || section.title
}

export function fixedTitleFromLine(line: BomLineInput, fallbackTitle: string) {
  if (line.source_cutting_material_id || line.cutting_material_number || /裁剪|裁片/.test(line.category)) return '裁剪明细'
  if (line.source_packaging_material_id || line.packaging_material_number || line.units_per_box || /包材|包装/.test(line.category)) return '包材类'
  if (line.hardware_material_number || /五金/.test(line.category)) return '五金件'
  if (line.plastic_material_number || /塑料/.test(line.category)) return '塑料件类'
  if (line.source_fabric_material_id || line.fabric_width || line.fabric_color_card || line.fabric_color_code || line.fabric_color_name || /面料/.test(line.category)) return '面料类'
  if (line.source_accessory_product_name_id || line.source_accessory_material_id || line.accessory_color || /辅料/.test(line.category)) return '辅料类'
  return fallbackTitle
}

export function withFixedSections(sourceSections: BomSection[]) {
  const usedTitles = new Set<string>()
  const fixedOrder = new Map(fixedSectionDefinitions.map((item, index) => [item.title, index]))
  const sectionByTitle = new Map<string, BomSectionInput>()
  for (const sourceSection of sourceSections) {
    const section = editableSection(sourceSection)
    const fixedTitle = matchingFixedTitle(section, usedTitles)
    if (!fixedOrder.has(fixedTitle)) continue
    usedTitles.add(fixedTitle)
    const canonicalSection: BomSectionInput = {
      ...section,
      title: fixedTitle,
      lines: [...(sectionByTitle.get(fixedTitle)?.lines || [])],
    }
    sectionByTitle.set(fixedTitle, canonicalSection)
    for (const line of section.lines) {
      const lineTitle = fixedTitleFromLine(line, fixedTitle)
      const target = sectionByTitle.get(lineTitle)
      if (target) target.lines.push(line)
      else {
        const definition = fixedSectionDefinitions.find((item) => item.title === lineTitle)
        if (definition) sectionByTitle.set(lineTitle, { section_type: definition.section_type, title: lineTitle, lines: [line] })
      }
    }
  }
  for (const definition of fixedSectionDefinitions) {
    if (!sectionByTitle.has(definition.title)) sectionByTitle.set(definition.title, emptyFixedSection(definition))
  }
  const tubeSection = sectionByTitle.get('管材类')
  if (tubeSection && !tubeSection.lines.length) tubeSection.lines.push(blankLine('根'))
  const preserved = [...sectionByTitle.values()]
  return preserved.sort((left, right) => (
    (fixedOrder.get(left.title) ?? fixedSectionDefinitions.length)
    - (fixedOrder.get(right.title) ?? fixedSectionDefinitions.length)
  ))
}

export function number(value: string | number | null | undefined) {
  if (value === null || value === undefined || value === '') return '—'
  const parsed = Number(value)
  return Number.isFinite(parsed) ? new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 4 }).format(parsed) : String(value)
}

export function decimalValuesEqual(leftValue: string | number, rightValue: string | number) {
  const left = decimalFraction(leftValue)
  const right = decimalFraction(rightValue)
  return Boolean(left && right && left.numerator * right.denominator === right.numerator * left.denominator)
}

export function decimalDifferenceText(value: string | number, baseline: string | number) {
  const current = decimalFraction(value)
  const base = decimalFraction(baseline)
  if (!current || !base) return '—'
  const numerator = current.numerator * base.denominator - base.numerator * current.denominator
  const denominator = current.denominator * base.denominator
  const difference = halfUpFixedText(numerator, denominator, 4).replace(/\.?0+$/, '') || '0'
  return `${numerator > 0n ? '+' : ''}${number(difference)}`
}

export type TubeCalculationKey =
  | 'total_consumption'
  | 'tube_cut_length_m'
  | 'suggested_purchase_meters'
  | 'branch_count'
  | 'long_material_unit_weight_kg'
  | 'tube_unit_weight_kg'
  | 'long_material_total_weight_kg'

export interface DecimalFraction {
  numerator: bigint
  denominator: bigint
}

export function decimalFraction(value: string | number | null | undefined): DecimalFraction | null {
  const text = String(value ?? '').trim()
  const match = text.match(/^([+-]?)(\d*)(?:\.(\d*))?(?:[eE]([+-]?\d+))?$/)
  if (!match || (!match[2] && !match[3])) return null
  const exponent = Number(match[4] || 0)
  if (!Number.isInteger(exponent) || Math.abs(exponent) > 100) return null
  const fractionDigits = match[3] || ''
  const digits = `${match[2] || '0'}${fractionDigits}`.replace(/^0+(?=\d)/, '')
  let numerator = BigInt(digits || '0')
  let scaleDigits = fractionDigits.length - exponent
  if (scaleDigits < 0) {
    numerator *= 10n ** BigInt(-scaleDigits)
    scaleDigits = 0
  }
  if (match[1] === '-') numerator = -numerator
  return { numerator, denominator: 10n ** BigInt(scaleDigits) }
}

export function halfUpFixedText(numerator: bigint, denominator: bigint, fractionDigits: number) {
  if (denominator <= 0n || fractionDigits < 0) return ''
  const negative = numerator < 0n
  const absoluteNumerator = negative ? -numerator : numerator
  const factor = 10n ** BigInt(fractionDigits)
  const scaledNumerator = absoluteNumerator * factor
  const quotient = scaledNumerator / denominator
  const remainder = scaledNumerator % denominator
  const rounded = quotient + (remainder * 2n >= denominator ? 1n : 0n)
  const whole = rounded / factor
  const fraction = fractionDigits ? `.${String(rounded % factor).padStart(fractionDigits, '0')}` : ''
  return `${negative && rounded !== 0n ? '-' : ''}${whole}${fraction}`
}

export function calculationText(value: number | null, fractionDigits = 4, keepTrailingZeros = false) {
  if (value === null || !Number.isFinite(value)) return '—'
  const fraction = decimalFraction(value)
  if (!fraction) return '—'
  const text = halfUpFixedText(fraction.numerator, fraction.denominator, fractionDigits)
  return keepTrailingZeros ? text : text.replace(/\.?0+$/, '')
}

export function tubeCalculations(line: BomLineInput, bom: BomDetail | null): Record<TubeCalculationKey, string> {
  const savedLine = line.id ? bom?.sections.flatMap(section => section.lines).find(saved => saved.id === line.id) : undefined
  const plan = pipePlanForBomLine(line, String(bom?.order_quantity || ''), savedLine)
  const length = plan ? Number(plan.tube_cut_length_m) : null
  const unitWeight = plan ? Number(line.length_value) * Number(line.unit_consumption) * 0.464 / 1000 : null
  return {
    total_consumption: plan?.total_consumption || '—', tube_cut_length_m: plan?.tube_cut_length_m || '—',
    branch_count: plan?.branch_count || '—', suggested_purchase_meters: plan?.suggested_purchase_meters || '—',
    long_material_unit_weight_kg: calculationText(length === null ? null : length * 0.464),
    tube_unit_weight_kg: calculationText(unitWeight),
    long_material_total_weight_kg: calculationText(plan && length !== null ? Number(plan.branch_count) * length * 0.464 : null),
  }
}
