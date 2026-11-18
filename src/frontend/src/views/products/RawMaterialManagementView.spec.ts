import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import RawMaterialManagementView from './RawMaterialManagementView.vue'
import { ElMessageBox } from 'element-plus'
import type { MaterialCatalogDraft } from '@/types/materialCatalog'
import MaterialCatalogSelect from '@/components/products/MaterialCatalogSelect.vue'

const auth = vi.hoisted(() => ({ permissions: new Set<string>() }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ user: { is_superuser: false }, hasPermission: (key: string) => auth.permissions.has(key) }) }))
const api = vi.hoisted(() => ({
  fetchMaterialCatalogOptions: vi.fn(), fetchMaterialCatalogs: vi.fn(), fetchMaterialCatalog: vi.fn(),
  fetchPublicMaterialOptions: vi.fn(), createMaterialCatalog: vi.fn(), saveMaterialCatalog: vi.fn(),
}))
vi.mock('@/api/materialCatalog', async (original) => ({ ...await original<object>(), ...api }))

const fields = [
  { key: 'material', label: '材质', kind: 'text' }, { key: 'color', label: '颜色', kind: 'text' },
  { key: 'shape', label: '截面形状', kind: 'shape' }, { key: 'section_size', label: '规格', kind: 'dimension' },
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
  warehouses: [{ id: 'wh-base', warehouse_number: 'RAW', warehouse_name: '原料仓', warehouse_type: 'MATERIAL' }, { id: 'wh-semi', warehouse_number: 'SEMI', warehouse_name: '半成品仓', warehouse_type: 'SEMI_FINISHED' }],
  units: [{ id: 'unit-root', unit_name: '根' }, { id: 'unit-kg', unit_name: '公斤' }],
}
function detail(id = 'a', name = '铁管') {
  return { id, name, base_warehouse_id: null as string | null, semi_warehouse_id: null as string | null, category_key: 'TUBE', template_key: 'TUBE', spray_enabled: false, updated_at: '2026-10-16T00:00:00Z',
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
  await row(field, scope, parent).findComponent(MaterialCatalogSelect).setValue(value)
}

const meta = (total: number) => ({ page: 1, page_size: 50, total, total_pages: total ? 1 : 0 })
const save = async () => { await wrapper.get('[data-testid="save-catalog"]').trigger('click'); await flushPromises() }
const labels = (field: string, scope = 'BASE', parent = '') =>
  row(field, scope, parent).findAll('.option-label').map(item => item.text())
const lastDraft = () => api.saveMaterialCatalog.mock.lastCall![1] as MaterialCatalogDraft
const confirmed = 'confirm' as Awaited<ReturnType<typeof ElMessageBox.confirm>>

function respondToSave(catalog: ReturnType<typeof detail>) {
  api.saveMaterialCatalog.mockImplementation(async (_id: string, payload: MaterialCatalogDraft) => ({
    data: { ...catalog, ...payload }, etag: '"saved-2"',
  }))
}

beforeEach(() => {
  vi.resetAllMocks()
  auth.permissions = new Set(['view', 'add', 'change'].map(action => `material_catalog.${action}_materialcatalog`))
  api.fetchMaterialCatalogOptions.mockResolvedValue(definitions)
  api.fetchMaterialCatalogs.mockResolvedValue({ data: [detail(), detail('b', '扶手管')], meta: meta(2) })
  api.fetchMaterialCatalog.mockImplementation(async (id: string) => ({ data: detail(id, id === 'a' ? '铁管' : '扶手管'), etag: `"${id}-1"` }))
  api.fetchPublicMaterialOptions.mockImplementation(async query => ({ ...query, fields: [], values: [], units: [] }))
  respondToSave(detail())
})
afterEach(() => { wrapper?.unmount(); vi.restoreAllMocks(); vi.useRealTimers() })

describe('独立原料管理', () => {
  it('编辑已有属性保留原 ID，失焦不提交，顶部保存发送版本', async () => {
    await open()
    await row('color').get('[data-action="edit"]').trigger('click')
    const select = row('color').getComponent(MaterialCatalogSelect)
    expect(select.props('modelValue')).toBe('无颜色')
    await select.setValue('  黑色  ')
    await row('color').get('input').trigger('blur')
    expect(api.saveMaterialCatalog).not.toHaveBeenCalled()
    await save()
    expect(api.saveMaterialCatalog).toHaveBeenCalledWith('a', expect.anything(), '"a-1"')
    expect(lastDraft().values.filter(value => value.field_key === 'color')).toEqual([
      expect.objectContaining({ id: 'a-color', value: '黑色' }),
    ])
    expect(labels('color')).toEqual(['黑色'])
  })

  it('取消修改保留原值，删除暂存到顶部保存', async () => {
    await open()
    await row('color').get('[data-action="edit"]').trigger('click')
    await row('color').getComponent(MaterialCatalogSelect).setValue('黑色')
    await row('color').get('[aria-label="取消修改"]').trigger('click')
    expect(labels('color')).toEqual(['无颜色'])
    await row('color').get('[data-action="delete"]').trigger('click')
    expect(labels('color')).toEqual([])
    expect(api.saveMaterialCatalog).not.toHaveBeenCalled()
    await save()
    expect(lastDraft().values.map(value => value.id)).not.toContain('a-color')
  })

  it('单位改名保留原 ID 和作用域', async () => {
    await open()
    await row('unit').get('[data-action="edit"]').trigger('click')
    expect(row('unit').getComponent(MaterialCatalogSelect).props('modelValue')).toBe('根')
    await choose('修改可用单位', '公斤')
    await save()
    expect(lastDraft().units).toEqual([{ id: 'a-unit', scope: 'BASE', unit_name: '公斤' }])
  })

  it('形状改名后规格仍跟随原形状 ID', async () => {
    await open()
    const shape = row('section_size', 'BASE', 'a-round')
    await shape.get('.shape-label [data-action="edit"]').trigger('click')
    await shape.getComponent(MaterialCatalogSelect).setValue('椭圆管')
    await save()
    expect(lastDraft().values).toContainEqual(expect.objectContaining({ id: 'a-round', value: '椭圆管' }))
    expect(labels('section_size', 'BASE', 'a-round')).toContain('Φ16')
  })

  it('按模板显示规格归属，各形状单独维护', async () => {
    await open()
    expect(wrapper.get('[data-testid="material-names"]').text()).toContain('铁管')
    expect(labels('section_size', 'BASE', 'a-round')).toContain('Φ16')
    expect(labels('section_size', 'BASE', 'a-square')).not.toContain('Φ16')
    expect(row('shape').find('.option-chip').exists()).toBe(false)
    expect(wrapper.find('table').exists()).toBe(false)
  })

  it('顶部收集同时打开的属性框并采用服务器返回的版本', async () => {
    await open(); await draft('material', ' Q235 '); await draft('length', '6000')
    await save()
    expect(api.saveMaterialCatalog).toHaveBeenCalledTimes(1)
    expect(lastDraft().values).toEqual(expect.arrayContaining([
      expect.objectContaining({ field_key: 'material', value: 'Q235' }),
      expect.objectContaining({ field_key: 'length', value: '6000' }),
    ]))
    await draft('material', 'Q195'); await save()
    expect(api.saveMaterialCatalog.mock.lastCall![2]).toBe('"saved-2"')
  })

  it('空白与重复选项显示行内错误并保留草稿', async () => {
    await open(); await draft('color', '  '); await save()
    expect(row('color').get('[role="alert"]').text()).toContain('请输入')
    await row('color').getComponent(MaterialCatalogSelect).setValue('无颜色'); await save()
    expect(row('color').get('[role="alert"]').text()).toContain('已存在')
    expect(api.saveMaterialCatalog).not.toHaveBeenCalled()
  })

  it('新增规格记录正确的形状，删除不会影响其他尺寸', async () => {
    await open(); await draft('section_size', '20×20', 'BASE', 'a-square'); await save()
    expect(lastDraft().values).toContainEqual(expect.objectContaining({ parent_id: 'a-square', value: '20×20' }))
    await row('section_size', 'BASE', 'a-square').get('[aria-label="删除20×20"]').trigger('click')
    expect(api.saveMaterialCatalog).toHaveBeenCalledTimes(1)
    await save()
    expect(lastDraft().values.filter(value => value.field_key === 'section_size')).toEqual([
      expect.objectContaining({ parent_id: 'a-round', value: 'Φ16' }),
    ])
  })

  it('喷塑开关与喷塑单位整档保存，原单位保持独立', async () => {
    await open(); await wrapper.get('[data-testid="spray-enabled"]').setValue(true)
    await draft('unit', '公斤', 'SPRAY'); await save()
    expect(lastDraft().spray_enabled).toBe(true)
    expect(lastDraft().units).toEqual(expect.arrayContaining([
      expect.objectContaining({ scope: 'BASE', unit_name: '根' }), expect.objectContaining({ scope: 'SPRAY', unit_name: '公斤' }),
    ]))
    expect(api.createMaterialCatalog).not.toHaveBeenCalled()
  })

  const templates = [
    { category: 'HARDWARE', key: 'HARDWARE', name: '五金', field: 'flow_unit', label: '流转单位', value: '套', added: '箱', sibling: 'specification', siblingLabel: '规格', other: 'M8' },
    ...packagingTemplates.map(t => ({ category: 'PACKAGING', key: t.templateKey, name: t.label,
      field: 'box_type', label: '箱子形状', value: '扁形', added: '方形', sibling: t.sizeKey, siblingLabel: t.sizeLabel, other: t.sizeValue })),
    ...packagingTemplates.map(t => ({ category: 'PACKAGING', key: t.templateKey, name: t.label,
      field: 'model', label: '型号', value: '2.5MM', added: '10.1*7.6', sibling: t.sizeKey, siblingLabel: t.sizeLabel, other: t.sizeValue })),
    { category: 'FABRIC_SEMI', key: 'FABRIC_SEMI', name: '委外布面', field: 'width', label: '门幅', value: '1.5', added: '2.0', sibling: 'specification', siblingLabel: '规格', other: '45×50，包边' },
  ]
  it.each(templates)('$key 的 $label 保留文字，增删均不改变相邻属性或单位', async t => {
    const fields = [{ key: t.field, label: t.label, kind: 'text' }, { key: t.sibling, label: t.siblingLabel, kind: 'text' }, { key: 'unit', label: '可用单位', kind: 'unit' }]
    api.fetchMaterialCatalogOptions.mockResolvedValue({ ...definitions, categories: [
      { key: t.category, label: t.name, templates: [{ key: t.key, label: t.name, supports_spray: t.category === 'HARDWARE', fields }] },
    ] })
    const catalog = { ...detail(), category_key: t.category, template_key: t.key, values: [
      { id: 'field-old', field_key: t.field, scope: 'BASE', value: t.value, parent_id: null },
      { id: 'sibling', field_key: t.sibling, scope: 'BASE', value: t.other, parent_id: null },
    ] }
    api.fetchMaterialCatalog.mockResolvedValue({ data: catalog, etag: '"a-1"' })
    api.fetchMaterialCatalogs.mockResolvedValue({ data: [catalog], meta: meta(1) })
    respondToSave(catalog)
    await open()
    expect(row(t.field).get('.attribute-label').text()).toBe(t.label)
    if (t.field === 'flow_unit') expect(wrapper.find('[data-field="SPRAY:flow_unit:"]').exists()).toBe(false)
    await draft(t.field, t.added); await save()
    expect(labels(t.field)).toEqual([t.value, t.added])
    await row(t.field).get(`[aria-label="删除${t.value}"]`).trigger('click'); await save()
    expect(labels(t.field)).toEqual([t.added])
    expect(labels(t.sibling)).toEqual([t.other])
    expect(labels('unit')).toEqual(['根'])
  })

  it('写入期间禁止切换品名或重复提交', async () => {
    await open(); await draft('material', 'Q235')
    const pending = deferred<{ data: ReturnType<typeof detail>; etag: string }>()
    api.saveMaterialCatalog.mockReturnValueOnce(pending.promise)
    await save()
    expect((wrapper.get('button[data-catalog-id="b"]').element as HTMLButtonElement).disabled).toBe(true)
    expect((wrapper.get('[data-testid="save-catalog"]').element as HTMLButtonElement).disabled).toBe(true)
    expect(api.saveMaterialCatalog).toHaveBeenCalledTimes(1)
    pending.resolve({ data: detail(), etag: '"new"' }); await flushPromises()
    expect((wrapper.get('button[data-catalog-id="b"]').element as HTMLButtonElement).disabled).toBe(false)
  })

  it('旧详情晚到不会覆盖新选中品名', async () => {
    const slow = deferred<{ data: ReturnType<typeof detail>; etag: string }>()
    api.fetchMaterialCatalog.mockImplementation((id: string) => id === 'a' ? slow.promise : Promise.resolve({ data: detail('b', '扶手管'), etag: '"b-1"' }))
    await open(); await wrapper.get('button[data-catalog-id="b"]').trigger('click'); await flushPromises()
    slow.resolve({ data: detail(), etag: '"a-1"' }); await flushPromises()
    expect(labels('section_size', 'BASE', 'b-round')).toContain('Φ16')
    expect(wrapper.find('[data-field="BASE:section_size:a-round"]').exists()).toBe(false)
  })

  it.each([false, true])('保存取消未执行的筛选，保存失败=%s', async failed => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
    await open(); await draft('material', 'Q235')
    await wrapper.get('[aria-label="搜索品名"]').setValue('扶手')
    if (failed) api.saveMaterialCatalog.mockRejectedValueOnce(new Error('保存失败'))
    await save(); await vi.advanceTimersByTimeAsync(300); await flushPromises()
    expect(api.fetchMaterialCatalogs.mock.calls.every(([query]) => query.q === '')).toBe(true)
    expect((wrapper.get('[aria-label="搜索品名"]').element as HTMLInputElement).value).toBe('')
    expect(wrapper.get('button[data-catalog-id="a"]').attributes('aria-current')).toBe('true')
    if (failed) expect(labels('material')).toContain('Q235')
  })

  it('分类加载中不能打开旧列表项', async () => {
    await open()
    const pending = deferred<{ data: ReturnType<typeof detail>[]; meta: ReturnType<typeof meta> }>()
    api.fetchMaterialCatalogs.mockReturnValueOnce(pending.promise)
    await choose('原料类别', 'PACKAGING')
    expect((wrapper.get('button[data-catalog-id="b"]').element as HTMLButtonElement).disabled).toBe(true)
    pending.resolve({ data: [], meta: meta(0) }); await flushPromises()
    expect(wrapper.get('[data-testid="material-names"]').text()).toContain('暂无品名')
  })

  it('有尺寸的形状要确认删除，取消保留形状与规格', async () => {
    const confirm = vi.spyOn(ElMessageBox, 'confirm').mockRejectedValueOnce('cancel').mockResolvedValueOnce(confirmed)
    await open()
    await row('section_size', 'BASE', 'a-round').get('[aria-label="删除圆管"]').trigger('click'); await flushPromises()
    expect(labels('section_size', 'BASE', 'a-round')).toContain('Φ16')
    await row('section_size', 'BASE', 'a-round').get('[aria-label="删除圆管"]').trigger('click'); await flushPromises()
    expect(confirm).toHaveBeenCalledTimes(2)
    await save()
    const remaining = lastDraft().values.map(value => value.id)
    expect(remaining).not.toContain('a-round')
    expect(remaining).not.toContain('a-diameter')
    expect(lastDraft().values).toContainEqual(expect.objectContaining({ id: 'a-square' }))
  })

  it('版本冲突后保留多个草稿并禁止自动重试', async () => {
    await open(); await draft('material', 'Q235'); await draft('length', '6000')
    api.saveMaterialCatalog.mockRejectedValueOnce({ response: { status: 412 } })
    await save()
    expect(wrapper.get('[data-testid="version-warning"]').text()).toContain('重新读取')
    expect(labels('material')).toContain('Q235'); expect(labels('length')).toContain('6000')
    expect(api.saveMaterialCatalog).toHaveBeenCalledTimes(1)
    expect((wrapper.get('[data-testid="save-catalog"]').element as HTMLButtonElement).disabled).toBe(true)
  })

  it('放弃冲突草稿后读取最新版本，再次保存使用新版本', async () => {
    await open(); await draft('material', 'Q235')
    api.saveMaterialCatalog.mockRejectedValueOnce({ response: { status: 412 } })
    await save()
    vi.spyOn(ElMessageBox, 'confirm').mockResolvedValueOnce(confirmed)
    api.fetchMaterialCatalog.mockResolvedValue({ data: detail(), etag: '"latest"' })
    await wrapper.get('[data-testid="reload-detail"]').trigger('click'); await flushPromises()
    expect(labels('material')).toEqual([])
    await draft('material', 'Q195'); await save()
    expect(api.saveMaterialCatalog.mock.lastCall![2]).toBe('"latest"')
  })

  it('新增多模板品名按选中模板整档创建', async () => {
    await open(); await choose('原料类别', 'PACKAGING')
    await wrapper.get('[data-testid="create-name"]').trigger('click'); await flushPromises()
    await choose('品名模板', 'BAG')
    await wrapper.get('[aria-label="新品名"]').setValue('袋子')
    await draft('bag_type', '封口')
    api.createMaterialCatalog.mockResolvedValue({ data: { ...detail('c', '袋子'), category_key: 'PACKAGING', template_key: 'BAG' }, etag: '"c-1"' })
    await save()
    expect(api.createMaterialCatalog).toHaveBeenCalledWith(expect.objectContaining({
      name: '袋子', category_key: 'PACKAGING', template_key: 'BAG', values: [expect.objectContaining({ value: '封口' })],
    }))
    expect(api.saveMaterialCatalog).not.toHaveBeenCalled()
  })

  it('无查看权限不请求列表，只有查看权限时禁用编辑', async () => {
    auth.permissions.clear(); await open()
    expect(api.fetchMaterialCatalogOptions).not.toHaveBeenCalled()
    wrapper.unmount(); auth.permissions.add('material_catalog.view_materialcatalog'); await open()
    expect(labels('color')).toContain('无颜色')
    expect(wrapper.find('[data-testid="save-catalog"]').exists()).toBe(false)
    expect(row('color').find('[data-action="add"]').exists()).toBe(false)
  })

  it('未启用喷塑也能设置半成品仓，两种仓库分别保留', async () => {
    await open(); await choose('原料仓库', 'wh-base'); await choose('半成品仓库', 'wh-semi')
    expect(api.saveMaterialCatalog).not.toHaveBeenCalled()
    await save()
    expect(lastDraft()).toMatchObject({ base_warehouse_id: 'wh-base', semi_warehouse_id: 'wh-semi', spray_enabled: false })
    await wrapper.get('[data-testid="spray-enabled"]').setValue(true)
    await wrapper.get('[data-testid="spray-enabled"]').setValue(false); await save()
    expect(lastDraft().semi_warehouse_id).toBe('wh-semi')
  })

  it('公共单位候选可输入新文字，服务器拒绝后保留草稿', async () => {
    api.fetchPublicMaterialOptions.mockImplementation(async query => ({ ...query, fields: [], values: [], units: [{ unit_name: '公斤' }] }))
    await open(); await draft('unit', '箱')
    expect(row('unit').getComponent(MaterialCatalogSelect).props('options')).toEqual([{ value: '公斤', label: '公斤' }])
    api.saveMaterialCatalog.mockRejectedValueOnce(new Error('单位保存失败'))
    await save()
    expect(labels('unit')).toEqual(['根', '箱'])
    expect(wrapper.text()).toContain('单位保存失败')
  })

  it('直接裁片选仓只写入半成品仓库字段', async () => {
    const cutting = { ...detail(), name: '裁片', category_key: 'FABRIC_SEMI', template_key: 'FABRIC_SEMI' }
    api.fetchMaterialCatalogOptions.mockResolvedValue({ ...definitions, categories: [{
      key: 'FABRIC_SEMI', label: '裁片', templates: [{ key: 'FABRIC_SEMI', label: '裁片', supports_spray: false, fields: [] }],
    }] })
    api.fetchMaterialCatalog.mockResolvedValue({ data: cutting, etag: '"a-1"' })
    respondToSave(cutting)
    await open()
    expect(wrapper.findAllComponents(MaterialCatalogSelect).some(item => item.props('ariaLabel') === '原料仓库')).toBe(false)
    await choose('半成品仓库', 'wh-semi'); await save()
    expect(lastDraft()).toMatchObject({ base_warehouse_id: null, semi_warehouse_id: 'wh-semi' })
  })

  it('仓库写入失败保留两个选择，重试使用原版本', async () => {
    await open(); await choose('原料仓库', 'wh-base'); await choose('半成品仓库', 'wh-semi')
    api.saveMaterialCatalog.mockRejectedValueOnce(new Error('仓库保存失败'))
    await save()
    expect(wrapper.text()).toContain('仓库保存失败')
    expect(wrapper.findAllComponents(MaterialCatalogSelect).find(item => item.props('ariaLabel') === '原料仓库')!.props('modelValue')).toBe('wh-base')
    await save()
    expect(lastDraft()).toMatchObject({ base_warehouse_id: 'wh-base', semi_warehouse_id: 'wh-semi' })
    expect(api.saveMaterialCatalog.mock.lastCall![2]).toBe('"a-1"')
  })
})
