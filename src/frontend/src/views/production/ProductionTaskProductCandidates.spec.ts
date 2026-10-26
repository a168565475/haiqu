import { flushPromises, shallowMount } from '@vue/test-utils'
import ElementPlus, { ElMessage } from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '@/api/productionTasks'
import type { InquiryItem, InquiryProductSelectionOptions } from '@/types/inquiry'
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
type Confirmation = { item: InquiryItem; imageChanged: boolean; imageFile: File | null; removeImage: boolean }
type CandidatePage = { loadProductionCandidates: (id: string) => Promise<InquiryProductSelectionOptions> }
type CreatePage = CandidatePage & { confirmManual: (value: Confirmation) => void; manualProducts: unknown[] }
type EditPage = CandidatePage & {
  confirmProduct: (value: Confirmation) => void
  products: Array<{ quantity: string; unitName: string; payload: { unit_id: string } }>
  form: { delivery_date: string }; dirty: boolean; buildPatch: () => ProductionTaskPatchInput
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
  vi.mocked(api.fetchProductionTaskOptions).mockImplementation(async () => options)
  vi.mocked(api.fetchProductionTask).mockImplementation(async () => ({ data: existingTask(), etag: '"v1"' }))
  vi.spyOn(ElMessage, 'warning').mockImplementation(() => ({ close: vi.fn() }))
})
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()); vi.restoreAllMocks() })

describe('生产任务创建与编辑的产品候选单位', () => {
  it.each([
    { label: '字典缺失', units: [] },
    { label: '字典同ID的显示字段不一致', units: [{ ...unit, unit_code: 'OLD', unit_name: '旧名称' }] },
  ])('$label 时两入口保留产品提供的单位字段和真实ID', async ({ units }) => {
    options.units = units
    const pages = await mountPages()
    for (const page of [pages.create, pages.edit]) {
      const result = await page.loadProductionCandidates(category.id)
      expect(result.groups[0].specifications[0].products[0]).toMatchObject({
        id: 'product-1', unit_id: 'unit-1', unit_code: 'PCS', unit_name: '件',
      })
    }
  })

  it.each([
    { fields: { unit_code: undefined, unit_name: undefined }, expected: { unit_code: 'PCS', unit_name: '件' } },
    { fields: { unit_code: '', unit_name: '产品单位名称' }, expected: { unit_code: 'PCS', unit_name: '产品单位名称' } },
  ])('产品未提供的单位字段才按ID回退字典：$fields', async ({ fields, expected }) => {
    options.products = [product(fields)]
    const pages = await mountPages()
    for (const page of [pages.create, pages.edit]) {
      const result = await page.loadProductionCandidates(category.id)
      expect(result.groups[0].specifications[0].products[0]).toMatchObject({ unit_id: 'unit-1', ...expected })
    }
  })

  it('两种来源都缺失时不编造单位，也不按同名单位替换产品的单位ID', async () => {
    options.products = [product({ unit_code: undefined, unit_name: undefined })]
    options.units = [{ id: 'other-unit', unit_code: 'PCS', unit_name: '件' }]
    const pages = await mountPages()
    for (const page of [pages.create, pages.edit]) {
      const result = await page.loadProductionCandidates(category.id)
      expect(result.groups[0].specifications[0].products[0]).toMatchObject({ unit_id: 'unit-1', unit_code: '', unit_name: '' })
    }
  })

  it('保留类别筛选、同名同规格的全部产品ID以及接口首次出现顺序', async () => {
    options.products = [product({ id: 'p2', specification: '规格二' }), product({ id: 'p3', product_name: '产品乙' }),
      product({ id: 'p4', specification: '规格二' }), product({ id: 'p5', specification: '规格一' }),
      product({ id: 'other-category', category_id: 'category-2' })]
    const original = JSON.stringify(options)
    const pages = await mountPages()
    const created = await pages.create.loadProductionCandidates(category.id)
    const edited = await pages.edit.loadProductionCandidates(category.id)
    const shape = (result: InquiryProductSelectionOptions) => result.groups.map(group => [group.product_name,
      group.specifications.map(spec => [spec.specification, spec.products.map(item => item.id)])])
    expect(shape(created)).toEqual([['产品甲', [['规格二', ['p2', 'p4']], ['规格一', ['p5']]]], ['产品乙', [['规格一', ['p3']]]]])
    expect(shape(edited)).toEqual(shape(created))
    expect(JSON.stringify(options)).toBe(original)
  })

  it('不可用类别在两入口都拒绝，空类别返回空候选', async () => {
    options.products = []
    const pages = await mountPages()
    for (const page of [pages.create, pages.edit]) {
      await expect(page.loadProductionCandidates('missing')).rejects.toThrow('产品类别不存在或不可用')
      await expect(page.loadProductionCandidates(category.id)).resolves.toEqual({ category, groups: [] })
    }
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

  it('加载当前候选不重写历史行单位或数量，也不将未编辑产品带入头字段PATCH', async () => {
    const { edit } = await mountPages()
    await edit.loadProductionCandidates(category.id)
    expect(edit.products[0]).toMatchObject({ quantity: '7', unitName: '箱', payload: { unit_id: 'unit-old' } })
    expect(edit.dirty).toBe(false)
    expect(edit.buildPatch()).toEqual({})
    edit.form.delivery_date = '2026-11-02'
    expect(edit.buildPatch()).toEqual({ delivery_date: '2026-11-02' })
  })
})
