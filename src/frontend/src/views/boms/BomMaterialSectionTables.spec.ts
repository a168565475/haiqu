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
