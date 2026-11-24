import { describe, expect, it } from 'vitest'
import type { MaterialCatalog, PublicMaterialOptions } from '@/types/materialCatalog'
import { applyErpMatch, applyRecognizedCatalog, buildAiBomPlans, copyLatestErpMatch, fabricUnitIssue, isCuttingSource, latestErpMatch, linkTaskProducts, makeAiBomDrafts, makeAiBomLine, prepareFabricMeterSelection, recognizedSection, rememberCatalog, tubeCalculationKey } from './AiImportBomFormData'

const field = (value: string, status = 'EXTRACTED') => ({ value, status, source_ids: ['sheet:4'], note: '' })
const source = (name: string, section = '') => ({ line_key: name, part_name: field(name), section, material: field('钢'), specification: field('M6'), quantity: field('1200'), unit: field('个'), notes: field('') })
const result = { products: [{ product_key: 'p1', name: field('椅子'), quantity: field('300') }, { product_key: 'p2', name: field('桌子'), quantity: field('600') }],
  boms: [{ product_key: 'p1', lines: [source('螺丝')] }, { product_key: 'p2', lines: [source('扶手')] }] }
const catalog: MaterialCatalog = { id: 'catalog-1', category_key: 'HARDWARE', template_key: 'HARDWARE', name: '螺丝', spray_enabled: false, updated_at: '2026-11-13T12:00:00Z', base_warehouse_id: null, semi_warehouse_id: null, values: [], units: [] }
const options: PublicMaterialOptions = { category_key: 'HARDWARE', template_key: 'HARDWARE', scope: 'BASE',
  fields: [{ key: 'material', label: '材质', kind: 'text', source: 'public', manage_url: '' }, { key: 'specification', label: '规格', kind: 'text', source: 'public', manage_url: '' }],
  values: [{ id: 'm1', scope: 'BASE', field_key: 'material', value: '钢', parent_id: null }, { id: 's1', scope: 'BASE', field_key: 'specification', value: 'M6', parent_id: null }], units: [{ id: 'unit-1', unit_name: '个' }] }

describe('AI BOM 与 ERP 对应', () => {
  const verifiedMatch = () => ({ status: 'MATCHED', note: '已核对真实材料属性', section: '五金件', catalog,
    selection: { catalog_version: catalog.updated_at, scope: 'BASE', processing_state: 'RAW', attributes: { material: '钢', specification: 'M6' }, unit_id: 'unit-1', unit_name: '个' } })

  it('最新对应只能按产品和行键唯一补入元数据，不重建草稿或覆盖人工材料身份', () => {
    const line = makeAiBomLine(source('螺丝'), 0)
    line.unit_consumption = '人工单耗'; line.ai_original_text = '人工核对原文'; line.fabric_source_client_key = '人工来源'
    const input = { boms: [{ product_key: 'p1', lines: [{ line_key: '螺丝', erp_match: verifiedMatch() }] }] }
    const before = JSON.parse(JSON.stringify(line))
    expect(copyLatestErpMatch(line, input, 'p1')).toBe(true)
    expect(line).toEqual({ ...before, ai_source: { ...before.ai_source, erp_match: verifiedMatch() } })
    expect(latestErpMatch(input, 'p2', '螺丝')).toBeNull()
    expect(latestErpMatch({ boms: [input.boms[0], input.boms[0]] }, 'p1', '螺丝')).toBeNull()
    expect(latestErpMatch({ boms: [{ product_key: 'p1', lines: [...input.boms[0]!.lines, ...input.boms[0]!.lines] }] }, 'p1', '螺丝')).toBeNull()
    line.material_catalog_id = '人工身份'
    expect(copyLatestErpMatch(line, { boms: [{ product_key: 'p1', lines: [{ line_key: '螺丝', erp_match: { status: 'REFERENCE' } }] }] }, 'p1')).toBe(false)
    expect(line.ai_source.erp_match).toEqual(verifiedMatch())
  })

  it('优先承接后端已核验身份，保留原表品名、原文和制造用量', () => {
    const line = makeAiBomLine({ ...source('表中螺丝'), raw_content: field('原始完整行'),
      erp_fields: { unit_consumption: field('4'), length_value: field('540'), tube_cut_piece_count: field('11'), source_raw_bar_length_m: field('5.99'), unit_material_weight_kg: field('0.00352') }, erp_match: verifiedMatch() }, 0)
    const originalText = line.ai_original_text
    line.ai_pending = ['ERP材料：旧提示', 'ERP属性：旧提示', '原表字段冲突：备注']
    expect(applyErpMatch(line)).toBe('五金件')
    expect(line).toMatchObject({ material_catalog_id: catalog.id, part_name: '表中螺丝', unit_consumption: '4', length_value: '540', tube_cut_piece_count: '11', source_raw_bar_length_m: '5.99', unit_material_weight_kg: '0.00352' })
    expect(line.ai_original_text).toBe(originalText)
    expect(line.ai_source.part_name).toEqual(field('表中螺丝'))
    expect(line.ai_pending).toEqual(['原表字段冲突：备注'])
  })

  it('已有同一管材身份仍可规范原喷塑颜色，空powder可补，完整要求留备注且不重复', () => {
    const line = makeAiBomLine({ ...source('交叉管', '管材类'), erp_fields: { tube_coating_color: field('黑色亮光喷塑'), unit_consumption: field('6') } }, 0)
    line.material_catalog_id = 'tube-id'
    line.material_selection = { catalog_version: 'manual-v1', scope: 'BASE', processing_state: 'RAW', attributes: { material: '人工确认的铁', section_size: '16' }, unit_id: 'unit-bar' }
    line.notes = '保留人工备注'
    const identity = JSON.parse(JSON.stringify(line.material_selection)), originalText = line.ai_original_text
    const erpMatch = { ...verifiedMatch(), section: '管材类', catalog: { ...catalog, id: 'tube-id', category_key: 'TUBE', template_key: 'TUBE', spray_enabled: true },
      field_updates: { tube_coating_color: '黑色亮光', powder_coating_color: '黑色亮光', notes: '不应覆盖', unit_consumption: '999' } }
    const input = { boms: [{ product_key: 'p1', lines: [{ line_key: '交叉管', erp_match: erpMatch }] }] }
    expect(copyLatestErpMatch(line, input, 'p1')).toBe(true)
    expect(applyErpMatch(line)).toBe('')
    expect(line).toMatchObject({ material_catalog_id: 'tube-id', material_selection: identity, tube_coating_color: '黑色亮光', powder_coating_color: '黑色亮光', unit_consumption: '6', ai_original_text: originalText })
    expect(line.notes).toBe('保留人工备注\n原表喷塑要求：黑色亮光喷塑')
    applyErpMatch(line)
    expect(line.notes).toBe('保留人工备注\n原表喷塑要求：黑色亮光喷塑')
  })

  it('人工改过颜色、不同材料身份或非MATCHED时不采用颜色建议', () => {
    const erpMatch = { ...verifiedMatch(), section: '管材类', catalog: { ...catalog, id: 'tube-id', category_key: 'TUBE', template_key: 'TUBE', spray_enabled: true }, field_updates: { tube_coating_color: '黑色', powder_coating_color: '黑色' } }
    const line = makeAiBomLine({ ...source('交叉管', '管材类'), erp_fields: { tube_coating_color: field('黑色亮光喷塑'), powder_coating_color: field('黑色亮光喷塑') }, erp_match: erpMatch }, 0)
    line.material_catalog_id = 'tube-id'; line.tube_coating_color = '人工红色'; line.powder_coating_color = '人工灰色'
    applyErpMatch(line)
    expect(line).toMatchObject({ tube_coating_color: '人工红色', powder_coating_color: '人工灰色', notes: '' })
    line.tube_coating_color = line.powder_coating_color = '黑色亮光喷塑'; line.material_catalog_id = 'other-id'
    applyErpMatch(line)
    expect(line.tube_coating_color).toBe('黑色亮光喷塑')
    line.material_catalog_id = 'tube-id'; line.ai_source.erp_match = { ...erpMatch, status: 'PARTIAL' }
    applyErpMatch(line)
    expect(line.powder_coating_color).toBe('黑色亮光喷塑')
  })

  it('五金仅规范powder颜色，不允许用field_updates改其他字段', () => {
    const line = makeAiBomLine({ ...source('螺丝'), erp_fields: { powder_coating_color: field('黑色亮光喷塑'), tube_coating_color: field('管材原色') },
      erp_match: { ...verifiedMatch(), catalog: { ...catalog, spray_enabled: true }, field_updates: { powder_coating_color: '黑色亮光', tube_coating_color: '不应填写', material_catalog_id: 'forged' } } }, 0)
    expect(applyErpMatch(line)).toBe('五金件')
    expect(line.powder_coating_color).toBe('黑色亮光')
    expect(line.tube_coating_color).toBe('管材原色')
    expect(line.material_catalog_id).toBe(catalog.id)
  })

  it('后端部分匹配、类别不符和已有人工身份不覆盖识别字段', () => {
    const partial = makeAiBomLine({ ...source('螺丝'), erp_match: { ...verifiedMatch(), status: 'PARTIAL', note: '尺寸有两个候选' } }, 0)
    expect(applyErpMatch(partial)).toBe('')
    expect(partial.specification).toBe('M6')
    expect(partial.material_catalog_id).toBeUndefined()
    expect(partial.ai_pending).toContain('ERP对应：尺寸有两个候选')
    const wrongSection = makeAiBomLine({ ...source('螺丝'), erp_match: { ...verifiedMatch(), section: '塑料件类' } }, 0)
    expect(applyErpMatch(wrongSection)).toBe('')
    expect(wrongSection.material_catalog_id).toBeUndefined()
    const manual = makeAiBomLine({ ...source('螺丝'), erp_match: verifiedMatch() }, 0)
    manual.material_catalog_id = 'manual-catalog'
    manual.specification = '人工选定的M8'
    expect(applyErpMatch(manual)).toBe('')
    expect(manual.material_catalog_id).toBe('manual-catalog')
    expect(manual.specification).toBe('人工选定的M8')
  })

  it('裁剪承接已核验工艺，缺少裁剪工艺仍待核对', () => {
    const cuttingCatalog = { ...catalog, id: 'cutting-1', category_key: 'FABRIC_SEMI', template_key: 'CUTTING', name: '布面' }
    const erpMatch = { ...verifiedMatch(), section: '裁剪明细', catalog: cuttingCatalog,
      selection: { ...verifiedMatch().selection, processing_state: 'PROCESSED', semi_kind: 'CUTTING', completed_craft: { id: 'craft-1', craft_type: 'INTERNAL', code: 'CUT' } } }
    const line = makeAiBomLine({ ...source('椅面', '裁剪明细'), erp_match: erpMatch, erp_fields: { cutting_pieces_per_set: field('2'), cutting_sets_per_product: field('1') } }, 0)
    line.fabric_source_client_key = 'fabric-line'
    expect(applyRecognizedCatalog(line, cuttingCatalog, options)).toBe(true)
    expect(line.material_selection).toMatchObject({ processing_state: 'PROCESSED', semi_kind: 'CUTTING', completed_craft: { id: 'craft-1' } })
    expect(line).toMatchObject({ part_name: '椅面', fabric_source_client_key: 'fabric-line', cutting_pieces_per_set: '2', cutting_sets_per_product: '1' })
    const incomplete = makeAiBomLine({ ...source('椅面', '裁剪明细'), erp_match: { ...erpMatch, selection: { ...erpMatch.selection, completed_craft: null } } }, 0)
    expect(applyErpMatch(incomplete)).toBe('')
    expect(incomplete.material_catalog_id).toBeUndefined()
  })

  it('汇总说明保留原文及重开内容，不进入待选材料或提交数据', () => {
    const input = { products: result.products.slice(0, 1), boms: [{ product_key: 'p1', lines: [
      { ...source('螺丝', '五金件'), erp_match: verifiedMatch() },
      { ...source('面料总计', '面料类'), raw_content: field('面料共600.8米，已包含各原料行'), erp_match: { status: 'REFERENCE', note: '汇总行不重复采购' } },
    ] }] }
    const drafts = makeAiBomDrafts(input, null)
    expect(drafts[0]!.reference_lines).toHaveLength(1)
    expect(drafts[0]!.pending_lines).toHaveLength(0)
    expect(drafts[0]!.sections.flatMap(section => section.lines)).toHaveLength(1)
    const restored = makeAiBomDrafts(input, drafts)
    expect(restored[0]!.reference_lines![0]!.ai_original_text).toContain('面料共600.8米')
    const products = [{ id: 'task-p1', client_key: 'p1' }]
    linkTaskProducts(restored, products)
    const plans = buildAiBomPlans(restored, products)
    expect(JSON.stringify(plans)).not.toContain('面料总计')
    expect(JSON.stringify(plans)).toContain(catalog.id)
  })

  it('保留所有产品和BOM，未知部件留待选且不把数量当单耗', () => {
    const drafts = makeAiBomDrafts(result, null)
    expect(drafts).toHaveLength(2)
    expect(drafts[0]!.sections.find(item => item.title === '五金件')!.lines).toHaveLength(1)
    expect(drafts[1]!.pending_lines[0]!.part_name).toBe('扶手')
    expect(drafts[1]!.sections.find(item => item.title === '辅料类')!.lines).toHaveLength(0)
    const line = drafts[0]!.sections.find(item => item.title === '五金件')!.lines[0]!
    expect(line.unit_consumption).toBe('')
    expect(line.material_quantity).toBeUndefined()
    expect(line.ai_original_text).toContain('原表数量：1200')
  })

  it('型材同义词可归管材，但椅面和扶手不能猜分类', () => {
    expect(recognizedSection(source('前脚', '型材'))).toBe('管材类')
    expect(recognizedSection(source('椅面'))).toBe('')
    expect(recognizedSection(source('扶手'))).toBe('')
    expect(recognizedSection({ ...source('扶手'), material: field('PP') })).toBe('塑料件类')
    expect(recognizedSection({ ...source('前脚'), specification: field('圆管 直径19 壁厚0.8') })).toBe('管材类')
  })

  it('只填写无冲突的ERP字段，未知字段及quantity不能注入身份', () => {
    const line = makeAiBomLine({ ...source('钢管'), erp_fields: { unit_consumption: field('2'), tube_thickness: field('0.8', 'CONFLICT'), material_catalog_id: field('forged') } }, 0)
    expect(line.unit_consumption).toBe('2')
    expect(line.tube_thickness).toBe('')
    expect(line.material_catalog_id).toBeUndefined()
    expect(line.ai_pending[0]).toContain('厚度')
    expect(line.ai_original_text).toContain('0.8（冲突）')
  })

  it('产品只能按唯一client_key对应，不回退到第一项', () => {
    const drafts = makeAiBomDrafts(result, null)
    linkTaskProducts(drafts, [{ id: 'wrong', client_key: 'different' }, { id: 'right', client_key: 'p2' }])
    expect(drafts[0]!.production_task_product_id).toBe('')
    expect(drafts[1]!.production_task_product_id).toBe('right')
    linkTaskProducts(drafts, [{ id: 'a', client_key: 'p1' }, { id: 'b', client_key: 'p1' }])
    expect(drafts[0]!.production_task_product_id).toBe('')
  })

  it('真实目录和公共属性匹配后用新目录身份，绝不填旧原料ID', () => {
    const line = makeAiBomLine(source('螺丝'), 0)
    expect(applyRecognizedCatalog(line, catalog, options)).toBe(true)
    expect(line.material_catalog_id).toBe('catalog-1')
    expect(line.material_selection).toMatchObject({ catalog_version: catalog.updated_at, attributes: { material: '钢', specification: 'M6' }, unit_id: 'unit-1' })
    expect(line.source_raw_material_id).toBeNull()
    expect(line.unit).toBe('个')
  })

  it('规格不存在公共候选时不伪造目录属性或身份', () => {
    const line = makeAiBomLine({ ...source('螺丝'), specification: field('M7') }, 0)
    expect(applyRecognizedCatalog(line, catalog, options)).toBe(false)
    expect(line.material_catalog_id).toBeUndefined()
    expect(line.specification).toBe('M7')
  })

  it('单位别名只在真实候选唯一时对应，存在个和件两种候选时不猜', () => {
    const line = makeAiBomLine({ ...source('螺丝'), unit: field('PCS') }, 0)
    expect(applyRecognizedCatalog(line, catalog, options)).toBe(true)
    expect(line.unit).toBe('个')
    const ambiguous = makeAiBomLine({ ...source('螺丝'), unit: field('PCS') }, 0)
    expect(applyRecognizedCatalog(ambiguous, catalog, { ...options, units: [...options.units, { id: 'u2', unit_name: '件' }] })).toBe(false)
    expect(ambiguous.unit).toBe('PCS')
  })

  it('泛称规格不同时冒充尺寸和螺纹，明确属性只按自身字段对应', () => {
    const expanded: PublicMaterialOptions = { ...options,
      fields: [...options.fields, ...['size', 'thread'].map(key => ({ key, label: key, kind: 'text' as const, source: 'public', manage_url: '' }))],
      values: [...options.values, ...['size', 'thread'].map(key => ({ id: key, field_key: key, value: 'M6', scope: 'BASE' as const, parent_id: null }))] }
    const generic = makeAiBomLine(source('螺丝'), 0)
    expect(applyRecognizedCatalog(generic, catalog, expanded)).toBe(true)
    expect(generic.material_selection?.attributes).toEqual({ material: '钢', specification: 'M6' })
    const explicit = makeAiBomLine({ ...source('螺丝'), erp_fields: { catalog_thread: field('M6') } }, 0)
    expect(applyRecognizedCatalog(explicit, catalog, expanded)).toBe(true)
    expect(explicit.material_selection?.attributes).toEqual({ material: '钢', thread: 'M6' })
    expect(explicit).not.toHaveProperty('catalog_thread')
  })

  it('包材泛称规格同时匹配尺寸和型号时保持待选', () => {
    const packaging = { ...catalog, category_key: 'PACKAGING', template_key: 'CARTON' }
    const candidates: PublicMaterialOptions = { ...options, category_key: 'PACKAGING', template_key: 'CARTON',
      fields: ['size', 'model'].map(key => ({ key, label: key, kind: 'text', source: 'public', manage_url: '' })),
      values: ['size', 'model'].map(key => ({ id: key, field_key: key, value: 'M6', scope: 'BASE', parent_id: null })) }
    expect(applyRecognizedCatalog(makeAiBomLine(source('纸箱'), 0), packaging, candidates)).toBe(false)
    const explicit = makeAiBomLine({ ...source('纸箱'), erp_fields: { catalog_size: field('M6') } }, 0)
    expect(applyRecognizedCatalog(explicit, packaging, candidates)).toBe(true)
    expect(explicit.material_selection?.attributes).toEqual({ size: 'M6' })
  })

  it('辅料宽度和厚度来自明确catalog属性，不借用面料或管材字段', () => {
    const auxiliary = { ...catalog, category_key: 'AUXILIARY', template_key: 'COTTON' }
    const candidates: PublicMaterialOptions = { ...options, category_key: 'AUXILIARY', template_key: 'COTTON',
      fields: ['width', 'thickness'].map(key => ({ key, label: key, kind: 'text', source: 'public', manage_url: '' })),
      values: [{ id: 'w', field_key: 'width', value: '1.5', scope: 'BASE', parent_id: null }, { id: 't', field_key: 'thickness', value: '2', scope: 'BASE', parent_id: null }] }
    const legacy = makeAiBomLine({ ...source('喷胶棉'), erp_fields: { fabric_width: field('1.5'), tube_thickness: field('2') } }, 0)
    expect(applyRecognizedCatalog(legacy, auxiliary, candidates)).toBe(false)
    const explicit = makeAiBomLine({ ...source('喷胶棉'), erp_fields: { catalog_width: field('1.5'), catalog_thickness: field('2') } }, 0)
    expect(applyRecognizedCatalog(explicit, auxiliary, candidates)).toBe(true)
    expect(explicit.material_selection?.attributes).toEqual({ width: '1.5', thickness: '2' })
  })

  it.each([
    ['FABRIC', 'FABRIC', { material: '涤纶', fabric_spec: '300*300D', width: '1.5', color: '灰', gram_weight: '220', finish: 'PE' }],
    ['PLASTIC', 'PLASTIC', { material: 'PP', specification: '扶手', tube_size: 'Φ22开口/配Φ16孔' }],
    ['PACKAGING', 'CARTON', { size: '101*32*30cm', layers: '五层', box_type: '半盖箱', printing: '客稿A' }],
    ['PACKAGING', 'BAG', { size: '70*50cm', thickness: '0.05mm', bag_type: '平口', printing: '客稿B' }],
    ['AUXILIARY', 'COTTON', { width: '1.5', thickness: '20mm', gram_weight: '180' }],
  ] as const)('将%s/%s的明确目录细项逐项匹配，不留在无结构备注中', (category, template, attributes) => {
    const selectedCatalog = { ...catalog, category_key: category, template_key: template }
    const candidates: PublicMaterialOptions = { category_key: category, template_key: template, scope: 'BASE',
      fields: Object.keys(attributes).map(key => ({ key, label: key, kind: 'text', source: 'public', manage_url: '' })),
      values: Object.entries(attributes).map(([key, value]) => ({ id: key, field_key: key, value, scope: 'BASE', parent_id: null })),
      units: [{ id: 'u1', unit_name: category === 'FABRIC' ? '米' : '个' }] }
    const attrs = attributes as Record<string, string>
    const recognized = Object.entries(attrs).filter(([key]) => !['material', 'color', 'specification'].includes(key)).map(([key, value]) => ({ field: `catalog_${key}`, value: field(value) }))
    if (category === 'FABRIC') recognized.push({ field: 'fabric_color_name', value: field('灰') })
    const line = makeAiBomLine({ ...source('材料'), material: field(attrs.material || ''), specification: field(attrs.specification || ''), unit: field(category === 'FABRIC' ? '米' : '个'), erp_fields: recognized }, 0)
    expect(applyRecognizedCatalog(line, selectedCatalog, candidates)).toBe(true)
    expect(line.material_selection?.attributes).toEqual(attributes)
    expect(line.ai_original_text).toContain(Object.values(attributes).at(-1))
  })

  it('已识别细项不在公共候选时留待选，不静默丢弃涂层并当作匹配成功', () => {
    const line = makeAiBomLine({ ...source('螺丝'), erp_fields: { catalog_thread: field('M7') } }, 0)
    const candidates: PublicMaterialOptions = { ...options, fields: [...options.fields, { key: 'thread', label: '螺纹规格', kind: 'text', source: 'public', manage_url: '' }] }
    expect(applyRecognizedCatalog(line, catalog, candidates)).toBe(false)
    expect(line.ai_pending.join('；')).toContain('螺纹规格未匹配')
    expect(line.material_catalog_id).toBeUndefined()
    expect(line.ai_original_text).toContain('M7')
  })

  it('管材原重量面积只留原文，五金明确单件重量继续预填', () => {
    const pipe = makeAiBomLine({ ...source('钢管', '管材类'), erp_fields: { coating_unit_area_sqm: field('0.2880636'), purchase_unit_weight_kg: field('1.32'), long_material_unit_weight_kg: field('1.998') } }, 0)
    expect(pipe.coating_unit_area_sqm).toBe('')
    expect(pipe.purchase_unit_weight_kg).toBe('')
    expect(pipe.long_material_unit_weight_kg).toBe('')
    expect(pipe.ai_original_text).toContain('0.2880636')
    const hardware = makeAiBomLine({ ...source('螺丝'), erp_fields: [{ field: 'unit_material_weight_kg', value: field('0.00143') }] }, 0)
    expect(hardware.unit_material_weight_kg).toBe('0.00143')
    const unreadable = makeAiBomLine({ ...source('螺丝'), erp_fields: { unit_material_weight_kg: field('模糊', 'UNREADABLE') } }, 0)
    expect(unreadable.unit_material_weight_kg).toBe('')
    expect(unreadable.ai_pending.join('；')).toContain('未读清')
  })

  it('同一原料父行可关联多个裁片，不复制原料用量或跨BOM连线', () => {
    const parent = { ...source('面料', '面料类'), line_key: 'material', unit: field('米'), erp_fields: { unit_consumption: field('0.4') } }
    const child = { ...source('右布面', '裁剪明细'), line_key: 'right', source_line_key: 'material', erp_fields: { cutting_pieces_per_set: field('2'), cutting_sets_per_product: field('1') } }
    const drafts = makeAiBomDrafts({ products: result.products, boms: [
      { product_key: 'p1', lines: [parent, child, { ...child, line_key: 'left' }] },
      { product_key: 'p2', lines: [child] },
    ] }, null)
    const material = drafts[0]!.sections.find(section => section.title === '面料类')!.lines
    const pieces = drafts[0]!.sections.find(section => section.title === '裁剪明细')!.lines
    expect(material).toHaveLength(1)
    expect(material[0]!.unit_consumption).toBe('0.4')
    expect(pieces.map(line => line.fabric_source_client_key)).toEqual([material[0]!.client_key, material[0]!.client_key])
    expect(drafts[1]!.sections.find(section => section.title === '裁剪明细')!.lines[0]!.fabric_source_client_key).toBeUndefined()
  })

  it('包材明确每成品单耗精确转成用量基数，不能近似或把总量当单耗', () => {
    const input = { ...source('纸箱', '包材类'), unit: field('箱'), quantity_basis: 'UNIT_CONSUMPTION', quantity: field('0.5') }
    expect(makeAiBomLine(input, 0).units_per_box).toBe('2')
    const repeating = makeAiBomLine({ ...input, quantity: field('0.3') }, 0)
    expect(repeating.units_per_box).toBe('')
    expect(repeating.ai_pending.join('；')).toContain('无法精确换算')
    expect(makeAiBomLine({ ...input, quantity_basis: 'PROCUREMENT_TOTAL' }, 0).units_per_box).toBe('')
  })

  it('棉类来源须真实目录类别且为米制原料，不按名称或PCS猜为耗米', () => {
    const line = makeAiBomLine(source('喷胶棉'), 0)
    line.material_catalog_id = 'cotton'
    line.material_selection = { catalog_version: 'v1', scope: 'BASE', processing_state: 'RAW', attributes: { width: '1.5' }, unit_name: '米' }
    line.unit = '米'
    expect(isCuttingSource(line)).toBe(false)
    rememberCatalog(line, { ...catalog, id: 'cotton', updated_at: 'v1', category_key: 'AUXILIARY', template_key: 'COTTON' })
    expect(isCuttingSource(line)).toBe(true)
    line.unit = 'PCS'
    expect(isCuttingSource(line)).toBe(false)
    line.unit = '米'
    rememberCatalog(line, { ...catalog, id: 'cotton', updated_at: 'v1', category_key: 'AUXILIARY', template_key: 'TAPE' })
    expect(isCuttingSource(line)).toBe(false)
  })

  it('面料非米或未知单耗单位不自动换算，人工选米时先清空待核对单耗', () => {
    const line = makeAiBomLine({ ...source('面料'), unit: field('码'), erp_fields: { unit_consumption: field('0.8') } }, 0)
    const fabric = { ...catalog, category_key: 'FABRIC', template_key: 'FABRIC' }
    expect(applyRecognizedCatalog(line, fabric, options)).toBe(false)
    expect(line.unit).toBe('码')
    expect(line.unit_consumption).toBe('0.8')
    expect(prepareFabricMeterSelection(line)).toContain('米制单耗')
    expect(line.unit_consumption).toBe('')
    expect(line.ai_original_text).toContain('单耗：0.8')
    expect(line.ai_pending.join('；')).toContain('原表单位为码')
    line.unit = ''
    line.unit_consumption = '0.8'
    expect(fabricUnitIssue(line)).toContain('单位未明确')
  })

  it('恢复预览保留原文调整和待选项，不重复生成空管材', () => {
    const drafts = makeAiBomDrafts(result, null)
    drafts[1]!.pending_lines[0]!.ai_original_text = '用户已调整原文'
    const restored = makeAiBomDrafts(result, drafts)
    expect(restored[1]!.pending_lines[0]!.ai_original_text).toBe('用户已调整原文')
    expect(restored[0]!.sections[0]!.lines).toHaveLength(0)
  })

  it('新原文不拼入机器来源编号，整行原文和证据对象保留', () => {
    const sourceId = `src_${'a'.repeat(64)}`
    const input = { ...source('螺丝'), part_name: { ...field('螺丝'), source_ids: [sourceId] }, raw_content: field('整行原文 [厂家备注]：M6螺丝') }
    const line = makeAiBomLine(input, 0)
    expect(line.ai_original_text).toContain('整行原文 [厂家备注]：M6螺丝')
    expect(line.ai_original_text).not.toContain(sourceId)
    expect(line.ai_source).toEqual(input)
  })

  it('恢复只剔除旧机器来源块，保留人工改动、普通括号和证据', () => {
    const sourceId = `src_${'a'.repeat(64)}`
    const anotherId = `src_${'b'.repeat(64)}`
    const drafts = makeAiBomDrafts(result, null)
    const line = drafts[1]!.pending_lines[0]!
    line.ai_original_text = `人工修改品名 [${sourceId}、${anotherId}]\n规格已核对 [手工备注]\n保留 [src_short]\n保留 [${sourceId} 用户说明]`
    line.ai_source = { part_name: { ...field('扶手'), source_ids: [sourceId] } }
    const restored = makeAiBomDrafts(result, drafts)[1]!.pending_lines[0]!
    expect(restored.ai_original_text).toBe(`人工修改品名\n规格已核对 [手工备注]\n保留 [src_short]\n保留 [${sourceId} 用户说明]`)
    expect(restored.ai_source).toEqual(line.ai_source)
    expect(line.ai_original_text).toContain(`[${sourceId}、${anotherId}]`)
  })

  it('构建计划拦截待选行、失效产品，并剔除独立总量及旧身份', () => {
    const drafts = makeAiBomDrafts({ ...result, boms: [result.boms[0]] }, null)
    const draft = drafts[0]!
    const line = draft.sections.find(item => item.title === '五金件')!.lines[0]!
    applyRecognizedCatalog(line, catalog, options)
    expect(() => buildAiBomPlans(drafts, [{ id: 'task-p', client_key: 'p1' }])).toThrow('请先选择')
    draft.production_task_product_id = 'task-p'
    line.material_quantity = '1200'
    line.cutting_pieces_per_set = ''
    line.cutting_sets_per_product = ''
    line.fabric_meters_per_set = '1.2'
    line.fabric_meters_per_piece = '0.5'
    const plans = buildAiBomPlans(drafts, [{ id: 'task-p', client_key: 'p1' }])
    expect(plans).toHaveLength(1)
    expect(JSON.stringify(plans)).not.toContain('material_quantity')
    expect(JSON.stringify(plans)).not.toContain('source_raw_material_id')
    expect(JSON.stringify(plans)).not.toContain('ai_original_text')
    expect(JSON.stringify(plans)).not.toContain('cutting_pieces_per_set')
    expect(JSON.stringify(plans)).not.toContain('fabric_meters_per_set')
    expect(JSON.stringify(plans)).not.toContain('fabric_meters_per_piece')
    draft.pending_lines.push(makeAiBomLine(source('未知'), 1))
    expect(() => buildAiBomPlans(drafts, [{ id: 'task-p' }])).toThrow('未选择分区')
  })

  it('裁剪必须有本BOM已对应的米制来源面料和有效工艺身份', () => {
    const drafts = makeAiBomDrafts({ ...result, boms: [result.boms[0]] }, null)
    const draft = drafts[0]!
    draft.production_task_product_id = 'task-p'
    const fabric = draft.sections.find(item => item.title === '五金件')!.lines.pop()!
    fabric.unit = '米'
    fabric.material_catalog_id = 'fabric-catalog'
    fabric.material_selection = { catalog_version: 'v1', scope: 'BASE', processing_state: 'RAW', attributes: { fabric_spec: '600D' }, unit_name: '米' }
    rememberCatalog(fabric, { ...catalog, id: 'fabric-catalog', updated_at: 'v1', category_key: 'FABRIC', template_key: 'FABRIC' })
    draft.sections.find(item => item.title === '面料类')!.lines.push(fabric)
    const cutting = makeAiBomLine(source('椅面'), 1)
    cutting.material_catalog_id = 'cutting-catalog'
    cutting.material_selection = { catalog_version: 'v1', scope: 'BASE', processing_state: 'PROCESSED', semi_kind: 'CUTTING', attributes: { specification: '600D' }, unit_name: '套' }
    draft.sections.find(item => item.title === '裁剪明细')!.lines.push(cutting)
    expect(() => buildAiBomPlans(drafts, [{ id: 'task-p' }])).toThrow('米制来源面料')
    cutting.fabric_source_client_key = fabric.client_key
    expect(() => buildAiBomPlans(drafts, [{ id: 'task-p' }])).toThrow('有效裁剪工艺')
    cutting.material_selection.completed_craft = { id: 'real-craft-response-id', craft_type: 'INTERNAL', code: 'CUTTING' }
    expect(buildAiBomPlans(drafts, [{ id: 'task-p' }])).toHaveLength(1)
    cutting.cutting_pieces_per_set = '2'
    expect(() => buildAiBomPlans(drafts, [{ id: 'task-p' }])).toThrow('请同时填写')
    cutting.cutting_sets_per_product = '1'
    expect(buildAiBomPlans(drafts, [{ id: 'task-p' }])).toHaveLength(1)
  })

  it('长料保留三位小数，超精度或规格变化未重算时拦截，不自动舍入', () => {
    const drafts = makeAiBomDrafts({ ...result, boms: [result.boms[0]] }, null)
    const draft = drafts[0]!
    draft.production_task_product_id = 'task-p'
    const line = draft.sections.find(item => item.title === '五金件')!.lines.pop()!
    applyRecognizedCatalog(line, catalog, options)
    draft.sections.find(item => item.title === '管材类')!.lines.push(line)
    line.source_raw_bar_length_m = '6.305'
    line.ai_original_text = '原材料长度6.305m'
    line.tube_calculation_preview = { formula_version: 'v1', coating_unit_area_sqm: '0.05', purchase_unit_weight_kg: '0.22', long_material_unit_weight_kg: '1.998' }
    line.ai_tube_formula_key = tubeCalculationKey(line)
    expect(buildAiBomPlans(drafts, [{ id: 'task-p' }])).toHaveLength(1)
    expect(line.source_raw_bar_length_m).toBe('6.305')
    line.source_raw_bar_length_m = '6.3051'
    expect(() => buildAiBomPlans(drafts, [{ id: 'task-p' }])).toThrow('最多保留 3 位小数')
    line.source_raw_bar_length_m = '6.30'
    expect(() => buildAiBomPlans(drafts, [{ id: 'task-p' }])).toThrow('完成 ERP 管材公式计算')
    line.ai_tube_formula_key = tubeCalculationKey(line)
    expect(buildAiBomPlans(drafts, [{ id: 'task-p' }])).toHaveLength(1)
    expect(line.ai_original_text).toBe('原材料长度6.305m')
  })
})
