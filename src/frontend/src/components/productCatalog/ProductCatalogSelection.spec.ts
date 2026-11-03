import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { ElOption, ElSelect } from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ProductCatalogSelection from './ProductCatalogSelection.vue'
import type { ProductCatalogSelectionOption, ProductEntryField, ProductSelectionInput, ProductSelectionSnapshot } from '@/types/productCatalog'
import { emptyProductEntry } from '@/utils/productEntryDraft'
const api = vi.hoisted(() => ({ options: vi.fn() }))
vi.mock('@/api/productCatalog', () => ({ fetchProductCatalogSelectionOptions: api.options, productCatalogError: (error: Error) => error.message }))
const product: ProductCatalogSelectionOption = { id: 'p1', name_id: 'n1', name: '导演椅', category_id: 'c1', category_name: '成品', product_code: 'CODE', item_number: 'ITEM', specification: '50*60', unit: '件', unit_id: 'u1', unit_code: 'PCS', scale: '', colors: [{ id: 'blue', value: '蓝' }], materials: ['铝'], thicknesses: ['1.2'], catalog_version: 'v2', updated_at: 'v2' }
const snapshot: ProductSelectionSnapshot = { version: 1, catalog_id: 'p1', catalog_version: 'v1', name_id: 'n1', name: '历史品名', category_id: 'c1', category_name: '历史类别', product_code: 'OLD', item_number: 'OLD-ITEM', specification: '历史规格', scale: '', unit_id: 'u0', unit_name: '旧单位', unit_code: 'OLD', color_id: 'blue', color_name: '历史蓝', material: '历史材质', thickness: '0.5' }
const result = () => ({ categories: [{ id: 'c1', name: '成品' }], names: [{ id: 'n1', category_id: 'c1', name: '导演椅' }], products: [product], units: [{ id: 'u1', unit_name: '件', unit_code: 'PCS' }] })
const fields: ProductEntryField[] = ['category_name', 'name', 'item_number', 'specification', 'product_code', 'unit_name', 'color_name', 'material']
let wrapper: VueWrapper<InstanceType<typeof ProductCatalogSelection>>
async function open(props: { catalogId?: string | null; selection?: ProductSelectionInput | null; snapshot?: ProductSelectionSnapshot | null; showIdentifiers?: boolean } = {}) {
  wrapper = mount(ProductCatalogSelection, { attachTo: document.body, props: { catalogId: null, showIdentifiers: true, ...props, onSelected: ({ product, selection }) => { void wrapper.setProps({ catalogId: product.id || null, selection }) } } })
  await flushPromises()
}
function select(field: ProductEntryField) {
  const visible = fields.filter(key => wrapper.props('showIdentifiers') || !['item_number', 'product_code'].includes(key))
  return wrapper.findAllComponents(ElSelect)[visible.indexOf(field)]!
}
async function choose(field: ProductEntryField, value: string) {
  const control = select(field)
  await control.find('.el-select__wrapper').trigger('click')
  await control.findAllComponents(ElOption).find(option => option.props('value') === value)!.trigger('click')
  await flushPromises()
}
async function type(field: ProductEntryField, value: string) { await select(field).get('input').setValue(value) }
function last() { return wrapper.emitted('selected')!.at(-1)![0] as { product: ProductCatalogSelectionOption; selection: ProductSelectionInput } }
async function chooseProduct() { await choose('category_name', 'c1'); await choose('name', 'n1'); await choose('item_number', 'ITEM') }
beforeEach(() => { vi.resetAllMocks(); api.options.mockResolvedValue(result()); vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} }) })
afterEach(() => { wrapper?.unmount(); document.body.innerHTML = ''; vi.unstubAllGlobals() })
describe('逐项选填产品', () => {
  it('前序只显示六项，按品名规格选择保留真实编号且可以切换其他货号的规格', async () => {
    api.options.mockResolvedValue({ ...result(), products: [product, { ...product, id: 'p2', item_number: 'ITEM-2', product_code: 'CODE-2', specification: '80*90' }] })
    await open({ showIdentifiers: false })
    expect(wrapper.findAllComponents(ElSelect)).toHaveLength(6)
    expect(wrapper.text()).not.toContain('货号'); expect(wrapper.text()).not.toContain('产品编码')
    await choose('category_name', 'c1'); await choose('name', 'n1'); await choose('specification', '50*60')
    expect(last().product).toMatchObject({ id: 'p1', item_number: 'ITEM', product_code: 'CODE' })
    expect(last().selection.draft?.sources.item_number).toBe('selected')
    await choose('specification', '80*90')
    expect(last().product).toMatchObject({ id: 'p2', item_number: 'ITEM-2', product_code: 'CODE-2' })
    await type('specification', '全新规格'); wrapper.vm.commit(); await flushPromises()
    expect(last().product).toMatchObject({ id: '', item_number: '', product_code: '', specification: '全新规格' })
    expect(wrapper.vm.validate()).toBe('')
  })
  it('前序同品名规格有多个产品时不猜编号，留到BOM确认', async () => {
    api.options.mockResolvedValue({ ...result(), products: [product, { ...product, id: 'p2', item_number: 'ITEM-2', product_code: 'CODE-2' }] })
    await open({ showIdentifiers: false })
    await choose('category_name', 'c1'); await choose('name', 'n1'); await choose('specification', '50*60')
    expect(last().product).toMatchObject({ id: '', item_number: '', product_code: '' })
    expect(last().selection.draft?.sources.specification).toBe('typed')
  })
  it('货号规格分开，带出单值属性，不出现壁厚控件', async () => {
    await open(); expect(wrapper.emitted('selected')).toBeUndefined(); await chooseProduct()
    expect(last()).toMatchObject({ product: { id: 'p1', item_number: 'ITEM', specification: '50*60' }, selection: { catalog_version: 'v2', draft: { color_id: 'blue', material: '铝', sources: { color_name: 'selected', material: 'selected' } } } })
    expect(select('specification').exists()).toBe(true); expect(wrapper.text()).not.toContain('壁厚'); expect(wrapper.vm.validate({ final: true })).toBe('')
  })
  it('未按回车的新文字也能提交，来源与空ID保留，长单位不写编码', async () => {
    await open(); const values = ['定制类别', '定制椅', 'ITEM-NEW', '新规格', 'CODE-NEW', '新单位名称'.repeat(8), '酒红', '新材质']
    for (const [index, field] of fields.entries()) await type(field, values[index]!)
    expect(wrapper.vm.validate({ final: true })).toBe(''); await flushPromises()
    expect(last().product).toMatchObject({ id: '', unit_id: null, unit_code: '' })
    expect(last().selection.draft).toEqual({ ...emptyProductEntry(), ...Object.fromEntries(fields.map((field, i) => [field, values[i]])) })
    expect(api.options).toHaveBeenCalledTimes(1)
  })
  it('已有产品补颜色材质保留关联，重开保留手填来源和旧壁厚', async () => {
    await open(); await chooseProduct(); await wrapper.setProps({ selection: { ...last().selection, thickness: '0.5' } })
    await type('color_name', '酒红'); await type('material', '钢'); expect(wrapper.vm.validate()).toBe(''); await flushPromises()
    const saved = last()
    expect(saved).toMatchObject({ product: { id: 'p1' }, selection: { thickness: '0.5', draft: { color_id: null, color_name: '酒红', material: '钢', sources: { color_name: 'typed', material: 'typed' } } } })
    wrapper.unmount(); await open({ catalogId: 'p1', selection: saved.selection })
    expect(select('color_name').props('modelValue')).toBe('酒红'); expect(wrapper.props('selection')?.draft?.sources.color_name).toBe('typed'); expect(wrapper.emitted('selected')).toBeUndefined()
  })
  it('改类别清除下级关联，保留填写文字，不伪造ID', async () => {
    await open(); await chooseProduct(); await type('category_name', '新类别'); wrapper.vm.commit(); await flushPromises()
    expect(last()).toMatchObject({ product: { id: '', name_id: '', name: '导演椅' }, selection: { draft: { category_id: null, name_id: null, color_id: null, sources: { category_name: 'typed', name: 'typed', item_number: 'typed', color_name: 'typed' } } } })
  })
  it('等值初始草稿重渲染不覆盖未回车内容', async () => {
    await open(); const initial = { ...emptyProductEntry(), category_name: '成品', name: '椅', specification: '旧', unit_name: '件' }
    await wrapper.setProps({ initialDraft: initial }); await type('specification', '新'); await wrapper.setProps({ initialDraft: { ...initial, sources: { ...initial.sources } } })
    expect(wrapper.vm.validate()).toBe(''); expect(last().selection.draft?.specification).toBe('新')
  })
  it('旧快照只回显不覆盖，未重新选择不改历史', async () => {
    const original = JSON.stringify(snapshot); await open({ catalogId: 'p1', snapshot })
    expect(wrapper.text()).toContain('历史品名'); expect(wrapper.text()).toContain('旧单位'); expect(wrapper.vm.validate()).toBe(''); expect(wrapper.emitted('selected')).toBeUndefined(); expect(JSON.stringify(snapshot)).toBe(original)
  })
  it('上游允许缺货号编码，BOM核对要求两者填写', async () => {
    await open(); await wrapper.setProps({ initialDraft: { ...emptyProductEntry(), category_name: '成品', name: '椅', specification: '规格', unit_name: '件' } })
    expect(wrapper.vm.validate()).toBe(''); expect(wrapper.vm.validate({ final: true })).toContain('货号'); await type('item_number', 'I1'); expect(wrapper.vm.validate({ final: true })).toContain('产品编码')
  })
  it('正式确认后重开使用真实关联，不把旧输入来源的空ID重新提交', async () => {
    const confirmed: ProductSelectionSnapshot = { ...snapshot, entry_state: 'confirmed', entry_draft: { ...emptyProductEntry(), category_name: '历史类别', name: '历史品名' } }
    await open({ catalogId: 'p1', snapshot: confirmed }); await type('color_name', '新蓝'); wrapper.vm.commit(); await flushPromises()
    expect(last().selection.draft).toMatchObject({ category_id: 'c1', name_id: 'n1', unit_id: 'u0', sources: { category_name: 'selected', name: 'selected' } })
    expect(confirmed.entry_draft?.name_id).toBeNull()
  })
})
