import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElButton, ElInput, ElMessage, ElOption, ElSelect } from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import MaterialTransferForm from './MaterialTransferForm.vue'
import * as api from '@/api/inventory'
import * as sourceApi from '@/api/inventoryMaterialSources'
import type { MaterialCatalog, MaterialCatalogOptions, MaterialColorSelection, MaterialFieldDefinition, PublicMaterialOptions } from '@/types/materialCatalog'
import type { SampleMaterialCategory } from '@/types/sampleMaterial'

vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ user: { is_superuser: true }, hasPermission: () => true }) }))
vi.mock('@/api/inventory', () => ({ createMaterialTransfer: vi.fn(), fetchMaterialReceivingOptions: vi.fn() }))
vi.mock('@/api/inventoryMaterialSources', () => ({ fetchInboundMaterialOptions: vi.fn(), fetchInboundMaterials: vi.fn(), fetchInboundMaterial: vi.fn(), fetchInboundPublicOptions: vi.fn() }))

type Row = {
  key: string; category: SampleMaterialCategory; catalogId: string; catalog?: MaterialCatalog; publicOptions?: PublicMaterialOptions
  color: MaterialColorSelection; attributes: Record<string, string>; unitId: string; warehouseId: string; zoneId: string
  quantity: string; rawLength: string; weight: string; selectionLoading: boolean; selectionError: string
}
type Vm = {
  rows: Row[]; form: { remark: string }; direction: string; sectionFilter: string
  catalogs: Record<string, MaterialCatalog[]>; ready: boolean; firstError: string; submitting: boolean; blocked: boolean
  chooseMaterial: (row: Row, id: string) => Promise<void>; chooseColor: (row: Row, id: string) => void
  sectionChanged: (category: SampleMaterialCategory) => void
  attributeChanged: (row: Row, key: string) => void; addRow: () => void; copyRow: (row: Row) => void; removeRow: (row: Row) => void
  loadPageOptions: () => Promise<void>; submit: () => Promise<void>; rowError: (row: Row) => string
  hasField: (row: Row, key: string) => boolean; valuesFor: (row: Row, key: string) => string[]
  unitsFor: (row: Row) => Array<{ id: string; unit_name: string }>
}
const categories: Record<string, SampleMaterialCategory> = { TUBE: 'tube', FABRIC: 'fabric', HARDWARE: 'hardware', PLASTIC: 'plastic', PACKAGING: 'packaging', AUXILIARY: 'accessory' }
const templates = [
  ['TUBE', 'TUBE', 'material,shape,section_size,thickness,length,color'],
  ['FABRIC', 'FABRIC', 'material,fabric_spec,width,color'],
  ['HARDWARE', 'HARDWARE', 'material,color,specification,size,thread'],
  ['PLASTIC', 'PLASTIC', 'material,color,specification,model,size'],
  ['PACKAGING', 'CARTON', 'material,size,model,layers'],
  ['PACKAGING', 'BAG', 'material,size,model,thickness'],
  ['PACKAGING', 'PACKAGING_GENERAL', 'material,specification,model'],
  ['AUXILIARY', 'TAPE', 'material,specification,width'],
  ['AUXILIARY', 'COTTON', 'material,specification,thickness,width'],
  ['AUXILIARY', 'AUXILIARY_GENERAL', 'material,specification'],
] as const
let definitions: MaterialCatalogOptions
let details: Record<string, MaterialCatalog>
let publicData: Record<string, PublicMaterialOptions>
const wrappers: ReturnType<typeof mount>[] = []

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>(done => { resolve = done })
  return { promise, resolve }
}
beforeEach(() => {
  vi.resetAllMocks()
  for (const method of ['error', 'warning', 'success'] as const) vi.spyOn(ElMessage, method).mockImplementation(() => ({ close: vi.fn() }))
  definitions = { categories: [], units: [], warehouses: [], spray_fields: [] }
  details = {}; publicData = {}
  for (const [category, template, keys] of templates) {
    let group = definitions.categories.find(item => item.key === category)
    if (!group) { group = { key: category, label: category, templates: [] }; definitions.categories.push(group) }
    const fields: MaterialFieldDefinition[] = keys.split(',').map(key => ({ key, label: key === 'length' ? '长度' : key, kind: 'text' }))
    group.templates.push({ key: template, label: template, supports_spray: false, fields })
    details[template] = { id: template, name: template, category_key: category, template_key: template, updated_at: 'v1', spray_enabled: false, values: [], units: [], base_warehouse_id: 'w1', semi_warehouse_id: null }
    publicData[template] = {
      category_key: category, template_key: template, scope: 'BASE', fields: fields.map(field => ({ ...field, source: 'public', manage_url: '' })),
      values: fields.map(field => ({ id: field.key, scope: 'BASE', field_key: field.key, value: field.key + '-value', parent_id: field.key === 'section_size' ? 'shape' : null })),
      units: [{ id: category === 'TUBE' ? 'root' : 'kg', unit_name: category === 'TUBE' ? '根' : 'KG' }],
    }
  }
  vi.mocked(sourceApi.fetchInboundMaterialOptions).mockImplementation(async () => definitions)
  vi.mocked(sourceApi.fetchInboundMaterials).mockImplementation(async query => ({ data: Object.values(details).filter(item => item.category_key === query.category), meta: { page: 1, page_size: 100, total: 1, total_pages: 1 } }))
  vi.mocked(sourceApi.fetchInboundMaterial).mockImplementation(async id => ({ data: details[id]! }))
  vi.mocked(sourceApi.fetchInboundPublicOptions).mockImplementation(async query => publicData[query.template_key]!)
  vi.mocked(api.fetchMaterialReceivingOptions).mockResolvedValue({ warehouses: [{ id: 'w1', warehouse_number: 'W1', warehouse_name: '材料仓', warehouse_type: 'MATERIAL' }, { id: 'w2', warehouse_number: 'W2', warehouse_name: '其他材料仓', warehouse_type: 'MATERIAL' }], zones: [{ id: 'z1', warehouse: 'w1', zone_name: '一区' }, { id: 'z2', warehouse: 'w2', zone_name: '二区' }] } as never)
  vi.mocked(api.createMaterialTransfer).mockResolvedValue({ transfer_number: 'TF001' } as never)
})
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()); vi.restoreAllMocks() })
async function render() {
  const wrapper = mount(MaterialTransferForm, { global: { plugins: [ElementPlus], stubs: { ElDatePicker: true } } })
  wrappers.push(wrapper); await flushPromises()
  return { wrapper, vm: wrapper.vm as unknown as Vm }
}
async function choose(vm: Vm, template = 'HARDWARE') {
  vm.sectionChanged(categories[details[template]!.category_key]!)
  const row = vm.rows[0]!
  await vm.chooseMaterial(row, template)
  row.quantity = '2'; row.rawLength = '6'; row.weight = '7.25'; vm.form.remark = '盘点'
  await flushPromises()
  return row
}

describe('材料收发表格契约（真实组件、模拟请求边界）', () => {
  it('公共候选和单位可在品名历史选项为空时选择，管材不混入其他单位', async () => {
    publicData.TUBE!.units.push({ id: 'meter', unit_name: '米' })
    const { vm } = await render()
    const row = await choose(vm)
    expect(row.catalog!.units).toEqual([])
    expect(row.unitId).toBe('kg'); expect(vm.ready).toBe(true)
    expect(sourceApi.fetchInboundPublicOptions).toHaveBeenCalledWith({ category_key: 'HARDWARE', template_key: 'HARDWARE', scope: 'BASE' })
    const tube = await choose(vm, 'TUBE')
    expect(vm.unitsFor(tube)).toEqual([{ id: 'root', unit_name: '根' }])
  })

  it('加载超过100条目录的后续页，后页材料可以选择', async () => {
    const all = Array.from({ length: 187 }, (_, index) => ({ ...details.PLASTIC!, id: 'plastic-' + index }))
    all.forEach(item => { details[item.id] = item })
    vi.mocked(sourceApi.fetchInboundMaterials).mockImplementation(async query => {
      const page = query.page || 1
      return { data: query.category === 'PLASTIC' ? all.slice((page - 1) * 100, page * 100) : [], meta: { page, page_size: 100, total: query.category === 'PLASTIC' ? 187 : 0, total_pages: query.category === 'PLASTIC' ? 2 : 0 } }
    })
    const { vm } = await render()
    expect(vm.catalogs.PLASTIC).toHaveLength(187)
    expect(sourceApi.fetchInboundMaterials).toHaveBeenCalledWith({ category: 'PLASTIC', page: 2, page_size: 100 })
    vm.sectionChanged('plastic'); await vm.chooseMaterial(vm.rows[0]!, 'plastic-186')
    expect(vm.rows[0]!.catalog!.id).toBe('plastic-186')
  })

  it('同名不同色卡保留独立颜色身份，复制保留身份且清空数量重量', async () => {
    publicData.FABRIC!.values = publicData.FABRIC!.values.filter(item => item.field_key !== 'color').concat([
      { id: 'c1', product_color_id: 'c1', color_card: 'A', color_code: '01', color_name: '红', scope: 'BASE', field_key: 'color', value: '红', parent_id: null },
      { id: 'c2', product_color_id: 'c2', color_card: 'B', color_code: '02', color_name: '红', scope: 'BASE', field_key: 'color', value: '红', parent_id: null },
    ])
    const { vm, wrapper } = await render()
    const row = await choose(vm, 'FABRIC')
    const colorSelect = wrapper.findAllComponents(ElSelect).find(item => item.props('placeholder') === '色卡 / 色号 / 颜色')!
    await colorSelect.get('.el-select__wrapper').trigger('click'); await flushPromises()
    const colors = colorSelect.findAllComponents(ElOption)
    expect(colors.map(item => item.props('label'))).toEqual(['A - 01 - 红', 'B - 02 - 红'])
    await colors.find(item => item.props('value') === 'c2')!.trigger('click'); await flushPromises()
    vm.copyRow(row)
    const copy = vm.rows[1]!
    expect(copy).toMatchObject({ catalogId: 'FABRIC', color: { product_color_id: 'c2', color_card: 'B', color_code: '02', color_name: '红' }, unitId: 'kg', warehouseId: 'w1', zoneId: 'z1', quantity: '', weight: '', rawLength: '6' })
    copy.attributes.material = ''
    expect(row.attributes.material).toBe('material-value')
    vm.removeRow(copy); await vm.submit()
    expect(api.createMaterialTransfer).toHaveBeenCalledWith(expect.objectContaining({ items: [expect.objectContaining({ material_selection: expect.objectContaining({ product_color_id: 'c2', color_card: 'B', color_code: '02', color_name: '红' }) })] }))
  })

  it.each(templates.map(([category, template]) => [category, template]))('%s/%s按实际模板校验必要属性', async (_category, template) => {
    const { vm } = await render()
    const row = await choose(vm, template)
    expect(vm.rowError(row)).toBe('')
    row.attributes = {}
    expect(vm.rowError(row)).toMatch(/必要属性|规格、尺寸或型号/)
  })

  it.each([['HARDWARE', 'size'], ['HARDWARE', 'thread'], ['PLASTIC', 'model'], ['PLASTIC', 'size'], ['CARTON', 'model'], ['BAG', 'size'], ['PACKAGING_GENERAL', 'model'], ['TAPE', 'width'], ['COTTON', 'thickness'], ['AUXILIARY_GENERAL', 'specification']])('%s允许以%s作为实际材料身份', async (template, field) => {
    const { vm } = await render()
    const row = await choose(vm, template)
    row.attributes = { [field]: field + '-value' }
    expect(vm.rowError(row)).toBe('')
  })

  it('清空选填属性时不提交空字符串，形状切换清除不匹配规格', async () => {
    publicData.TUBE!.values.push({ id: 'shape2', scope: 'BASE', field_key: 'shape', value: '圆管', parent_id: null }, { id: 's2', scope: 'BASE', field_key: 'section_size', value: '20', parent_id: 'shape2' })
    const { vm } = await render()
    const hardware = await choose(vm)
    hardware.attributes.color = ''
    expect(vm.ready).toBe(true); await vm.submit()
    expect(vi.mocked(api.createMaterialTransfer).mock.calls[0]![0].items[0]!.material_selection.attributes).not.toHaveProperty('color')
    const tube = await choose(vm, 'TUBE')
    tube.attributes.shape = 'shape-value'; tube.attributes.section_size = 'section_size-value'
    tube.attributes.shape = '圆管'; vm.attributeChanged(tube, 'shape')
    expect(tube.attributes.section_size).toBe(''); expect(vm.valuesFor(tube, 'section_size')).toEqual(['20'])
    tube.attributes.shape = ''; vm.attributeChanged(tube, 'shape'); expect(vm.valuesFor(tube, 'section_size')).toEqual([])
  })

  it('删除BOM长度列，管材单根长度直接输入米数并提交到库存', async () => {
    const { vm, wrapper } = await render()
    const row = await choose(vm, 'TUBE')
    const headers = wrapper.findAll('th').map(header => header.text())
    expect(headers).not.toContain('长度')
    expect(headers).toContain('单根长度（米）')
    expect(wrapper.find('input[aria-label="第 1 行长度（毫米）"]').exists()).toBe(false)
    const lengthInput = wrapper.find('input[aria-label="第 1 行单根长度（米）"]')
    expect(lengthInput.exists()).toBe(true)
    expect(wrapper.findAllComponents(ElSelect).some(item => item.props('placeholder') === '长度')).toBe(false)
    await lengthInput.setValue('6.05')
    expect(row.rawLength).toBe('6.05')
    expect(vm.rowError(row)).toBe('')
    await vm.submit()
    expect(vi.mocked(api.createMaterialTransfer).mock.calls[0]![0].items[0]).toMatchObject({ raw_bar_length_m: '6.05', material_selection: { attributes: expect.objectContaining({ length: '6050' }) } })
  })

  it('单一分区下所有新增行沿用顶部选择，不提供行内分区切换', async () => {
    const { vm, wrapper } = await render()
    vm.sectionChanged('hardware')
    await vm.chooseMaterial(vm.rows[0]!, 'HARDWARE')
    vm.addRow(); await flushPromises()
    expect(vm.rows.every(row => row.category === 'hardware')).toBe(true)
    expect(wrapper.findAll('[aria-label="分区"]')).toHaveLength(1)
    expect(wrapper.findAll('tbody tr')[0]!.findAll('td')).not.toHaveLength(0)
  })

  it('先选A再选B，A的迟到详情不会覆盖B', async () => {
    const slow = deferred<{ data: MaterialCatalog }>()
    details.second = { ...details.HARDWARE!, id: 'second', base_warehouse_id: 'w2' }
    const normal = vi.mocked(sourceApi.fetchInboundMaterial).getMockImplementation()!
    vi.mocked(sourceApi.fetchInboundMaterial).mockImplementation(id => id === 'HARDWARE' ? slow.promise : normal(id))
    const { vm } = await render(); vm.sectionChanged('hardware')
    const row = vm.rows[0]!
    const first = vm.chooseMaterial(row, 'HARDWARE'); await flushPromises()
    await vm.chooseMaterial(row, 'second'); slow.resolve({ data: details.HARDWARE! }); await first
    expect(row.catalogId).toBe('second'); expect(row.catalog!.id).toBe('second'); expect(row.warehouseId).toBe('w2')
  })

  it('迟到的公共属性不会覆盖新选模板，失败行不能提交', async () => {
    const slow = deferred<PublicMaterialOptions>()
    const normal = vi.mocked(sourceApi.fetchInboundPublicOptions).getMockImplementation()!
    vi.mocked(sourceApi.fetchInboundPublicOptions).mockImplementation(query => query.template_key === 'CARTON' ? slow.promise : normal(query))
    const { vm } = await render(); vm.sectionChanged('packaging'); const row = vm.rows[0]!
    const first = vm.chooseMaterial(row, 'CARTON'); await flushPromises()
    await vm.chooseMaterial(row, 'BAG'); slow.resolve(publicData.CARTON!); await first
    expect(row.catalog!.template_key).toBe('BAG'); expect(row.publicOptions!.template_key).toBe('BAG')
    vi.mocked(sourceApi.fetchInboundMaterial).mockRejectedValueOnce(new Error('读取失败'))
    await vm.chooseMaterial(row, 'PACKAGING_GENERAL'); expect(vm.rowError(row)).toBe('读取失败'); expect(vm.ready).toBe(false)
  })

  it('刷新重新读取目录、已选版本和公共候选，保留数量备注并更新默认仓', async () => {
    const { vm } = await render(); const row = await choose(vm)
    const oldCount = vi.mocked(sourceApi.fetchInboundMaterials).mock.calls.length
    details.HARDWARE = { ...details.HARDWARE!, updated_at: 'v2', base_warehouse_id: 'w2' }
    publicData.HARDWARE = { ...publicData.HARDWARE!, units: [{ id: 'kg', unit_name: 'KG' }, { id: 'piece', unit_name: '个' }] }
    await vm.loadPageOptions()
    expect(sourceApi.fetchInboundMaterials).toHaveBeenCalledTimes(oldCount + 6)
    expect(row.catalog!.updated_at).toBe('v2'); expect(row.warehouseId).toBe('w2'); expect(row.zoneId).toBe('z2')
    expect(vm.unitsFor(row)).toHaveLength(2); expect(row.quantity).toBe('2'); expect(vm.form.remark).toBe('盘点')
  })

  it('刷新后的新版本不会被刷新前尚未返回的请求覆盖', async () => {
    const slow = deferred<{ data: MaterialCatalog }>()
    vi.mocked(sourceApi.fetchInboundMaterial).mockReturnValueOnce(slow.promise)
    const { vm } = await render(); vm.sectionChanged('hardware'); const row = vm.rows[0]!
    const selecting = vm.chooseMaterial(row, 'HARDWARE'); await flushPromises()
    const old = details.HARDWARE!
    details.HARDWARE = { ...old, updated_at: 'v2' }
    await vm.loadPageOptions()
    slow.resolve({ data: old }); await selecting
    expect(row.catalog!.updated_at).toBe('v2'); expect(row.selectionLoading).toBe(false)
  })

  it('连续录入同品名重新读取保存后的版本，已选单位只提交ID', async () => {
    const { vm } = await render()
    await choose(vm)
    await vm.submit()
    const first = vi.mocked(api.createMaterialTransfer).mock.calls[0]![0]
    expect(first.items[0]!.material_selection.unit_id).toBe('kg')
    expect(first.items[0]!.material_selection).not.toHaveProperty('unit_name')
    details.HARDWARE = { ...details.HARDWARE!, updated_at: 'v2' }
    await choose(vm)
    expect(sourceApi.fetchInboundMaterial).toHaveBeenCalledTimes(2)
    await vm.submit()
    expect(vi.mocked(api.createMaterialTransfer).mock.calls[1]![0].items[0]!.material_selection.catalog_version).toBe('v2')
  })

  it('换品名不继承旧仓；默认仓不可用时明确阻止保存', async () => {
    const { vm } = await render(); const row = await choose(vm)
    details.invalid = { ...details.HARDWARE!, id: 'invalid', base_warehouse_id: 'disabled-warehouse' }
    await vm.chooseMaterial(row, 'invalid')
    row.quantity = '2'
    expect(row.warehouseId).toBe(''); expect(row.zoneId).toBe('')
    expect(vm.rowError(row)).toContain('默认仓库不可用'); expect(vm.ready).toBe(false)
  })

  it('保存等待期间冻结所有编辑和增删复制，成功后建立新空行', async () => {
    const pending = deferred<never>()
    vi.mocked(api.createMaterialTransfer).mockReturnValueOnce(pending.promise)
    const { vm, wrapper } = await render(); const row = await choose(vm)
    const save = vm.submit(); await flushPromises()
    expect(vm.submitting).toBe(true)
    expect(wrapper.findAllComponents(ElSelect).every(item => item.props('disabled'))).toBe(true)
    expect(wrapper.findAllComponents(ElInput).every(item => item.props('readonly') || item.props('disabled'))).toBe(true)
    expect(wrapper.findAllComponents(ElButton).every(item => item.props('disabled'))).toBe(true)
    vm.addRow(); vm.copyRow(row); vm.removeRow(row); vm.sectionChanged('tube'); await vm.chooseMaterial(row, 'TUBE')
    expect(vm.rows).toHaveLength(1); expect(row.catalogId).toBe('HARDWARE')
    pending.resolve({ transfer_number: 'TF001' } as never); await save
    expect(vm.rows).toHaveLength(1); expect(vm.rows[0]!.catalogId).toBe('')
    expect(ElMessage.success).toHaveBeenCalledWith('入库已保存，单号 TF001')
  })

  it.each([new Error('timeout'), { __CANCEL__: true }])('业务错误保留草稿可改，网络结果不明或取消时锁定全部编辑：%s', async failure => {
    const { vm, wrapper } = await render(); const row = await choose(vm)
    vi.mocked(api.createMaterialTransfer).mockRejectedValueOnce({ response: { status: 400, data: { error: { message: '可用库存不足' } } } })
    await vm.submit(); expect(vm.blocked).toBe(false); expect(vm.rows[0]).toBe(row); expect(vm.form.remark).toBe('盘点')
    vi.mocked(api.createMaterialTransfer).mockRejectedValueOnce(failure)
    await vm.submit(); await flushPromises(); expect(vm.blocked).toBe(true)
    expect(wrapper.findAllComponents(ElSelect).every(item => item.props('disabled'))).toBe(true)
    vm.addRow(); expect(vm.rows).toHaveLength(1)
  })

  it('顶部只选一个分区，添加和复制不改变分区，切换分区清空旧行', async () => {
    const { vm } = await render(); const row = await choose(vm)
    vm.addRow(); vm.copyRow(row)
    expect(vm.rows).toHaveLength(3)
    expect(vm.rows.every(item => item.category === 'hardware')).toBe(true)
    vm.sectionChanged('fabric'); expect(vm.rows).toHaveLength(1); expect(vm.rows[0]).toMatchObject({ category: 'fabric', catalogId: '', quantity: '' })
  })

  it('未填写完整时点击保存才提示缺少的具体内容', async () => {
    const { wrapper, vm } = await render()
    const saveButton = wrapper.findAllComponents(ElButton).find(button => button.text().includes('保存入库'))!
    expect(vm.ready).toBe(false)
    expect(saveButton.props('disabled')).toBe(false)
    expect(wrapper.text()).not.toContain('请填写备注。')
    await saveButton.trigger('click')
    expect(ElMessage.warning).toHaveBeenCalledWith('请填写备注。')
  })
})
