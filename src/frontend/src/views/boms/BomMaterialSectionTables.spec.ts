import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { blankLine } from './bomEditorHelpers'
import BomMaterialSectionTables from './BomMaterialSectionTables.vue'

const api = vi.hoisted(() => ({ detail: vi.fn() }))
vi.mock('@/api/materialCatalog', () => ({ fetchMaterialCatalog: api.detail, materialCatalogError: (error: Error) => error.message }))

function open() {
  const lines = [
    { ...blankLine('个'), material_catalog_id: 'off', powder_coating_color: '历史颜色' },
    { ...blankLine('个'), material_catalog_id: 'on', powder_coating_color: '' },
    { ...blankLine('个'), material_catalog_id: 'off', powder_coating_color: '' },
  ]
  const noop = () => {}
  const wrapper = mount(BomMaterialSectionTables, { props: {
    activeSection: { title: '五金件', section_type: 'ACCESSORY', lines },
    isHardwareSection: true, isPlasticSection: false, isAuxiliarySection: false,
    isFabricSection: false, isPackagingSection: false, isCuttingSection: false,
    orderQuantity: '25', canEdit: true, tableFullscreen: false,
    tubeOptionsLoading: false, editorReferenceOptionsLoading: false, catalogRefreshKey: 0,
    tubeCoatingColors: [], toggleTableFullscreen: noop, openLineDrawer: noop,
    removeLine: noop, openLineImageManager: noop, tubeCalculations: () => ({}), formatHardwareColor: String,
    auxiliaryLineHasActiveProduct: () => false, auxiliarySpecificationOptions: () => [], setAuxiliarySpecification: noop,
    auxiliaryColorOptions: () => [], setAuxiliaryColor: noop, auxiliaryMaterialOptions: () => [], setAuxiliaryMaterial: noop,
    fabricSpecificationOptions: () => [], setFabricSpecification: noop, fabricMaterialOptions: () => [], setFabricMaterial: noop,
    fabricColorSnapshot: () => ({}), fabricColorOptions: () => [], setFabricColor: noop,
    fabricWidthOptions: () => [], setFabricWidth: noop, cuttingQuantities: () => ({}), legacyPipeCuttingValues: () => null,
  } as never, global: { plugins: [ElementPlus], stubs: { BomLineImageSummary: true } } })
  return { wrapper, lines }
}

beforeEach(() => {
  api.detail.mockReset().mockImplementation(async (id: string) => ({ data: { id, category_key: 'HARDWARE', spray_enabled: id === 'on' } }))
})

describe('五金分区表格按品名喷塑开关显示下拉', () => {
  it('单件用量合列仍按类型保存原字段，历史行显示横线且订单需求计算不变', async () => {
    const { wrapper } = open()
    const part = { ...blankLine('个'), component_kind: 'SEWN_PART' as const, part_name: '椅面', parts_per_product: 1 }
    const piece = { ...blankLine('片'), component_kind: 'CUT_PIECE' as const, part_name: '座面', parent_part_client_key: part.client_key, pieces_per_part: 2 }
    const legacy = { ...blankLine('套'), part_name: '历史裁片' }
    await wrapper.setProps({ activeSection: { title: '裁剪明细', section_type: 'FABRIC', lines: [part, piece, legacy] },
      isHardwareSection: false, isCuttingSection: true } as never)
    await flushPromises()
    const headers = wrapper.findAll('.el-table__header-wrapper th').map(cell => cell.text())
    expect(headers.filter(text => text === '单件用量')).toHaveLength(1)
    expect(headers).not.toContain('每产品部位数')
    expect(headers).not.toContain('每部位片数')
    const columnIndex = headers.indexOf('单件用量')
    const rows = wrapper.findAll('.el-table__body-wrapper tbody tr')
    expect(rows[0]!.findAll('td')[columnIndex]!.find('input[aria-label="每产品部位数量"]').exists()).toBe(true)
    expect(rows[1]!.findAll('td')[columnIndex]!.find('input[aria-label="每部位用量"]').exists()).toBe(true)
    expect(rows[2]!.findAll('td')[columnIndex]!.text()).toBe('—')
    await wrapper.get('input[aria-label="每产品部位数量"]').setValue('3')
    await wrapper.get('input[aria-label="每部位用量"]').setValue('4')
    expect(part.parts_per_product).toBe('3')
    expect(piece.pieces_per_part).toBe('4')
    expect(piece.parts_per_product).toBe(legacy.parts_per_product)
    expect(part.pieces_per_part).toBe(legacy.pieces_per_part)
    const demandIndex = headers.indexOf('订单需求')
    expect(rows[0]!.findAll('td')[demandIndex]!.text()).toBe('75')
    expect(rows[1]!.findAll('td')[demandIndex]!.text()).toBe('300')
    await wrapper.setProps({ canEdit: false })
    expect(wrapper.get('input[aria-label="每产品部位数量"]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('input[aria-label="每部位用量"]').attributes('disabled')).toBeDefined()
    wrapper.unmount()
  })
  it('部位和裁片单位下拉都使用真实候选并同步所选引用单位，空候选不造选项', async () => {
    const { wrapper } = open()
    const selection = { catalog_version: 'v1', scope: 'BASE' as const, processing_state: 'PROCESSED' as const, attributes: {}, unit_name: '片' }
    const part = { ...blankLine('个'), component_kind: 'SEWN_PART' as const, part_name: '椅面', parts_per_product: 2, material_catalog_id: 'part', material_selection: { ...selection, unit_name: '个' } }
    const piece = { ...blankLine('片'), component_kind: 'CUT_PIECE' as const, part_name: '面片', parent_part_client_key: part.client_key, pieces_per_part: 3, material_catalog_id: 'piece', material_selection: { ...selection } }
    const units = [{ id: 'piece', unit_name: '片' }, { id: 'one', unit_name: '个' }, { id: 'set', unit_name: '套' }]
    await wrapper.setProps({ activeSection: { title: '裁剪明细', section_type: 'FABRIC', lines: [part, piece] },
      isHardwareSection: false, isCuttingSection: true, componentUnits: units } as never)
    await flushPromises()
    const selects = wrapper.findAllComponents({ name: 'ElSelect' }).filter(item => ['部位单位', '裁片单位'].includes(item.props('ariaLabel')))
    expect(selects).toHaveLength(2)
    for (const select of selects) {
      expect(select.findAllComponents({ name: 'ElOption' }).map(item => item.props('value'))).toEqual(['片', '个', '套'])
      select.vm.$emit('change', '套')
    }
    await flushPromises()
    expect(part).toMatchObject({ unit: '套', parts_per_product: 2, material_selection: { unit_name: '套' } })
    expect(piece).toMatchObject({ unit: '套', pieces_per_part: 3, material_selection: { unit_name: '套' } })
    await wrapper.setProps({ componentUnits: [], canEdit: false })
    for (const select of selects) {
      expect(select.props('modelValue')).toBe('套')
      expect(select.props('disabled')).toBe(true)
      expect(select.findAllComponents({ name: 'ElOption' })).toHaveLength(0)
    }
    wrapper.unmount()
  })
  it('部位规格和裁片独立尺寸都能在原表修改，品名旁不恢复裁片属性摘要', async () => {
    const { wrapper } = open()
    const part = { ...blankLine('个'), component_kind: 'SEWN_PART' as const, part_name: '椅面', parts_per_product: 1, specification: '成品尺寸' }
    const piece = { ...blankLine('片'), component_kind: 'CUT_PIECE' as const, part_name: '座面布片', parent_part_client_key: part.client_key,
      pieces_per_part: 1, specification: '裁片尺寸', fabric_source_line_id: 'fabric' }
    await wrapper.setProps({ activeSection: { title: '裁剪明细', section_type: 'FABRIC', lines: [part, piece] },
      isHardwareSection: false, isCuttingSection: true, componentUnits: [{ id: 'piece-unit', unit_name: '个', unit_code: 'PCS' }] } as never)
    await flushPromises()
    expect(wrapper.findAll('.el-table__header-wrapper th').map(cell => cell.text())).toContain('尺寸 / 规格')
    await wrapper.get('input[aria-label="部位规格"]').setValue('50×60cm')
    await wrapper.get('input[aria-label="裁片尺寸或规格"]').setValue('55×65cm')
    expect(part.specification).toBe('50×60cm')
    expect(piece.specification).toBe('55×65cm')
    expect(piece.fabric_source_line_id).toBe('fabric')
    expect(wrapper.find('.component-source-summary').exists()).toBe(false)
    expect(wrapper.findAll('.material-name-trigger').map(item => item.text())).toEqual(['椅面', '座面布片'])
    await wrapper.setProps({ canEdit: false })
    expect(wrapper.get('input[aria-label="部位规格"]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('.material-name-trigger').attributes('disabled')).toBeDefined()
    wrapper.unmount()
  })
  it('部位归属面布可直接选择或清空，不改变单位规格及子裁片来源', async () => {
    const { wrapper } = open()
    const part = { ...blankLine('套'), component_kind: 'SEWN_PART' as const, part_name: '椅面', parts_per_product: 1, material: '错误自身材质', specification: '部位规格' }
    const sources = [
      { ...blankLine('米'), id: 'source-a', part_name: '面布', material: '涤纶', fabric_color_name: '蓝色', fabric_color_code: 'B01', specification: '600D', fabric_width: '150cm' },
      { ...blankLine('米'), part_name: '底布', material: '棉', fabric_color_name: '米白', fabric_color_code: 'W01', specification: '300D', fabric_width: '140cm' },
    ]
    const piece = { ...blankLine('片'), component_kind: 'CUT_PIECE' as const, part_name: '座面', parent_part_client_key: part.client_key, pieces_per_part: 1, fabric_source_line_id: 'source-a' }
    await wrapper.setProps({ activeSection: { title: '裁剪明细', section_type: 'FABRIC', lines: [part, piece] },
      isHardwareSection: false, isCuttingSection: true, componentSources: sources } as never)
    await flushPromises()
    const faceSelect = wrapper.findAllComponents({ name: 'ElSelect' }).find(item => item.props('ariaLabel') === '归属面布')!
    expect(faceSelect.props('modelValue')).toBe('')
    expect(faceSelect.props('clearable')).toBe(true)
    faceSelect.vm.$emit('change', 'source-a')
    await flushPromises()
    expect(part.fabric_source_line_id).toBe('source-a')
    expect(wrapper.findAll('.component-source-cell')[0]!.attributes('title')).toContain('颜色：蓝色；色号：B01')
    faceSelect.vm.$emit('change', sources[1]!.client_key)
    await flushPromises()
    expect(part).toMatchObject({ fabric_source_line_id: null, fabric_source_client_key: sources[1]!.client_key, specification: '部位规格', unit: '套' })
    expect(piece.fabric_source_line_id).toBe('source-a')
    expect(wrapper.findAll('.component-source-cell')[0]!.attributes('title')).toContain('颜色：米白；色号：W01')
    expect(wrapper.find('.component-fabric-sources').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('错误自身材质')
    expect(wrapper.find('.component-source-summary').exists()).toBe(false)
    faceSelect.vm.$emit('change', '')
    await flushPromises()
    expect(part).toMatchObject({ fabric_source_line_id: null, fabric_source_client_key: null, specification: '部位规格', unit: '套' })
    await wrapper.setProps({ canEdit: false })
    expect(faceSelect.props('disabled')).toBe(true)
    wrapper.unmount()
  })
  it('表格手动修改单重立即退出自动计算', async () => {
    const { wrapper, lines } = open()
    const line = lines[0]!
    line.hardware_weight_mode = 'AUTO'
    line.hardware_weight_input = { kind: 'PLAIN_WASHER', material: '钢', specification: 'M6' }
    await flushPromises()
    const cells = wrapper.findAll('.el-table__body-wrapper tr')[0]!.findAll('td')
    const header = wrapper.findAll('.el-table__header-wrapper th').map(cell => cell.text())
    const index = header.findIndex(text => text === '单个材料重量（kg）')
    await cells[index]!.find('input').setValue('0.0095')
    expect(line.hardware_weight_mode).toBe('MANUAL')
    expect(line.unit_material_weight_kg).toBe('0.0095')
    wrapper.unmount()
  })
  it('包材不显示品号列，既有品号数据保留', async () => {
    const { wrapper } = open()
    const line = { ...blankLine('个'), part_name: '纸箱', packaging_material_number: 'PK-001', raw_material: 'PK-OLD', units_per_box: '10' }
    await wrapper.setProps({ activeSection: { title: '包材类', section_type: 'ACCESSORY', lines: [line] },
      isHardwareSection: false, isPackagingSection: true })
    await flushPromises()
    expect(wrapper.findAll('.el-table__header-wrapper th').map(cell => cell.text())).not.toContain('品号')
    expect(wrapper.text()).not.toContain('PK-001')
    expect(line.packaging_material_number).toBe('PK-001')
    wrapper.unmount()
  })
  it('仅面料列显示单耗，切回五金仍显示单个用量', async () => {
    const { wrapper } = open()
    await wrapper.setProps({ activeSection: { title: '面料类', section_type: 'FABRIC', lines: [] }, isFabricSection: true, isHardwareSection: false })
    await flushPromises()
    let headers = wrapper.findAll('.el-table__header-wrapper th').map(cell => cell.text())
    expect(headers).toContain('单耗')
    expect(headers).not.toContain('单个用量')
    await wrapper.setProps({ activeSection: { title: '五金件', section_type: 'ACCESSORY', lines: [] }, isFabricSection: false, isHardwareSection: true })
    await flushPromises()
    headers = wrapper.findAll('.el-table__header-wrapper th').map(cell => cell.text())
    expect(headers).toContain('单个用量')
    expect(headers).not.toContain('单耗')
    wrapper.unmount()
  })
  it('未开启的行只显示原值或横线；已开启但未选颜色的行仍可选择；同品名只读取一次', async () => {
    const { wrapper, lines } = open()
    await flushPromises()
    const rows = wrapper.findAll('.el-table__body-wrapper tbody tr')
    expect(rows).toHaveLength(3)
    expect(rows[0]!.find('.el-select').exists()).toBe(false)
    expect(rows[0]!.text()).toContain('历史颜色')
    expect(rows[1]!.find('.el-select').exists()).toBe(true)
    expect(rows[2]!.find('.el-select').exists()).toBe(false)
    expect(lines[0]!.powder_coating_color).toBe('历史颜色')
    expect(api.detail).toHaveBeenCalledTimes(2)
    wrapper.unmount()
  })

  it('维护关闭刷新后按最新开关更新，读取失败给出重试且不当成未开启', async () => {
    const { wrapper } = open()
    await flushPromises()
    api.detail.mockImplementation(async (id: string) => ({ data: { id, category_key: 'HARDWARE', spray_enabled: true } }))
    await wrapper.setProps({ catalogRefreshKey: 1 })
    await flushPromises()
    expect(wrapper.findAll('.el-table__body-wrapper .el-select')).toHaveLength(3)
    api.detail.mockRejectedValueOnce(new Error('配置暂时不可用'))
    await wrapper.setProps({ catalogRefreshKey: 2 })
    await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('配置读取失败')
    await wrapper.get('[role="alert"] button').trigger('click')
    await flushPromises()
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    expect(wrapper.findAll('.el-table__body-wrapper .el-select')).toHaveLength(3)
    wrapper.unmount()
  })
})
