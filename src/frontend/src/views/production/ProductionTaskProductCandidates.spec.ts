import { flushPromises, mount, shallowMount } from '@vue/test-utils'
import ElementPlus, { ElMessage } from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '@/api/productionTasks'
import type { InquiryItem } from '@/types/inquiry'
import InquiryProductDialog from '@/components/inquiries/InquiryProductDialog.vue'
import ProductCatalogSelection from '@/components/productCatalog/ProductCatalogSelection.vue'
import type { ProductCatalogSelectionOption } from '@/types/productCatalog'
import { emptyProductEntry } from '@/utils/productEntryDraft'
import type { ProductOption, ProductionTask, ProductionTaskOptions, ProductionTaskPatchInput } from '@/types/productionTask'
import ProductionTaskCreateView from './ProductionTaskCreateView.vue'
import ProductionTaskEditView from './ProductionTaskEditView.vue'

vi.mock('vue-router', () => ({
  useRoute: () => ({ name: 'production-task-manual-create', params: { taskId: 'task-1' }, query: {} }),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }), onBeforeRouteLeave: vi.fn(),
}))
vi.mock('@/components/InquiryWangEditor.vue', () => ({ default: { template: '<div />' } }))
vi.mock('@/api/productionTasks', async original => ({
  ...await original<typeof import('@/api/productionTasks')>(),
  fetchProductionTaskOptions: vi.fn(), fetchProductionTask: vi.fn(), updateProductionTask: vi.fn(), createProductionTask: vi.fn(),
}))

const productApi = vi.hoisted(() => ({ options: vi.fn() }))
vi.mock('@/api/productCatalog', () => ({ fetchProductCatalogSelectionOptions: productApi.options, productCatalogError: (error: Error) => error.message }))
const category = { id: 'category-1', category_name: '成品' }
const unit = { id: 'unit-1', unit_code: 'PCS', unit_name: '件' }
function product(overrides: Partial<ProductOption> = {}): ProductOption {
  return { id: 'product-1', product_number: 'P001', product_code: 'CODE-1', item_number: 'ITEM-1', product_name: '产品甲',
    specification: '规格一', category_id: category.id, default_unit_id: unit.id, unit_code: 'PCS', unit_name: '件', ...overrides }
}
function catalog(): ProductionTaskOptions {
  return { categories: [category], products: [product()], units: [unit], employees: [], salespeople: [], colors: [],
    currencies: [{ id: 'cny', code: 'CNY', name: '人民币', symbol: '¥' }], detail_template: [], recent_task_numbers: [] } as unknown as ProductionTaskOptions
}
function existingTask(): ProductionTask {
  return { id: 'task-1', task_number: 'HT-TEST', status: 'DRAFT', order_date: '2026-10-01', delivery_date: '2026-11-01',
    delivery_method: 'SINGLE', salesperson: { id: 'sales-1' }, followers: [{ id: 'follower-1', display_name: '跟单员' }],
    products: [{ id: 'line-old', product_id: 'product-1', product_name: '历史产品', specification: '历史规格', quantity: '7',
      unit_id: 'unit-old', unit_code: 'BOX', unit_name: '箱', currency_id: 'cny', currency_code: 'CNY', unit_price: '2.0000',
      exchange_rate: '1.00000000', local_unit_price: '2.0000', local_total_amount: '14.0000', images: [], details: [] }],
    delivery_batches: [], special_requirements_html: '',
  } as unknown as ProductionTask
}
function catalogProduct(overrides: Partial<ProductCatalogSelectionOption> = {}): ProductCatalogSelectionOption {
  return { id: 'catalog-1', name_id: 'name-1', name: '产品甲', category_id: category.id, category_name: category.category_name, product_code: 'CODE-NEW', item_number: 'ITEM-NEW', specification: '规格一', unit: '件', unit_id: 'unit-1', unit_code: 'PCS', scale: '', colors: [{ id: 'blue', value: '蓝色' }], materials: ['铝'], thicknesses: ['1.2'], updated_at: 'v2', catalog_version: 'v2', ...overrides }
}
const control = { props: ['modelValue', 'disabled'], emits: ['update:modelValue', 'change'], template: '<input :value="modelValue" :disabled="disabled" @input="$emit(\'update:modelValue\', $event.target.value)" @change="$emit(\'change\', $event.target.value)"/>' }
async function openCatalogDialog(confirm: (value: Confirmation) => void) {
  const dialog = mount(InquiryProductDialog, { props: { modelValue: true, item: { product_description: '', specification: '', color: '', material: '', quantity: '3', unit_code: '', target_unit_price: '12.3456', target_currency_code: 'CNY', expected_date: null, product_match_status: 'PENDING', notes: '' }, categories: [category], units: options.units, colors: [], currencies: [], canUpload: false, closeOnConfirm: false, scene: 'sales-order', quotationCurrency: 'CNY', onConfirm: confirm }, global: { stubs: { AppWindowDialog: { template: '<section><slot/><slot name="footer"/></section>' }, ElInput: control, ElSelect: control, ElDatePicker: control, ElOption: true, ElImage: true, ElIcon: true, ElButton: { template: '<button><slot/></button>' } } } })
  await flushPromises()
  return dialog
}

type Confirmation = { item: InquiryItem; imageChanged: boolean; imageFile: File | null; removeImage: boolean }
type CreatePage = { confirmManual: (value: Confirmation) => void; manualProducts: unknown[] }
type EditPage = {
  confirmProduct: (value: Confirmation) => void
  products: Array<{ quantity: string; unitName: string; payload: { unit_id: string | null } }>
  form: { delivery_date: string }; dirty: boolean; buildPatch: () => ProductionTaskPatchInput
  editProduct: (row?: unknown) => void; editorItem: InquiryItem
}
let options: ProductionTaskOptions
const wrappers: ReturnType<typeof shallowMount>[] = []
async function mountPages() {
  const create = shallowMount(ProductionTaskCreateView, { global: { plugins: [ElementPlus] } })
  const edit = shallowMount(ProductionTaskEditView, { global: { plugins: [ElementPlus] } })
  wrappers.push(create, edit)
  await flushPromises()
  return { create: create.vm as unknown as CreatePage, edit: edit.vm as unknown as EditPage }
}
beforeEach(() => {
  vi.clearAllMocks()
  options = catalog()
  productApi.options.mockResolvedValue({ categories: [{ id: category.id, name: category.category_name }], names: [{ id: 'name-1', category_id: category.id, name: '产品甲' }], products: [catalogProduct()] })
  vi.mocked(api.fetchProductionTaskOptions).mockImplementation(async () => options)
  vi.mocked(api.fetchProductionTask).mockImplementation(async () => ({ data: existingTask(), etag: '"v1"' }))
  vi.spyOn(ElMessage, 'warning').mockImplementation(() => ({ close: vi.fn() }))
})
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()); vi.restoreAllMocks() })

describe('生产任务创建与编辑的产品候选单位', () => {
  it('按品名规格选择唯一产品，在创建和编辑入口保存目录ID、属性和单位，不展示货号编码', async () => {
    options.products = []
    productApi.options.mockResolvedValue({ categories: [{ id: category.id, name: category.category_name }], names: [{ id: 'name-1', category_id: category.id, name: '产品甲' }], products: [catalogProduct(), catalogProduct({ id: 'other-category', name_id: 'other-name', category_id: 'category-2' })] })
    const pages = await mountPages()
    for (const confirm of [pages.create.confirmManual, pages.edit.confirmProduct]) {
      const dialog = await openCatalogDialog(confirm)
      expect(dialog.find('input[aria-label="产品库货号"]').exists()).toBe(false)
      expect(dialog.find('input[aria-label="产品库产品编码"]').exists()).toBe(false)
      await dialog.get('input[aria-label="产品库类别"]').setValue(category.id)
      await dialog.get('input[aria-label="产品库品名"]').setValue('name-1')
      await dialog.get('input[aria-label="产品库规格"]').setValue('规格一')
      dialog.vm.confirm()
      await flushPromises()
      expect(dialog.emitted('confirm')).toHaveLength(1)
      dialog.unmount()
    }
    expect(pages.create.manualProducts).toMatchObject([{ item: { product_id: null, product_catalog_id: 'catalog-1', product_unit_id: 'unit-1', item_number_snapshot: 'ITEM-NEW', product_selection: { catalog_version: 'v2', draft: { color_id: 'blue', material: '铝' } }, quantity: '3', target_unit_price: '12.3456' } }])
    expect(pages.edit.products[1]?.payload).toMatchObject({ product_id: null, product_catalog_id: 'catalog-1', unit_id: 'unit-1', product_selection: { catalog_version: 'v2', draft: { color_id: 'blue', material: '铝' } }, quantity: '3', unit_price: '12.3456' })
    pages.edit.editProduct(pages.edit.products[1])
    expect(pages.edit.editorItem.item_number_snapshot).toBe('ITEM-NEW')
    expect(ElMessage.warning).not.toHaveBeenCalled()
  })

  it('同品名规格对应多个货号时两入口保留草稿，不猜目录ID，货号编码留待BOM', async () => {
    const first = catalogProduct()
    const second = catalogProduct({ id: 'catalog-2', item_number: 'ITEM-SECOND', product_code: 'CODE-SECOND' })
    productApi.options.mockResolvedValue({ categories: [{ id: category.id, name: category.category_name }], names: [{ id: 'name-1', category_id: category.id, name: '产品甲' }], products: [second, first, catalogProduct({ id: 'other-category', name_id: 'other-name', category_id: 'category-2' })] })
    const pages = await mountPages()
    for (const confirm of [pages.create.confirmManual, pages.edit.confirmProduct]) {
      const dialog = await openCatalogDialog(confirm)
      await dialog.get('input[aria-label="产品库类别"]').setValue(category.id)
      await dialog.get('input[aria-label="产品库品名"]').setValue('name-1')
      await dialog.get('input[aria-label="产品库规格"]').setValue('规格一')
      const picker = dialog.findComponent(ProductCatalogSelection)
      expect(picker.emitted('selected')?.at(-1)?.[0]).toMatchObject({ product: { id: '' }, selection: { draft: { name_id: 'name-1', specification: '规格一', item_number: '', product_code: '', sources: { item_number: 'typed', product_code: 'typed' } } } })
      await dialog.get('input[aria-label="产品库单位"]').setValue(unit.id)
      await dialog.get('input[aria-label="产品库颜色"]').setValue('酒红')
      await dialog.get('input[aria-label="产品库材质"]').setValue('钢')
      dialog.vm.confirm()
      await flushPromises()
      expect(dialog.emitted('confirm')).toHaveLength(1)
      dialog.unmount()
    }
    const expectedSelection = { draft: { name_id: 'name-1', specification: '规格一', item_number: '', product_code: '', color_name: '酒红', material: '钢' } }
    expect(pages.create.manualProducts).toMatchObject([{ item: { product_catalog_id: null, product_unit_id: unit.id, product_selection: expectedSelection, quantity: '3', target_unit_price: '12.3456' } }])
    expect(pages.edit.products[1]?.payload).toMatchObject({ product_catalog_id: null, unit_id: unit.id, product_selection: expectedSelection, quantity: '3', unit_price: '12.3456' })
    expect(ElMessage.warning).not.toHaveBeenCalled()
    expect(api.createProductionTask).not.toHaveBeenCalled()
    expect(api.updateProductionTask).not.toHaveBeenCalled()
  })

  it('候选加载失败时保留历史行，数量单位和精确头字段PATCH不受影响', async () => {
    productApi.options.mockRejectedValueOnce(new Error('产品库暂不可用'))
    const { edit } = await mountPages()
    const dialog = await openCatalogDialog(edit.confirmProduct)
    expect(dialog.text()).toContain('产品库暂不可用')
    expect(edit.products[0]).toMatchObject({ quantity: '7', unitName: '箱', payload: { unit_id: 'unit-old' } })
    expect(edit.dirty).toBe(false)
    expect(edit.buildPatch()).toEqual({})
    edit.form.delivery_date = '2026-11-02'
    expect(edit.buildPatch()).toEqual({ delivery_date: '2026-11-02' })
    dialog.unmount()
  })

  it('候选有单位名称但有效单位字典缺失时，两入口仍拒绝确认产品', async () => {
    options.units = []
    const pages = await mountPages()
    const confirmation = { item: { product_id: 'product-1', product_unit_id: 'unit-1', unit_code: 'PCS', quantity: '1',
      target_unit_price: '2' } as InquiryItem, imageChanged: false, imageFile: null, removeImage: false }
    pages.create.confirmManual(confirmation)
    pages.edit.confirmProduct(confirmation)
    expect(pages.create.manualProducts).toHaveLength(0)
    expect(pages.edit.products).toHaveLength(1)
    expect(ElMessage.warning).toHaveBeenCalledTimes(2)
    expect(api.createProductionTask).not.toHaveBeenCalled()
    expect(api.updateProductionTask).not.toHaveBeenCalled()
  })

  it('新单位草稿在创建和编辑都保持空单位 ID、文字和来源，不提前匹配字典或创建档案', async () => {
    options.units = []
    const pages = await mountPages()
    const draft = { ...emptyProductEntry(), category_name: '成品', name: '定制椅', specification: '60×80', unit_name: '新单位', color_name: '酒红', material: '铝' }
    const confirmation = { item: { product_id: null, product_catalog_id: null, product_selection: { draft }, product_unit_id: null, unit_code: '',
      product_description: '定制椅', specification: '60×80', quantity: '3', target_unit_price: '12.3456', notes: '' } as InquiryItem,
    imageChanged: false, imageFile: null, removeImage: false }
    pages.create.confirmManual(confirmation)
    pages.edit.confirmProduct(confirmation)
    expect(pages.create.manualProducts).toMatchObject([{ item: { product_unit_id: null, product_selection: { draft } } }])
    expect(pages.edit.products[1]).toMatchObject({ unitName: '新单位', payload: { unit_id: null, product_selection: { draft }, quantity: '3', unit_price: '12.3456' } })
    pages.edit.editProduct(pages.edit.products[1])
    expect(pages.edit.editorItem.product_selection?.draft).toEqual(draft)
    expect(ElMessage.warning).not.toHaveBeenCalled()
    expect(api.createProductionTask).not.toHaveBeenCalled()
    expect(api.updateProductionTask).not.toHaveBeenCalled()
  })

  it('已有单位ID不会被排在前面的同编码记录覆盖', async () => {
    options.units = [{ id: 'other-unit', unit_code: 'PCS', unit_name: '其他单位' },
      { ...unit, unit_code: 'OLD', unit_name: '当前名称' }]
    const pages = await mountPages()
    const confirmation = { item: { product_id: 'product-1', product_unit_id: 'unit-1', unit_code: 'PCS', quantity: '1',
      target_unit_price: '2' } as InquiryItem, imageChanged: false, imageFile: null, removeImage: false }
    pages.create.confirmManual(confirmation)
    pages.edit.confirmProduct(confirmation)
    expect.soft(pages.create.manualProducts).toMatchObject([{ item: { product_unit_id: 'unit-1' } }])
    expect.soft(pages.edit.products).toHaveLength(2)
    expect.soft(pages.edit.products[1]?.payload.unit_id).toBe('unit-1')
    expect(ElMessage.warning).not.toHaveBeenCalled()
  })

  it('已有单位ID失效时拒绝确认，不按同编码记录换ID', async () => {
    options.units = [{ id: 'other-unit', unit_code: 'PCS', unit_name: '件' }]
    const pages = await mountPages()
    const confirmation = { item: { product_id: 'product-1', product_unit_id: 'unit-1', unit_code: 'PCS', quantity: '1',
      target_unit_price: '2' } as InquiryItem, imageChanged: false, imageFile: null, removeImage: false }
    pages.create.confirmManual(confirmation)
    pages.edit.confirmProduct(confirmation)
    expect.soft(pages.create.manualProducts).toHaveLength(0)
    expect.soft(pages.edit.products).toHaveLength(1)
    expect(ElMessage.warning).toHaveBeenCalledTimes(2)
    expect(api.createProductionTask).not.toHaveBeenCalled()
    expect(api.updateProductionTask).not.toHaveBeenCalled()
  })

  it.each([null, undefined])('无单位ID（%s）的手工录入仍可按已维护编码确认', async productUnitId => {
    const pages = await mountPages()
    const confirmation = { item: { product_id: null, product_unit_id: productUnitId, unit_code: 'PCS',
      product_description: '手工产品', specification: '手填规格', quantity: '1', target_unit_price: '2' } as InquiryItem,
    imageChanged: false, imageFile: null, removeImage: false }
    pages.create.confirmManual(confirmation)
    pages.edit.confirmProduct(confirmation)
    expect(pages.create.manualProducts).toMatchObject([{ item: { product_id: null, product_unit_id: 'unit-1' } }])
    expect(pages.edit.products).toHaveLength(2)
    expect(pages.edit.products[1]?.payload).toMatchObject({ product_id: null, unit_id: 'unit-1' })
    expect(ElMessage.warning).not.toHaveBeenCalled()
  })

})
