import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import RawMaterialInformationView from './RawMaterialInformationView.vue'

const fixtures = vi.hoisted(() => ({
  granted: new Set<string>(),
  row: {
    id: 'raw-1', material_number: 'YL0004', item_type: 'MATERIAL', item_type_label: '材料',
    category: 'category-package', category_name: '包材', material_name: '12号半盖纸箱',
    specification: '87×23×30.5', unit: 'unit-pcs', unit_code: 'PCS', unit_name: 'PCS',
    color: null, color_name: '/', color_label: '/', has_legacy_color: true, material: '/',
    is_packaging_auxiliary: false, box_shape: 'HALF_COVER', box_shape_label: '半盖', notes: '',
    warehouse_number: 'CK04', warehouse_name: '包材仓', diameter: '/', length: '/', width: '/',
    thickness: '/', model_number: '/', weight_kg: '', flow_unit: '', number_value: '87',
    source_unique_check: '', source_row_number: 3, created_at: '2026-08-31T00:00:00Z',
    updated_at: '2026-08-31T00:00:00Z', archived_at: null,
  },
}))

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({
    user: { is_superuser: false },
    hasPermission: (permission: string) => fixtures.granted.has(permission),
  }),
}))

const apiMocks = vi.hoisted(() => ({
  fetchRawMaterialOptions: vi.fn(),
  fetchRawMaterials: vi.fn(),
}))

vi.mock('@/api/rawMaterials', () => ({
  fetchRawMaterialOptions: apiMocks.fetchRawMaterialOptions,
  fetchRawMaterials: apiMocks.fetchRawMaterials,
}))

const mountView = () => mount(RawMaterialInformationView, {
  global: {
    plugins: [ElementPlus],
    stubs: { RawMaterialInformationDrawer: true },
  },
})

describe('RawMaterialInformationView', () => {
  beforeEach(() => {
    document.body.innerHTML = ''
    fixtures.granted.clear()
    fixtures.granted.add('products.view_rawmaterialinformation')
    fixtures.granted.add('products.add_rawmaterialinformation')
    fixtures.granted.add('products.change_rawmaterialinformation')
    apiMocks.fetchRawMaterialOptions.mockReset().mockResolvedValue({
      item_types: [], categories: [], units: [], colors: [], warehouses: [], box_shapes: [],
    })
    apiMocks.fetchRawMaterials.mockReset().mockResolvedValue({
      data: [fixtures.row],
      meta: { page: 1, page_size: 50, total: 368, total_pages: 8 },
    })
  })

  it('按验收口径显示 50 条分页、强语义标签和组合仓库', async () => {
    const wrapper = mountView()
    await flushPromises()

    expect(apiMocks.fetchRawMaterials).toHaveBeenCalledWith(expect.objectContaining({
      page: 1, page_size: 50, ordering: 'material_number',
    }))
    expect(wrapper.text()).toContain('368 条')
    expect(wrapper.text()).toContain('YL0004')
    expect(wrapper.text()).toContain('CK04')
    expect(wrapper.text()).toContain('包材仓')
    expect(wrapper.find('.strong-tag.is-material').text()).toBe('材料')
    expect(wrapper.find('.strong-tag.is-category').text()).toBe('包材')
    const typeColumn = wrapper.findAllComponents({ name: 'ElTableColumn' })
      .find((column) => column.props('label') === '类型')!
    expect(typeColumn.props('align')).toBe('center')
    expect(typeColumn.props('headerAlign')).toBe('center')
  })

  it('新增与编辑抽屉按需创建，关闭后重开保留正确模式和记录', async () => {
    const wrapper = mountView()
    await flushPromises()
    expect(wrapper.findComponent({ name: 'RawMaterialInformationDrawer' }).exists()).toBe(false)
    await wrapper.find('.create-button').trigger('click')
    const drawer = wrapper.findComponent({ name: 'RawMaterialInformationDrawer' })
    expect(drawer.props('modelValue')).toBe(true)
    expect(drawer.props('mode')).toBe('create')
    drawer.vm.$emit('update:modelValue', false)
    await flushPromises()
    await wrapper.find('.edit-button').trigger('click')
    expect(drawer.props('modelValue')).toBe(true)
    expect(drawer.props('mode')).toBe('edit')
    expect(drawer.props('materialId')).toBe('raw-1')
    wrapper.unmount()
  })

  it('所有可排序列都把升降序传给后端', async () => {
    const wrapper = mountView()
    await flushPromises()
    const table = wrapper.findComponent({ name: 'ElTable' })
    const keys = [
      'material_number', 'item_type', 'category_name', 'material_name', 'specification',
      'unit_name', 'color_name', 'warehouse', 'is_packaging_auxiliary', 'box_shape',
    ] as const

    for (const key of keys) {
      table.vm.$emit('sort-change', { prop: key, order: 'ascending' })
      await flushPromises()
      expect(apiMocks.fetchRawMaterials).toHaveBeenLastCalledWith(expect.objectContaining({ ordering: key }))
      table.vm.$emit('sort-change', { prop: key, order: 'descending' })
      await flushPromises()
      expect(apiMocks.fetchRawMaterials).toHaveBeenLastCalledWith(expect.objectContaining({ ordering: `-${key}` }))
    }
  })

  it('工具栏排序同步原料表头箭头', async () => {
    const wrapper = mountView()
    await flushPromises()
    const table = wrapper.findComponent({ name: 'ElTable' })
    const exposed = (table.vm.$ as unknown as { exposed: { sort: (prop: string, order: string) => void } }).exposed
    const sort = vi.spyOn(exposed, 'sort')
    const toolbar = wrapper.findAllComponents({ name: 'ElSelect' })
      .find((select) => select.props('ariaLabel') === '原料排序')!

    toolbar.vm.$emit('update:modelValue', '-material_number')
    await flushPromises()
    expect(sort).toHaveBeenCalledWith('material_number', 'descending')
  })

  it('没有查看权限时不请求列表和选项', async () => {
    fixtures.granted.clear()
    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain('无权查看原料信息')
    expect(apiMocks.fetchRawMaterialOptions).not.toHaveBeenCalled()
    expect(apiMocks.fetchRawMaterials).not.toHaveBeenCalled()
  })
})
