import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import RawMaterialManagementView from './RawMaterialManagementView.vue'
import MaterialCatalogSelect from '@/components/products/MaterialCatalogSelect.vue'

const auth = vi.hoisted(() => ({ permissions: new Set<string>() }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ user: { is_superuser: false }, hasPermission: (key: string) => auth.permissions.has(key) }) }))
const api = vi.hoisted(() => ({
  fetchMaterialCatalogOptions: vi.fn(), fetchMaterialCatalogs: vi.fn(), fetchMaterialCatalog: vi.fn(),
  createMaterialCatalog: vi.fn(), updateMaterialCatalog: vi.fn(), addMaterialAttributeValue: vi.fn(),
  deleteMaterialAttributeValue: vi.fn(), addMaterialAllowedUnit: vi.fn(), deleteMaterialAllowedUnit: vi.fn(),
}))
vi.mock('@/api/materialCatalog', async (original) => ({ ...await original<object>(), ...api }))

const fields = [
  { key: 'material', label: '材质', kind: 'text' }, { key: 'color', label: '颜色', kind: 'text' },
  { key: 'shape', label: '截面形状', kind: 'shape' }, { key: 'section_size', label: '截面尺寸', kind: 'dimension' },
  { key: 'thickness', label: '厚度', kind: 'text' }, { key: 'length', label: '长度', kind: 'text' },
  { key: 'unit', label: '可用单位', kind: 'unit' },
]
const packagingTemplates = [
  { templateKey: 'CARTON', label: '纸箱', sizeKey: 'size', sizeLabel: '长宽高尺寸', sizeValue: '600×400×300' },
  { templateKey: 'BAG', label: '塑料袋', sizeKey: 'size', sizeLabel: '长宽尺寸', sizeValue: '300×400' },
  { templateKey: 'PACKAGING_GENERAL', label: '通用包材', sizeKey: 'specification', sizeLabel: '规格', sizeValue: 'EPE-20' },
]
const definitions = {
  categories: [
    { key: 'TUBE', label: '管材', templates: [{ key: 'TUBE', label: '管材', supports_spray: true, fields }] },
    { key: 'PACKAGING', label: '包材', templates: [
      { key: 'CARTON', label: '纸箱', supports_spray: false, fields: [{ key: 'layers', label: '层数', kind: 'text' }] },
      { key: 'BAG', label: '塑料袋', supports_spray: false, fields: [{ key: 'bag_type', label: '袋型/封口方式', kind: 'text' }] },
    ] },
  ],
  spray_fields: [{ key: 'color', label: '颜色', kind: 'text' }, { key: 'length', label: '长度', kind: 'text' }, { key: 'unit', label: '可用单位', kind: 'unit' }],
  units: [{ id: 'unit-root', unit_name: '根' }, { id: 'unit-kg', unit_name: '公斤' }],
}
function detail(id = 'a', name = '铁管') {
  return { id, name, category_key: 'TUBE', template_key: 'TUBE', spray_enabled: false, updated_at: '2026-10-16T00:00:00Z',
    values: [
      { id: `${id}-color`, scope: 'BASE', field_key: 'color', value: '无颜色', parent_id: null },
      { id: `${id}-round`, scope: 'BASE', field_key: 'shape', value: '圆管', parent_id: null },
      { id: `${id}-square`, scope: 'BASE', field_key: 'shape', value: '方管', parent_id: null },
      { id: `${id}-diameter`, scope: 'BASE', field_key: 'section_size', value: 'Φ16', parent_id: `${id}-round` },
    ], units: [{ id: `${id}-unit`, scope: 'BASE', unit_id: 'unit-root', unit_name: '根' }],
  }
}
function deferred<T>() { let resolve!: (value: T) => void; let reject!: (reason: unknown) => void; const promise = new Promise<T>((done, fail) => { resolve = done; reject = fail }); return { promise, resolve, reject } }
let wrapper: VueWrapper
const row = (field: string, scope = 'BASE', parent = '') => wrapper.get(`[data-field="${scope}:${field}:${parent}"]`)
async function open() { wrapper = mount(RawMaterialManagementView); await flushPromises() }
async function choose(label: string, value: string) {
  const select = wrapper.findAllComponents(MaterialCatalogSelect).find(item => item.props('ariaLabel') === label)!
  select.vm.$emit('update:modelValue', value)
  select.vm.$emit('change', value)
  await flushPromises()
}
async function draft(field: string, value: string, scope = 'BASE', parent = '') {
  await row(field, scope, parent).get('[data-action="add"]').trigger('click')
  await row(field, scope, parent).get('input').setValue(value)
}

beforeEach(() => {
  vi.resetAllMocks()
  auth.permissions = new Set(['view', 'add', 'change'].map(action => `material_catalog.${action}_materialcatalog`))
  api.fetchMaterialCatalogOptions.mockResolvedValue(definitions)
  api.fetchMaterialCatalogs.mockResolvedValue({ data: [detail(), detail('b', '扶手管')], meta: { page: 1, page_size: 50, total: 2, total_pages: 1 } })
  api.fetchMaterialCatalog.mockImplementation(async (id: string) => ({ data: detail(id, id === 'a' ? '铁管' : '扶手管'), etag: `"${id}-1"` }))
})
afterEach(() => { wrapper?.unmount(); vi.useRealTimers() })

describe('独立原料管理', () => {
  it('用后端定义展示独立属性和形状尺寸，不生成属性组合', async () => {
    await open()
    expect(wrapper.get('[data-testid="material-names"]').text()).toContain('铁管')
    expect(row('section_size', 'BASE', 'a-round').text()).toContain('Φ16')
    expect(row('section_size', 'BASE', 'a-square').text()).not.toContain('Φ16')
    expect(wrapper.get('.section-labels').text()).toContain('截面形状截面尺寸')
    expect(row('shape').find('.option-chip').exists()).toBe(false)
    expect(wrapper.findAll('[data-field]')).toHaveLength(8)
    expect(wrapper.find('table').exists()).toBe(false)
    expect(wrapper.text()).not.toMatch(/SKU|生成规格|保存全部/)
  })

  it('输入与失焦不写库，点击小保存后显示服务器返回选项', async () => {
    await open()
    await draft('material', '  Q235  ')
    await row('material').get('input').trigger('blur')
    expect(api.addMaterialAttributeValue).not.toHaveBeenCalled()
    const saved = detail(); saved.values.push({ id: 'new-material', scope: 'BASE', field_key: 'material', value: 'Q235', parent_id: null })
    api.addMaterialAttributeValue.mockResolvedValue({ data: saved, etag: '"a-2"' })
    await row('material').get('[data-action="save"]').trigger('click'); await flushPromises()
    expect(api.addMaterialAttributeValue).toHaveBeenCalledWith('a', { scope: 'BASE', field_key: 'material', value: 'Q235', parent_id: null }, '"a-1"')
    expect(row('material').text()).toContain('Q235')
    expect(row('material').find('input').exists()).toBe(false)
  })

  it('保存失败保留输入并显示字段错误，空白输入不发送请求', async () => {
    await open(); await draft('material', '   ')
    await row('material').get('[data-action="save"]').trigger('click'); await flushPromises()
    expect(api.addMaterialAttributeValue).not.toHaveBeenCalled()
    await row('material').get('input').setValue('Q235')
    api.addMaterialAttributeValue.mockRejectedValue({ response: { status: 400, data: { error: { field_errors: { value: ['该选项已存在'] } } } } })
    await row('material').get('[data-action="save"]').trigger('click'); await flushPromises()
    expect((row('material').get('input').element as HTMLInputElement).value).toBe('Q235')
    expect(row('material').get('[role="alert"]').text()).toContain('该选项已存在')
  })

  it('尺寸新增携带对应形状父项，删除只移除服务器确认的选项', async () => {
    await open(); await draft('section_size', '20×20', 'BASE', 'a-square')
    const updated = detail(); updated.values.push({ id: 'size-new', scope: 'BASE', field_key: 'section_size', value: '20×20', parent_id: 'a-square' })
    api.addMaterialAttributeValue.mockResolvedValue({ data: updated, etag: '"a-2"' })
    await row('section_size', 'BASE', 'a-square').get('[data-action="save"]').trigger('click'); await flushPromises()
    expect(api.addMaterialAttributeValue).toHaveBeenCalledWith('a', expect.objectContaining({ parent_id: 'a-square', field_key: 'section_size' }), '"a-1"')
    api.deleteMaterialAttributeValue.mockResolvedValue({ data: detail(), etag: '"a-3"' })
    await row('section_size', 'BASE', 'a-square').get('[aria-label="删除20×20"]').trigger('click'); await flushPromises()
    expect(api.deleteMaterialAttributeValue).toHaveBeenCalledWith('a', 'size-new', '"a-2"')
    expect(row('section_size', 'BASE', 'a-square').text()).not.toContain('20×20')
  })

  it('喷塑在同档启用，只呈现喷塑定义并从现有单位字典选取', async () => {
    await open()
    const enabled = { ...detail(), spray_enabled: true }
    api.updateMaterialCatalog.mockResolvedValue({ data: enabled, etag: '"a-2"' })
    await wrapper.get('[data-testid="spray-enabled"]').setValue(true); await flushPromises()
    expect(api.updateMaterialCatalog).toHaveBeenCalledWith('a', { spray_enabled: true }, '"a-1"')
    expect(wrapper.findAll('[data-field^="SPRAY:"]')).toHaveLength(3)
    await row('unit', 'SPRAY').get('[data-action="add"]').trigger('click')
    await choose('添加可用单位', 'unit-kg')
    api.addMaterialAllowedUnit.mockResolvedValue({ data: { ...enabled, units: [...enabled.units, { id: 'spray-unit', scope: 'SPRAY', unit_id: 'unit-kg', unit_name: '公斤' }] }, etag: '"a-3"' })
    await row('unit', 'SPRAY').get('[data-action="save"]').trigger('click'); await flushPromises()
    expect(api.addMaterialAllowedUnit).toHaveBeenCalledWith('a', { scope: 'SPRAY', unit_id: 'unit-kg' }, '"a-2"')
    expect(row('unit', 'SPRAY').text()).toContain('公斤')
    expect(api.createMaterialCatalog).not.toHaveBeenCalled()
  })

  it('五金流转单位独立于可用单位，增删走属性接口且不扩展到喷塑', async () => {
    api.fetchMaterialCatalogOptions.mockResolvedValue({ ...definitions, categories: [
      { key: 'HARDWARE', label: '五金', templates: [{ key: 'HARDWARE', label: '五金', supports_spray: true, fields: [
        { key: 'flow_unit', label: '流转单位', kind: 'text' }, { key: 'unit', label: '可用单位', kind: 'unit' },
      ] }] },
    ], units: [{ id: 'unit-piece', unit_name: '个' }, { id: 'unit-kg', unit_name: '公斤' }] })
    const hardware = { ...detail('hardware', '螺丝'), category_key: 'HARDWARE', template_key: 'HARDWARE', spray_enabled: true,
      values: [
        { id: 'flow-existing', scope: 'BASE', field_key: 'flow_unit', value: '套', parent_id: null },
        { id: 'spray-color', scope: 'SPRAY', field_key: 'color', value: '白色', parent_id: null },
      ], units: [
        { id: 'base-piece', scope: 'BASE', unit_id: 'unit-piece', unit_name: '个' },
        { id: 'base-kg', scope: 'BASE', unit_id: 'unit-kg', unit_name: '公斤' },
        { id: 'spray-kg', scope: 'SPRAY', unit_id: 'unit-kg', unit_name: '公斤' },
      ],
    }
    api.fetchMaterialCatalogs.mockResolvedValue({ data: [hardware], meta: { page: 1, page_size: 50, total: 1, total_pages: 1 } })
    api.fetchMaterialCatalog.mockResolvedValue({ data: hardware, etag: '"hardware-1"' })
    await open()
    const labels = (field: string, scope = 'BASE') => row(field, scope).findAll('.option-label').map(item => item.text())
    expect(row('flow_unit').get('.attribute-label').text()).toBe('流转单位')
    expect(row('unit').get('.attribute-label').text()).toBe('可用单位')
    expect(labels('flow_unit')).toEqual(['套'])
    expect(labels('unit')).toEqual(['个', '公斤'])
    expect(wrapper.find('[data-field="SPRAY:flow_unit:"]').exists()).toBe(false)
    await row('unit').get('[data-action="add"]').trigger('click')
    expect(row('unit').findComponent(MaterialCatalogSelect).exists()).toBe(true)
    expect(row('unit').find('select').exists()).toBe(false)
    await row('unit').get('[aria-label="取消添加"]').trigger('click')

    await draft('flow_unit', '箱')
    expect(row('flow_unit').findComponent(MaterialCatalogSelect).exists()).toBe(false)
    const saved = { ...hardware, values: [...hardware.values, { id: 'flow-new', scope: 'BASE', field_key: 'flow_unit', value: '箱', parent_id: null }] }
    api.addMaterialAttributeValue.mockResolvedValue({ data: saved, etag: '"hardware-2"' })
    await row('flow_unit').get('[data-action="save"]').trigger('click'); await flushPromises()
    expect(api.addMaterialAttributeValue).toHaveBeenCalledExactlyOnceWith('hardware', { scope: 'BASE', field_key: 'flow_unit', value: '箱', parent_id: null }, '"hardware-1"')
    expect(labels('flow_unit')).toEqual(['套', '箱'])
    expect(labels('unit')).toEqual(['个', '公斤'])
    expect(labels('unit', 'SPRAY')).toEqual(['公斤'])

    api.deleteMaterialAttributeValue.mockResolvedValue({ data: hardware, etag: '"hardware-3"' })
    await row('flow_unit').get('[aria-label="删除箱"]').trigger('click'); await flushPromises()
    expect(api.deleteMaterialAttributeValue).toHaveBeenCalledExactlyOnceWith('hardware', 'flow-new', '"hardware-2"')
    expect(labels('flow_unit')).toEqual(['套'])
    expect(labels('unit')).toEqual(['个', '公斤'])
    expect(labels('unit', 'SPRAY')).toEqual(['公斤'])
    expect(wrapper.find('[data-field="SPRAY:flow_unit:"]').exists()).toBe(false)
    expect(api.addMaterialAllowedUnit).not.toHaveBeenCalled()
    expect(api.deleteMaterialAllowedUnit).not.toHaveBeenCalled()
  })

  it.each(packagingTemplates)('$templateKey 的箱子形状独立多值，增删保留规格与可用单位', async ({ templateKey, label, sizeKey, sizeLabel, sizeValue }) => {
    api.fetchMaterialCatalogOptions.mockResolvedValue({ ...definitions, categories: [
      { key: 'PACKAGING', label: '包材', templates: [{ key: templateKey, label, supports_spray: false, fields: [
        { key: 'box_type', label: '箱子形状', kind: 'text' },
        { key: sizeKey, label: sizeLabel, kind: 'text' }, { key: 'unit', label: '可用单位', kind: 'unit' },
      ] }] },
    ], units: [{ id: 'unit-piece', unit_name: '个' }] })
    const packaging = { ...detail('packaging', label), category_key: 'PACKAGING', template_key: templateKey,
      values: [
        { id: 'shape-rectangle', scope: 'BASE', field_key: 'box_type', value: '长方形', parent_id: null },
        { id: 'shape-square', scope: 'BASE', field_key: 'box_type', value: '正方形', parent_id: null },
        { id: 'size-original', scope: 'BASE', field_key: sizeKey, value: sizeValue, parent_id: null },
      ], units: [{ id: 'base-piece', scope: 'BASE', unit_id: 'unit-piece', unit_name: '个' }],
    }
    api.fetchMaterialCatalogs.mockResolvedValue({ data: [packaging], meta: { page: 1, page_size: 50, total: 1, total_pages: 1 } })
    api.fetchMaterialCatalog.mockResolvedValue({ data: packaging, etag: '"packaging-1"' })
    await open()
    const labels = (field: string) => row(field).findAll('.option-label').map(item => item.text())
    expect(row('box_type').get('.attribute-label').text()).toBe('箱子形状')
    expect(labels('box_type')).toEqual(['长方形', '正方形'])
    expect(labels(sizeKey)).toEqual([sizeValue])
    expect(labels('unit')).toEqual(['个'])

    await draft('box_type', '异形')
    const saved = { ...packaging, values: [...packaging.values, { id: 'shape-new', scope: 'BASE', field_key: 'box_type', value: '异形', parent_id: null }] }
    api.addMaterialAttributeValue.mockResolvedValue({ data: saved, etag: '"packaging-2"' })
    await row('box_type').get('[data-action="save"]').trigger('click'); await flushPromises()
    expect(api.addMaterialAttributeValue).toHaveBeenCalledExactlyOnceWith('packaging', { scope: 'BASE', field_key: 'box_type', value: '异形', parent_id: null }, '"packaging-1"')
    expect(labels('box_type')).toEqual(['长方形', '正方形', '异形'])
    expect(labels(sizeKey)).toEqual([sizeValue])
    expect(labels('unit')).toEqual(['个'])

    api.deleteMaterialAttributeValue.mockResolvedValue({ data: { ...saved, values: saved.values.filter(value => value.id !== 'shape-square') }, etag: '"packaging-3"' })
    await row('box_type').get('[aria-label="删除正方形"]').trigger('click'); await flushPromises()
    expect(api.deleteMaterialAttributeValue).toHaveBeenCalledExactlyOnceWith('packaging', 'shape-square', '"packaging-2"')
    expect(labels('box_type')).toEqual(['长方形', '异形'])
    expect(labels(sizeKey)).toEqual([sizeValue])
    expect(labels('unit')).toEqual(['个'])
    expect(api.addMaterialAllowedUnit).not.toHaveBeenCalled()
    expect(api.deleteMaterialAllowedUnit).not.toHaveBeenCalled()
  })

  it.each(packagingTemplates)('$templateKey 的型号保留原文，增删不改变尺寸、箱子形状、厚度或单位', async ({ templateKey, label, sizeKey, sizeLabel, sizeValue }) => {
    const isBag = templateKey === 'BAG'
    api.fetchMaterialCatalogOptions.mockResolvedValue({ ...definitions, categories: [
      { key: 'PACKAGING', label: '包材', templates: [{ key: templateKey, label, supports_spray: false, fields: [
        { key: 'model', label: '型号', kind: 'text' }, { key: 'box_type', label: '箱子形状', kind: 'text' },
        { key: sizeKey, label: sizeLabel, kind: 'text' },
        ...(isBag ? [{ key: 'thickness', label: '厚度', kind: 'text' }] : []),
        { key: 'unit', label: '可用单位', kind: 'unit' },
      ] }] },
    ], units: [{ id: 'unit-piece', unit_name: '个' }] })
    const packaging = { ...detail('packaging', label), category_key: 'PACKAGING', template_key: templateKey,
      values: [
        { id: 'model-first', scope: 'BASE', field_key: 'model', value: '2.5MM', parent_id: null },
        { id: 'model-second', scope: 'BASE', field_key: 'model', value: 'M-A', parent_id: null },
        { id: 'shape-original', scope: 'BASE', field_key: 'box_type', value: '长方形', parent_id: null },
        { id: 'size-original', scope: 'BASE', field_key: sizeKey, value: sizeValue, parent_id: null },
        ...(isBag ? [{ id: 'thickness-original', scope: 'BASE', field_key: 'thickness', value: '0.05', parent_id: null }] : []),
      ], units: [{ id: 'base-piece', scope: 'BASE', unit_id: 'unit-piece', unit_name: '个' }],
    }
    api.fetchMaterialCatalogs.mockResolvedValue({ data: [packaging], meta: { page: 1, page_size: 50, total: 1, total_pages: 1 } })
    api.fetchMaterialCatalog.mockResolvedValue({ data: packaging, etag: '"packaging-1"' })
    await open()
    const labels = (field: string) => row(field).findAll('.option-label').map(item => item.text())
    const expectOtherOptionsUnchanged = () => {
      expect(labels(sizeKey)).toEqual([sizeValue])
      expect(labels('box_type')).toEqual(['长方形'])
      expect(labels('unit')).toEqual(['个'])
      if (isBag) expect(labels('thickness')).toEqual(['0.05'])
    }
    expect(row('model').get('.attribute-label').text()).toBe('型号')
    expect(labels('model')).toEqual(['2.5MM', 'M-A'])
    expectOtherOptionsUnchanged()

    await draft('model', '10.1*7.6')
    const saved = { ...packaging, values: [...packaging.values, { id: 'model-new', scope: 'BASE', field_key: 'model', value: '10.1*7.6', parent_id: null }] }
    api.addMaterialAttributeValue.mockResolvedValue({ data: saved, etag: '"packaging-2"' })
    await row('model').get('[data-action="save"]').trigger('click'); await flushPromises()
    expect(api.addMaterialAttributeValue).toHaveBeenCalledExactlyOnceWith('packaging', { scope: 'BASE', field_key: 'model', value: '10.1*7.6', parent_id: null }, '"packaging-1"')
    expect(labels('model')).toEqual(['2.5MM', 'M-A', '10.1*7.6'])
    expectOtherOptionsUnchanged()

    api.deleteMaterialAttributeValue.mockResolvedValue({ data: { ...saved, values: saved.values.filter(value => value.id !== 'model-first') }, etag: '"packaging-3"' })
    await row('model').get('[aria-label="删除2.5MM"]').trigger('click'); await flushPromises()
    expect(api.deleteMaterialAttributeValue).toHaveBeenCalledExactlyOnceWith('packaging', 'model-first', '"packaging-2"')
    expect(labels('model')).toEqual(['M-A', '10.1*7.6'])
    expectOtherOptionsUnchanged()
    expect(api.addMaterialAllowedUnit).not.toHaveBeenCalled()
    expect(api.deleteMaterialAllowedUnit).not.toHaveBeenCalled()
  })

  it('委外布面门幅原样展示文本多值，增删保留其他属性与可用单位', async () => {
    api.fetchMaterialCatalogOptions.mockResolvedValue({ ...definitions, categories: [
      { key: 'FABRIC_SEMI', label: '委外布面', templates: [{ key: 'FABRIC_SEMI', label: '委外布面', supports_spray: false, fields: [
        { key: 'width', label: '门幅', kind: 'text' },
        { key: 'specification', label: '规格描述', kind: 'text' }, { key: 'unit', label: '可用单位', kind: 'unit' },
      ] }] },
    ], units: [{ id: 'unit-piece', unit_name: '片' }] })
    const fabric = { ...detail('fabric-semi', '椅面布'), category_key: 'FABRIC_SEMI', template_key: 'FABRIC_SEMI',
      values: [
        { id: 'width-first', scope: 'BASE', field_key: 'width', value: '1.5', parent_id: null },
        { id: 'width-second', scope: 'BASE', field_key: 'width', value: '1.8', parent_id: null },
        { id: 'spec-original', scope: 'BASE', field_key: 'specification', value: '45×50，包边', parent_id: null },
      ], units: [{ id: 'base-piece', scope: 'BASE', unit_id: 'unit-piece', unit_name: '片' }],
    }
    api.fetchMaterialCatalogs.mockResolvedValue({ data: [fabric], meta: { page: 1, page_size: 50, total: 1, total_pages: 1 } })
    api.fetchMaterialCatalog.mockResolvedValue({ data: fabric, etag: '"fabric-1"' })
    await open()
    const labels = (field: string) => row(field).findAll('.option-label').map(item => item.text())
    expect(row('width').get('.attribute-label').text()).toBe('门幅')
    expect(labels('width')).toEqual(['1.5', '1.8'])
    expect(labels('specification')).toEqual(['45×50，包边'])
    expect(labels('unit')).toEqual(['片'])

    await draft('width', '2.0')
    const saved = { ...fabric, values: [...fabric.values, { id: 'width-new', scope: 'BASE', field_key: 'width', value: '2.0', parent_id: null }] }
    api.addMaterialAttributeValue.mockResolvedValue({ data: saved, etag: '"fabric-2"' })
    await row('width').get('[data-action="save"]').trigger('click'); await flushPromises()
    expect(api.addMaterialAttributeValue).toHaveBeenCalledExactlyOnceWith('fabric-semi', { scope: 'BASE', field_key: 'width', value: '2.0', parent_id: null }, '"fabric-1"')
    expect(labels('width')).toEqual(['1.5', '1.8', '2.0'])
    expect(labels('specification')).toEqual(['45×50，包边'])
    expect(labels('unit')).toEqual(['片'])

    api.deleteMaterialAttributeValue.mockResolvedValue({ data: { ...saved, values: saved.values.filter(value => value.id !== 'width-second') }, etag: '"fabric-3"' })
    await row('width').get('[aria-label="删除1.8"]').trigger('click'); await flushPromises()
    expect(api.deleteMaterialAttributeValue).toHaveBeenCalledExactlyOnceWith('fabric-semi', 'width-second', '"fabric-2"')
    expect(labels('width')).toEqual(['1.5', '2.0'])
    expect(labels('specification')).toEqual(['45×50，包边'])
    expect(labels('unit')).toEqual(['片'])
    expect(api.addMaterialAllowedUnit).not.toHaveBeenCalled()
    expect(api.deleteMaterialAllowedUnit).not.toHaveBeenCalled()
  })

  it('同档连续保存串行使用最新版本，写入期间不能切换档案', async () => {
    await open(); await draft('material', 'Q235'); await draft('length', '6000')
    const first = deferred<{ data: ReturnType<typeof detail>; etag: string }>()
    api.addMaterialAttributeValue.mockReturnValueOnce(first.promise).mockResolvedValueOnce({ data: detail(), etag: '"a-3"' })
    await row('material').get('[data-action="save"]').trigger('click')
    await row('length').get('[data-action="save"]').trigger('click'); await flushPromises()
    expect(api.addMaterialAttributeValue).toHaveBeenCalledTimes(1)
    expect((wrapper.get('[data-catalog-id="b"]').element as HTMLButtonElement).disabled).toBe(true)
    first.resolve({ data: detail(), etag: '"a-2"' }); await flushPromises()
    expect(api.addMaterialAttributeValue).toHaveBeenNthCalledWith(2, 'a', expect.objectContaining({ field_key: 'length', value: '6000' }), '"a-2"')
  })

  it('旧详情晚到不会覆盖已切换品名的属性', async () => {
    const slow = deferred<{ data: ReturnType<typeof detail>; etag: string }>()
    api.fetchMaterialCatalog.mockImplementation((id: string) => id === 'a' ? slow.promise : Promise.resolve({ data: detail('b', '扶手管'), etag: '"b-1"' }))
    await open(); await wrapper.get('[data-catalog-id="b"]').trigger('click'); await flushPromises()
    slow.resolve({ data: detail(), etag: '"a-1"' }); await flushPromises()
    expect(wrapper.find('[data-field="BASE:section_size:b-round"]').exists()).toBe(true)
    expect(wrapper.find('[data-field="BASE:section_size:a-round"]').exists()).toBe(false)
  })

  it.each([false, true])('保存取消未执行的筛选并保持搜索框与当前列表一致，失败=%s', async (failed) => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
    await open(); await draft('material', 'Q235')
    await wrapper.get('[aria-label="搜索品名"]').setValue('扶手')
    if (failed) api.addMaterialAttributeValue.mockRejectedValue(new Error('保存失败'))
    else api.addMaterialAttributeValue.mockResolvedValue({ data: detail(), etag: '"a-2"' })
    await row('material').get('[data-action="save"]').trigger('click'); await flushPromises()
    await vi.advanceTimersByTimeAsync(300); await flushPromises()
    expect(api.fetchMaterialCatalogs).toHaveBeenCalledTimes(1)
    expect((wrapper.get('[aria-label="搜索品名"]').element as HTMLInputElement).value).toBe('')
    expect(wrapper.get('[data-catalog-id="a"]').attributes('aria-current')).toBe('true')
    if (failed) expect((row('material').get('input').element as HTMLInputElement).value).toBe('Q235')
  })

  it('分类列表尚未返回时不允许打开上一分类残留的品名', async () => {
    await open()
    const pending = deferred<{ data: ReturnType<typeof detail>[]; meta: { page: number; page_size: number; total: number; total_pages: number } }>()
    api.fetchMaterialCatalogs.mockReturnValue(pending.promise)
    await choose('原料类别', 'PACKAGING')
    expect((wrapper.get('[data-catalog-id="b"]').element as HTMLButtonElement).disabled).toBe(true)
    pending.resolve({ data: [], meta: { page: 1, page_size: 50, total: 0, total_pages: 0 } }); await flushPromises()
    expect(wrapper.get('[data-testid="material-names"]').text()).toContain('暂无品名')
  })

  it('删除有尺寸的形状被拒绝时保留形状与尺寸并显示原因', async () => {
    await open()
    api.deleteMaterialAttributeValue.mockRejectedValue({ response: { status: 400, data: { error: { message: '请先删除该形状下的尺寸。' } } } })
    await row('section_size', 'BASE', 'a-round').get('[aria-label="删除圆管"]').trigger('click'); await flushPromises()
    expect(row('section_size', 'BASE', 'a-round').get('[role="alert"]').text()).toContain('请先删除')
    expect(row('section_size', 'BASE', 'a-round').text()).toContain('Φ16')
    expect(row('section_size', 'BASE', 'a-round').find('[aria-label="删除圆管"]').exists()).toBe(true)
  })

  it('首次排队写入发生版本冲突时停止后续写入并保留两个草稿', async () => {
    await open(); await draft('material', 'Q235'); await draft('length', '6000')
    const first = deferred<{ data: ReturnType<typeof detail>; etag: string }>()
    api.addMaterialAttributeValue.mockReturnValue(first.promise)
    await row('material').get('[data-action="save"]').trigger('click')
    await row('length').get('[data-action="save"]').trigger('click')
    first.reject({ response: { status: 412 } }); await flushPromises()
    expect(api.addMaterialAttributeValue).toHaveBeenCalledTimes(1)
    expect((row('material').get('input').element as HTMLInputElement).value).toBe('Q235')
    expect((row('length').get('input').element as HTMLInputElement).value).toBe('6000')
  })

  it('版本冲突不重试覆盖，重新读取后保留失败草稿供手动保存', async () => {
    await open(); await draft('material', 'Q235')
    api.addMaterialAttributeValue.mockRejectedValue({ response: { status: 412 } })
    await row('material').get('[data-action="save"]').trigger('click'); await flushPromises()
    expect(wrapper.get('[data-testid="version-warning"]').text()).toContain('重新读取')
    api.fetchMaterialCatalog.mockResolvedValue({ data: detail(), etag: '"a-latest"' })
    await wrapper.get('[data-testid="reload-detail"]').trigger('click'); await flushPromises()
    expect((row('material').get('input').element as HTMLInputElement).value).toBe('Q235')
    expect(api.addMaterialAttributeValue).toHaveBeenCalledTimes(1)
  })

  it('多模板类别必须明确选择模板，再创建并展示其定义字段', async () => {
    await open()
    api.fetchMaterialCatalogs.mockResolvedValue({ data: [], meta: { page: 1, page_size: 50, total: 0, total_pages: 0 } })
    await choose('原料类别', 'PACKAGING')
    await wrapper.get('[data-testid="create-name"]').trigger('click')
    await wrapper.get('[aria-label="新品名"]').setValue('内袋')
    await wrapper.get('[data-testid="save-name"]').trigger('click'); await flushPromises()
    expect(api.createMaterialCatalog).not.toHaveBeenCalled()
    await choose('品名模板', 'BAG')
    const bag = { ...detail('bag', '内袋'), category_key: 'PACKAGING', template_key: 'BAG', values: [], units: [] }
    api.createMaterialCatalog.mockResolvedValue({ data: bag, etag: '"bag-1"' })
    api.fetchMaterialCatalogs.mockResolvedValue({ data: [bag], meta: { page: 1, page_size: 50, total: 1, total_pages: 1 } })
    await wrapper.get('[data-testid="save-name"]').trigger('click'); await flushPromises()
    expect(api.createMaterialCatalog).toHaveBeenCalledWith({ name: '内袋', category_key: 'PACKAGING', template_key: 'BAG' })
    expect(row('bag_type').text()).toContain('袋型/封口方式')
    expect(wrapper.find('[data-testid="spray-enabled"]').exists()).toBe(false)
  })

  it('无查看权限不请求数据，只有查看权限时不可修改选项', async () => {
    auth.permissions.clear(); await open()
    expect(wrapper.text()).toContain('无权查看原料管理')
    expect(api.fetchMaterialCatalogOptions).not.toHaveBeenCalled()
    wrapper.unmount(); auth.permissions.add('material_catalog.view_materialcatalog'); await open()
    expect(wrapper.find('[data-action="add"]').exists()).toBe(false)
    expect(wrapper.find('[data-action="delete"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="create-name"]').exists()).toBe(false)
    expect(wrapper.get('.shape-heading').isVisible()).toBe(false)
  })
})
