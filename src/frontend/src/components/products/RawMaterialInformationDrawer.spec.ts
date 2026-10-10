import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import RawMaterialInformationDrawer from './RawMaterialInformationDrawer.vue'

const fixture = {
  id: 'raw-1', material_number: 'YL0004', item_type: 'MATERIAL' as const, item_type_label: '材料',
  category: 'category-package', category_name: '包材', material_name: '12号半盖纸箱',
  specification: '87×23×30.5', unit: 'unit-pcs', unit_code: 'PCS', unit_name: 'PCS',
  color: null, color_name: '/', color_label: '/', has_legacy_color: true, material: '/',
  is_packaging_auxiliary: false, box_shape: 'HALF_COVER' as const, notes: '历史备注',
  warehouse_number: 'CK04', warehouse_name: '旧包材仓', diameter: '/', length: '/', width: '/',
  thickness: '/', model_number: '/', weight_kg: '', flow_unit: '', number_value: '87',
  source_unique_check: 'legacy-source', source_row_number: 3, created_at: '2026-08-31T00:00:00Z',
  updated_at: '2026-08-31T00:00:00Z', archived_at: null,
}

const apiMocks = vi.hoisted(() => ({
  fetchRawMaterialOptions: vi.fn(), fetchRawMaterial: vi.fn(), createRawMaterial: vi.fn(), updateRawMaterial: vi.fn(),
}))

vi.mock('@/api/rawMaterials', () => apiMocks)

const drawerStub = {
  name: 'ElDrawer',
  props: ['modelValue', 'size'],
  template: '<div v-if="modelValue"><slot name="header" /><slot /><slot name="footer" /></div>',
}

const options = {
  item_types: [{ value: 'MATERIAL' as const, label: '材料' }, { value: 'SEMI_FINISHED' as const, label: '半成品' }],
  categories: [
    { id: 'category-package', item_type: 'MATERIAL' as const, category_name: '包材' },
    { id: 'category-tube', item_type: 'MATERIAL' as const, category_name: '管材' },
  ],
  units: [{ id: 'unit-pcs', unit_code: 'PCS', unit_name: 'PCS' }],
  colors: [{ id: 'color-black', color_card: '', color_code: '', color_name: '黑色', label: '黑色' }],
  warehouses: [
    { warehouse_number: 'CK04', warehouse_name: '新包材仓' },
    { warehouse_number: 'CK04', warehouse_name: '旧包材仓' },
  ],
  box_shapes: [{ value: 'HALF_COVER' as const, label: '半盖' }],
}

const mountDrawer = (mode: 'create' | 'edit' = 'edit') => mount(RawMaterialInformationDrawer, {
  props: { modelValue: true, mode, materialId: mode === 'edit' ? 'raw-1' : undefined },
  global: { plugins: [ElementPlus], stubs: { ElDrawer: drawerStub } },
})

describe('RawMaterialInformationDrawer', () => {
  beforeEach(() => {
    document.body.innerHTML = ''
    vi.clearAllMocks()
    apiMocks.fetchRawMaterialOptions.mockResolvedValue(options)
    apiMocks.fetchRawMaterial.mockResolvedValue({ data: fixture, etag: '"raw-etag-1"' })
    apiMocks.updateRawMaterial.mockResolvedValue({ data: fixture, etag: '"raw-etag-2"' })
  })

  it('历史颜色未操作时省略 color，并按编号与名称组合选择仓库', async () => {
    const wrapper = mountDrawer()
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text().includes('保存修改'))!.trigger('click')
    await flushPromises()

    expect(apiMocks.updateRawMaterial).toHaveBeenCalledTimes(1)
    const payload = apiMocks.updateRawMaterial.mock.calls[0][1]
    expect(payload).not.toHaveProperty('color')
    expect(payload).toMatchObject({ warehouse_number: 'CK04', warehouse_name: '旧包材仓', notes: '历史备注' })
    expect(payload).not.toHaveProperty('source_unique_check')
    expect(payload).not.toHaveProperty('diameter')
  })

  it('明确清空历史颜色时提交 null，备注不添加虚构长度限制', async () => {
    const wrapper = mountDrawer()
    await flushPromises()
    const colorSelect = wrapper.findAllComponents({ name: 'ElSelect' })
      .find((select) => select.props('placeholder') === '请选择颜色')!
    expect(colorSelect.props('modelValue')).toBe('__legacy_color__')
    colorSelect.vm.$emit('update:modelValue', '')
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text().includes('保存修改'))!.trigger('click')
    await flushPromises()

    expect(apiMocks.updateRawMaterial.mock.calls[0][1]).toMatchObject({ color: null })
    expect(wrapper.find('textarea').attributes('maxlength')).toBeUndefined()
  })

  it('新增态为空值起步，选择材料包材后才显示包装字段', async () => {
    const wrapper = mountDrawer('create')
    await flushPromises()
    expect(wrapper.findComponent({ name: 'ElDrawer' }).props('size')).toBe('896px')
    expect(wrapper.text()).not.toContain('是否包材辅料')

    const selects = wrapper.findAllComponents({ name: 'ElSelect' })
    selects.find((select) => select.props('placeholder') === '请选择类型')!.vm.$emit('update:modelValue', 'MATERIAL')
    await flushPromises()
    selects.find((select) => select.props('placeholder') === '请先选择类型')!.vm.$emit('update:modelValue', 'category-package')
    await flushPromises()

    expect(wrapper.text()).toContain('是否包材辅料')
    expect(wrapper.text()).toContain('箱子形状')
  })

  it('切换历史原料类型时清除已经不在有效选项中的旧类别', async () => {
    apiMocks.fetchRawMaterial.mockResolvedValueOnce({
      data: { ...fixture, category: 'inactive-category', category_name: '已停用类别' },
      etag: '"raw-etag-1"',
    })
    const wrapper = mountDrawer()
    await flushPromises()
    const selects = wrapper.findAllComponents({ name: 'ElSelect' })
    const typeSelect = selects.find((select) => select.props('placeholder') === '请选择类型')!
    const categorySelect = selects.find((select) => select.props('placeholder') === '请先选择类型')!
    expect(categorySelect.props('modelValue')).toBe('inactive-category')
    typeSelect.vm.$emit('update:modelValue', 'SEMI_FINISHED')
    await flushPromises()
    expect(categorySelect.props('modelValue')).toBe('')
  })

  it('冲突后重新读取失败会恢复原料草稿', async () => {
    apiMocks.updateRawMaterial.mockRejectedValueOnce({ response: { status: 412, data: {} } })
    apiMocks.fetchRawMaterial
      .mockResolvedValueOnce({ data: fixture, etag: '"raw-etag-1"' })
      .mockRejectedValueOnce(new Error('network'))
    const wrapper = mountDrawer()
    await flushPromises()
    await wrapper.find('textarea').setValue('原料网络失败草稿')
    await wrapper.findAll('button').find((button) => button.text().includes('保存修改'))!.trigger('click')
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text().includes('重新读取最新资料'))!.trigger('click')
    await flushPromises()

    expect((wrapper.find('textarea').element as HTMLTextAreaElement).value).toBe('原料网络失败草稿')
    expect(wrapper.text()).toContain('数据已被其他人更新，本次未保存')
  })

  it('恢复历史颜色草稿时不会清空并发用户写入的正式颜色', async () => {
    apiMocks.updateRawMaterial
      .mockRejectedValueOnce({ response: { status: 412, data: {} } })
      .mockResolvedValueOnce({ data: fixture, etag: '"raw-etag-3"' })
    apiMocks.fetchRawMaterial
      .mockResolvedValueOnce({ data: fixture, etag: '"raw-etag-1"' })
      .mockResolvedValueOnce({
        data: { ...fixture, color: 'color-black', color_name: '黑色', has_legacy_color: false },
        etag: '"raw-etag-2"',
      })
    const wrapper = mountDrawer()
    await flushPromises()
    await wrapper.find('textarea').setValue('保留历史颜色语义的草稿')
    const save = () => wrapper.findAll('button').find((button) => button.text().includes('保存修改'))!.trigger('click')
    await save()
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text().includes('重新读取最新资料'))!.trigger('click')
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text().includes('恢复旧草稿'))!.trigger('click')
    await flushPromises()
    await save()
    await flushPromises()

    expect(apiMocks.updateRawMaterial).toHaveBeenCalledTimes(2)
    expect(apiMocks.updateRawMaterial.mock.calls[1][1]).not.toHaveProperty('color')
    expect(apiMocks.updateRawMaterial.mock.calls[1][2]).toBe('"raw-etag-2"')
  })
})
