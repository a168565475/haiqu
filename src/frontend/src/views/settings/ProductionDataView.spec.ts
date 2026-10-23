import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { createPinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import ProductionDataView from './ProductionDataView.vue'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'

const fixtures = vi.hoisted(() => {
  const granted = new Set<string>()
  const category = {
    id: 'category-1', item_type: 'FINISHED', item_type_label: '成品', category_name: '成品帐篷',
    reference_count: 1, status: 'ACTIVE', sort_order: 1, description: '',
    created_at: '2026-08-31T00:00:00Z', updated_at: '2026-08-31T00:00:00Z', archived_at: null,
  }
  const unit = {
    id: 'unit-1', unit_code: '01', unit_name: '个', status: 'ACTIVE', sort_order: 12,
    description: '', created_at: '2026-08-31T00:00:00Z', updated_at: '2026-08-31T00:00:00Z', archived_at: null,
  }
  const color = {
    id: 'color-1', color_card: 'PANTONE', color_code: '7771 C', color_name: '灰绿色',
    image_url: '/api/v1/reference-data/product-colors/color-1/image/', has_image: true,
    status: 'ACTIVE', sort_order: 1, description: '', created_at: '2026-08-31T00:00:00Z',
    updated_at: '2026-08-31T00:00:00Z', archived_at: null,
  }
  const fabricMaterial = {
    id: 'fabric-material-1', material_name: '加密尼龙', status: 'ACTIVE', sort_order: 1,
    inventory_raw_material: null, inventory_material_number: null, inventory_material_name: null,
    inventory_material_unit: null,
    description: '', created_at: '2026-08-31T00:00:00Z', updated_at: '2026-08-31T00:00:00Z', archived_at: null,
  }
  const fabricSpecification = {
    id: 'fabric-specification-1', specification_name: '190D', status: 'ACTIVE', sort_order: 1,
    description: '', created_at: '2026-08-31T00:00:00Z', updated_at: '2026-08-31T00:00:00Z', archived_at: null,
  }
  const fabricWidth = {
    id: 'fabric-width-1', width_value: '1.7', status: 'ACTIVE', sort_order: 1,
    description: '', created_at: '2026-08-31T00:00:00Z', updated_at: '2026-08-31T00:00:00Z', archived_at: null,
  }
  const tubeProductName = {
    id: 'tube-product-name-1', product_name: '上下短脚管', status: 'ACTIVE', sort_order: 1,
    description: '', created_at: '2026-08-31T00:00:00Z', updated_at: '2026-08-31T00:00:00Z', archived_at: null,
  }
  const tubeThickness = {
    id: 'tube-thickness-1', thickness_value: '2.0', status: 'ACTIVE', sort_order: 1,
    description: '', created_at: '2026-08-31T00:00:00Z', updated_at: '2026-08-31T00:00:00Z', archived_at: null,
  }
  const tubeDiameter = {
    id: 'tube-diameter-1', diameter_value: '25*15', status: 'ACTIVE', sort_order: 1,
    description: '', created_at: '2026-08-31T00:00:00Z', updated_at: '2026-08-31T00:00:00Z', archived_at: null,
  }
  const tubeMaterial = {
    id: 'tube-material-1', material_name: '铁-中光', status: 'ACTIVE', sort_order: 1,
    description: '', created_at: '2026-08-31T00:00:00Z', updated_at: '2026-08-31T00:00:00Z', archived_at: null,
  }
  const tubeShape = {
    id: 'tube-shape-1', shape_name: '扁圆管', status: 'ACTIVE', sort_order: 1,
    description: '', created_at: '2026-08-31T00:00:00Z', updated_at: '2026-08-31T00:00:00Z', archived_at: null,
  }
  const tubeCoatingColor = {
    id: 'tube-color-1', color_name: 'Pantone  7771c亮光', status: 'ACTIVE', sort_order: 2,
    description: '', created_at: '2026-08-31T00:00:00Z', updated_at: '2026-08-31T00:00:00Z', archived_at: null,
  }
  const accessoryProductName = {
    id: 'accessory-name-1', product_name: '半元靠背海棉', unit_name: '个', status: 'ACTIVE', sort_order: 1,
    description: '', created_at: '2026-08-31T00:00:00Z', updated_at: '2026-08-31T00:00:00Z', archived_at: null,
  }
  const accessorySpecification = {
    id: 'accessory-spec-1', product_name: 'accessory-name-1', product_name_label: '半元靠背海棉', unit_name: '个',
    specification_value: '长33*宽17*高5CM', weight: '', status: 'ACTIVE', sort_order: 1,
    description: '', created_at: '2026-08-31T00:00:00Z', updated_at: '2026-08-31T00:00:00Z', archived_at: null,
  }
  const accessoryColor = {
    id: 'accessory-color-1', product_name: 'accessory-name-1', product_name_label: '半元靠背海棉', unit_name: '个',
    color_name: '白色', status: 'ACTIVE', sort_order: 1, description: '',
    created_at: '2026-08-31T00:00:00Z', updated_at: '2026-08-31T00:00:00Z', archived_at: null,
  }
  const accessoryMaterial = {
    id: 'accessory-material-1', material_name: '橡胶', status: 'ACTIVE', sort_order: 1,
    inventory_raw_material: null, inventory_material_number: null, inventory_material_name: null,
    inventory_material_unit: null,
    description: '', created_at: '2026-08-31T00:00:00Z', updated_at: '2026-08-31T00:00:00Z', archived_at: null,
  }
  return {
    granted, category, unit, color, fabricMaterial, fabricSpecification, fabricWidth,
    tubeProductName, tubeThickness, tubeDiameter, tubeMaterial, tubeShape, tubeCoatingColor,
    accessoryProductName, accessorySpecification, accessoryColor, accessoryMaterial,
  }
})

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({
    user: { is_superuser: false },
    hasPermission: (permission: string) => fixtures.granted.has(permission),
  }),
}))

const apiMocks = vi.hoisted(() => ({
  fetchProductionDataSummary: vi.fn(),
  fetchProductionDataList: vi.fn(),
  fetchAllProductCategories: vi.fn(),
  fetchAllAccessoryProductNames: vi.fn(),
  fetchAllInventoryRawMaterials: vi.fn(),
}))

vi.mock('@/api/productionData', () => ({
  fetchProductionDataSummary: apiMocks.fetchProductionDataSummary,
  fetchProductionDataList: apiMocks.fetchProductionDataList,
  fetchAllProductCategories: apiMocks.fetchAllProductCategories,
  fetchAllAccessoryProductNames: apiMocks.fetchAllAccessoryProductNames,
  fetchProductionDataRecord: vi.fn(),
  createProductionDataRecord: vi.fn(),
  updateProductionDataRecord: vi.fn(),
  changeProductionDataStatus: vi.fn(),
  uploadProductColorImage: vi.fn(),
  clearProductColorImage: vi.fn(),
}))

vi.mock('@/api/rawMaterials', () => ({
  fetchAllInventoryRawMaterials: apiMocks.fetchAllInventoryRawMaterials,
}))

describe('ProductionDataView', () => {
  beforeEach(() => {
    document.body.innerHTML = ''
    fixtures.granted.clear()
    for (const model of [
      'productcategory', 'productionunit', 'productcolor', 'productitem',
      'fabricmaterial', 'fabricspecification', 'fabricwidth',
      'tubeproductname', 'tubethickness', 'tubediameter', 'tubematerial', 'tubeshape', 'tubecoatingcolor',
      'accessoryproductname', 'accessoryspecification', 'accessorycolor', 'accessorymaterial',
    ]) {
      fixtures.granted.add(`reference_data.view_${model}`)
      fixtures.granted.add(`reference_data.add_${model}`)
      fixtures.granted.add(`reference_data.change_${model}`)
    }
    fixtures.granted.add('products.view_rawmaterialinformation')
    apiMocks.fetchProductionDataSummary.mockReset().mockResolvedValue({
      category_counts: {
        product_categories: 50, production_units: 12, product_colors: 324, product_items: 35,
        fabric_materials: 7, fabric_specifications: 16, fabric_widths: 8,
        tube_product_names: 79, tube_thicknesses: 14, tube_diameters: 24,
        tube_materials: 3, tube_shapes: 7, tube_coating_colors: 29,
        accessory_product_names: 148, accessory_specifications: 349,
        accessory_colors: 284, accessory_materials: 27,
      },
    })
    apiMocks.fetchAllProductCategories.mockReset().mockResolvedValue([fixtures.category])
    apiMocks.fetchAllAccessoryProductNames.mockReset().mockResolvedValue([fixtures.accessoryProductName])
    apiMocks.fetchAllInventoryRawMaterials.mockReset().mockResolvedValue([
      {
        id: 'raw-material-1', material_number: 'RM-001', material_name: '库存牛津布',
        specification: '600D', unit_name: '米',
      },
    ])
    apiMocks.fetchProductionDataList.mockReset().mockImplementation((resource: string) => {
      const rows: Record<string, unknown[]> = {
        'product-categories': [fixtures.category],
        'production-units': [fixtures.unit],
        'product-colors': [fixtures.color],
        'product-items': [],
        'fabric-materials': [fixtures.fabricMaterial],
        'fabric-specifications': [fixtures.fabricSpecification],
        'fabric-widths': [fixtures.fabricWidth],
        'tube-product-names': [fixtures.tubeProductName],
        'tube-thicknesses': [fixtures.tubeThickness],
        'tube-diameters': [fixtures.tubeDiameter],
        'tube-materials': [fixtures.tubeMaterial],
        'tube-shapes': [fixtures.tubeShape],
        'tube-coating-colors': [fixtures.tubeCoatingColor],
        'accessory-product-names': [fixtures.accessoryProductName],
        'accessory-specifications': [fixtures.accessorySpecification],
        'accessory-colors': [fixtures.accessoryColor],
        'accessory-materials': [fixtures.accessoryMaterial],
      }
      return Promise.resolve({ data: rows[resource], meta: { total: rows[resource].length, page: 1, page_size: 50, total_pages: 1 } })
    })
  })

  it('显示四个一级维护分类并在生产维护中切换颜色设置项', async () => {
    const wrapper = mount(ProductionDataView, { attachTo: document.body, global: { plugins: [createPinia(), ElementPlus] } })
    await flushPromises()
    await flushPromises()

    expect(wrapper.text()).toContain('生产维护')
    expect(wrapper.text()).toContain('面料维护')
    expect(wrapper.text()).toContain('辅料维护')
    expect(wrapper.text()).toContain('管材维护')
    expect(wrapper.text()).toContain('类别维护')
    expect(wrapper.text()).toContain('50')
    expect(wrapper.text()).toContain('324')
    expect(wrapper.findComponent({ name: 'ElTable' }).props('height')).toBe('100%')

    const colorButton = wrapper.findAll('button').find((button) => button.text().includes('颜色维护'))
    expect(colorButton).toBeTruthy()
    await colorButton!.trigger('click')
    await flushPromises()

    expect(apiMocks.fetchProductionDataList).toHaveBeenLastCalledWith(
      'product-colors',
      expect.objectContaining({ page: 1, page_size: 50 }),
    )
    expect(wrapper.text()).toContain('7771 C')
    expect(wrapper.find('.color-thumb').exists()).toBe(true)
    expect(wrapper.text()).not.toContain('归档')

    const itemButton = wrapper.findAll('button').find((button) => button.text().includes('货号维护'))
    expect(itemButton).toBeTruthy()
    await itemButton!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).not.toContain('data_id')
  })

  it('嵌入配置窗口时要求先处理生产资料编辑，取消后允许关闭', async () => {
    const wrapper = mount(ProductionDataView, { global: { plugins: [createPinia(), ElementPlus], stubs: { teleport: true, ElSelect: true, ElOption: true } } })
    await flushPromises()
    expect(wrapper.vm.canClose()).toBe(true)
    await wrapper.findAll('button').find(button => button.text() === '新增产品类别')!.trigger('click')
    await flushPromises()
    expect(wrapper.vm.canClose()).toBe(false)
    expect(wrapper.findComponent(AppWindowDialog).props('modelValue')).toBe(true)
    await wrapper.findAll('button').find(button => button.text() === '取消')!.trigger('click')
    expect(wrapper.vm.canClose()).toBe(true)
    wrapper.unmount()
  })

  it('面料维护显示材质规格门幅并读取导入数据', async () => {
    const wrapper = mount(ProductionDataView, { global: { plugins: [createPinia(), ElementPlus] } })
    await flushPromises()

    const fabricButton = wrapper.findAll('.metric-card').find((button) => button.text().includes('面料维护'))
    expect(fabricButton).toBeTruthy()
    await fabricButton!.trigger('click')
    await flushPromises()

    expect(wrapper.find('.category-panel').text()).toContain('面料维护')
    expect(wrapper.find('.category-panel').text()).toContain('材质维护')
    expect(wrapper.find('.category-panel').text()).toContain('规格维护')
    expect(wrapper.find('.category-panel').text()).toContain('门幅维护')
    expect(wrapper.find('.category-panel').text()).toContain('7')
    expect(wrapper.text()).toContain('加密尼龙')
    expect(apiMocks.fetchProductionDataList).toHaveBeenLastCalledWith(
      'fabric-materials',
      expect.objectContaining({ page: 1, page_size: 50 }),
    )

    const addButton = wrapper.findAll('button').find((button) => button.text().includes('新增面料材质'))
    expect(addButton).toBeTruthy()
    await addButton!.trigger('click')
    await flushPromises()
    expect(apiMocks.fetchAllInventoryRawMaterials).toHaveBeenCalled()
    expect(document.body.textContent).toContain('库存原料')
    wrapper.unmount()
  })

  it('管材维护显示六个设置项并读取原始导入数据', async () => {
    const wrapper = mount(ProductionDataView, { global: { plugins: [createPinia(), ElementPlus] } })
    await flushPromises()

    const tubeButton = wrapper.findAll('.metric-card').find((button) => button.text().includes('管材维护'))
    expect(tubeButton).toBeTruthy()
    await tubeButton!.trigger('click')
    await flushPromises()

    const categoryPanelText = wrapper.find('.category-panel').text()
    expect(categoryPanelText).toContain('品名维护')
    expect(categoryPanelText).toContain('厚度维护')
    expect(categoryPanelText).toContain('直径维护')
    expect(categoryPanelText).toContain('材质维护')
    expect(categoryPanelText).toContain('形状维护')
    expect(categoryPanelText).toContain('喷塑颜色')
    expect(categoryPanelText).toContain('79')
    expect(wrapper.text()).toContain('上下短脚管')
    expect(apiMocks.fetchProductionDataList).toHaveBeenLastCalledWith(
      'tube-product-names',
      expect.objectContaining({ page: 1, page_size: 50 }),
    )

    const colorButton = wrapper.findAll('.category-panel button').find((button) => button.text().includes('喷塑颜色'))
    expect(colorButton).toBeTruthy()
    await colorButton!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('Pantone  7771c亮光')
    expect(apiMocks.fetchProductionDataList).toHaveBeenLastCalledWith(
      'tube-coating-colors',
      expect.objectContaining({ page: 1, page_size: 50 }),
    )
  })

  it('辅料维护显示四个设置项且规格颜色使用品名关联', async () => {
    const wrapper = mount(ProductionDataView, { global: { plugins: [createPinia(), ElementPlus] } })
    await flushPromises()

    const accessoryButton = wrapper.findAll('.metric-card').find((button) => button.text().includes('辅料维护'))
    expect(accessoryButton).toBeTruthy()
    await accessoryButton!.trigger('click')
    await flushPromises()

    const categoryPanelText = wrapper.find('.category-panel').text()
    expect(categoryPanelText).toContain('品名维护')
    expect(categoryPanelText).toContain('规格维护')
    expect(categoryPanelText).toContain('颜色维护')
    expect(categoryPanelText).toContain('材质维护')
    expect(categoryPanelText).toContain('148')
    expect(wrapper.text()).toContain('半元靠背海棉')

    const specificationButton = wrapper.findAll('.category-panel button').find((button) => button.text().includes('规格维护'))
    expect(specificationButton).toBeTruthy()
    await specificationButton!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('长33*宽17*高5CM')
    expect(apiMocks.fetchProductionDataList).toHaveBeenLastCalledWith(
      'accessory-specifications',
      expect.objectContaining({ page: 1, page_size: 50 }),
    )
    expect(apiMocks.fetchAllAccessoryProductNames).toHaveBeenCalled()

    const colorButton = wrapper.findAll('.category-panel button').find((button) => button.text().includes('颜色维护'))
    expect(colorButton).toBeTruthy()
    await colorButton!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('白色')
    expect(wrapper.text()).toContain('半元靠背海棉')
  })

  it('只有面料材质查看权限时默认进入面料维护', async () => {
    fixtures.granted.clear()
    fixtures.granted.add('reference_data.view_fabricmaterial')
    const wrapper = mount(ProductionDataView, { global: { plugins: [createPinia(), ElementPlus] } })
    await flushPromises()
    await flushPromises()

    expect(wrapper.find('.category-panel').text()).toContain('面料维护')
    expect(wrapper.find('.category-panel').text()).toContain('材质维护')
    expect(wrapper.find('.category-panel').text()).not.toContain('规格维护')
    expect(wrapper.text()).toContain('加密尼龙')
    expect(apiMocks.fetchProductionDataList).toHaveBeenLastCalledWith(
      'fabric-materials',
      expect.objectContaining({ page: 1, page_size: 50 }),
    )
  })

  it('新增窗口可拖动并使用可缩放窗口类', async () => {
    const wrapper = mount(ProductionDataView, { global: { plugins: [createPinia(), ElementPlus] } })
    await flushPromises()

    const addButton = wrapper.findAll('button').find((button) => button.text().includes('新增产品类别'))
    expect(addButton).toBeTruthy()
    await addButton!.trigger('click')
    await flushPromises()

    const dialog = wrapper.findComponent(AppWindowDialog)
    expect(dialog.exists()).toBe(true)
    expect(dialog.props('width')).toBe('min(680px, 92vw)')
    expect(document.body.textContent).toContain('可拖动标题移动窗口')
    wrapper.unmount()
  })

  it('没有任何生产资料查看权限时不调用接口', async () => {
    fixtures.granted.clear()
    const wrapper = mount(ProductionDataView, { global: { plugins: [createPinia(), ElementPlus] } })
    await flushPromises()

    expect(wrapper.text()).toContain('无生产资料权限')
    expect(apiMocks.fetchProductionDataSummary).not.toHaveBeenCalled()
    expect(apiMocks.fetchProductionDataList).not.toHaveBeenCalled()
  })
})
