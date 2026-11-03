import { DOMWrapper, flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import InquiryProductDialog from './InquiryProductDialog.vue'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import type { InquiryItem } from '@/types/inquiry'
import ProductCatalogSelection from '@/components/productCatalog/ProductCatalogSelection.vue'

const catalogApi = vi.hoisted(() => ({ options: vi.fn() }))
vi.mock('@/api/productCatalog', () => ({ fetchProductCatalogSelectionOptions: catalogApi.options, productCatalogError: (error: Error) => error.message }))
const catalogProduct = { id: 'catalog1', name_id: 'name1', name: '三折床', category_id: 'cat1', category_name: '成品', product_code: 'C1', item_number: 'I1', specification: '186*55*24cm', unit: '张', unit_id: 'u1', unit_code: 'PCS', scale: '', colors: [{ id: 'blue', value: '深宝蓝' }], materials: ['铝'], thicknesses: [], catalog_version: 'v1', updated_at: 'v1' }
async function selectMaterial(wrapper: ReturnType<typeof mount>) {
  wrapper.findComponent(ProductCatalogSelection).vm.$emit('selected', { product: catalogProduct, selection: { catalog_version: 'v1', color_id: 'blue', material: '铝' } })
  await flushPromises()
}

vi.mock('@/api/inquiries', () => ({
  fetchInquiryProductSelectionOptions: vi.fn().mockResolvedValue({ groups: [] }),
  inquiryProductImageUrl: () => '',
}))

const item: InquiryItem = {
  product_id: 'p1', product_category_id: 'c1', product_unit_id: 'u1', product_color_id: 'color1',
  product_description: '三折床', specification: '186*55*24cm', unit_code: 'PCS',
  color: '深宝蓝', material: 'PE', quantity: '1000', target_unit_price: null,
  target_currency_code: '', expected_date: null, product_match_status: 'MATCHED', notes: '',
}
const control = { props: ['modelValue', 'disabled'], emits: ['update:modelValue', 'change'], template: '<input :value="modelValue" :disabled="disabled" @input="$emit(\'update:modelValue\', $event.target.value)" @change="$emit(\'change\', $event.target.value)" />' }
const wrappers: ReturnType<typeof mount>[] = []
function open(reviewed = false) {
  const wrapper = mount(InquiryProductDialog, {
    attachTo: document.body,
    props: { modelValue: true, item: { ...item }, scene: 'bom', reviewed, closeOnConfirm: false,
      categories: [{ id: 'c1', category_name: '成品' }], units: [{ id: 'u1', unit_code: 'PCS', unit_name: '张' }],
      colors: [{ id: 'color1', color_name: '深宝蓝' }], currencies: [], canUpload: false },
    global: { stubs: { ElInput: control, ElSelect: control, ElOption: true, ElDatePicker: control,
      ElButton: { props: ['disabled'], template: '<button :disabled="disabled"><slot /></button>' } } },
  })
  wrappers.push(wrapper)
  return wrapper
}
const body = () => new DOMWrapper(document.body)
const button = (label: string) => body().findAll('button').find(row => row.text() === label)!
beforeEach(() => { vi.clearAllMocks(); catalogApi.options.mockResolvedValue({ categories: [{ id: 'cat1', name: '成品' }], names: [{ id: 'name1', category_id: 'cat1', name: '三折床' }], products: [catalogProduct] }) })
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()); document.body.innerHTML = '' })

describe('BOM 产品核对关闭保护', () => {
  it('货号编码只在BOM核对场景展示', async () => {
    const wrapper = open()
    await flushPromises()
    expect(wrapper.findComponent(ProductCatalogSelection).props('showIdentifiers')).toBe(true)
    for (const scene of ['inquiry', 'quotation', 'sales-order'] as const) {
      await wrapper.setProps({ scene })
      expect(wrapper.findComponent(ProductCatalogSelection).props('showIdentifiers')).toBe(false)
    }
  })
  it('未核对时所有关闭途径和最小化都不能绕回用料页', async () => {
    const wrapper = open()
    await flushPromises()
    expect(body().find('[aria-label="关闭"]').exists()).toBe(false)
    expect(body().find('[aria-label="最小化"]').exists()).toBe(false)
    expect(button('取消').attributes('disabled')).toBeDefined()
    await button('取消').trigger('click')
    await body().get('.app-window-overlay').trigger('click')
    await body().get('.app-window-overlay').trigger('keydown', { key: 'Escape' })
    wrapper.findComponent(AppWindowDialog).vm.$emit('update:modelValue', false)
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
    expect(document.body.style.overflow).toBe('hidden')
  })

  it('已核对未修改可以关闭，修改后取消和 Esc 必须被拦截', async () => {
    const unchanged = open(true)
    await flushPromises()
    await button('取消').trigger('click')
    expect(unchanged.emitted('update:modelValue')).toEqual([[false]])
    unchanged.unmount(); wrappers.pop()
    const changed = open(true)
    await flushPromises()
    await selectMaterial(changed)
    expect(button('取消').attributes('disabled')).toBeDefined()
    expect(body().find('[aria-label="关闭"]').exists()).toBe(false)
    expect(body().find('[aria-label="最小化"]').exists()).toBe(false)
    await body().get('.app-window-overlay').trigger('keydown', { key: 'Escape' })
    expect(changed.emitted('update:modelValue')).toBeUndefined()
  })

  it('确认只发请求事件；保存失败保留输入和关闭保护，再次确认仍可提交', async () => {
    const wrapper = open()
    await flushPromises()
    await selectMaterial(wrapper)
    await button('保存本次产品核对').trigger('click')
    expect(wrapper.emitted('confirm')).toHaveLength(1)
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
    await wrapper.setProps({ busy: true })
    await button('保存本次产品核对').trigger('click')
    expect(wrapper.emitted('confirm')).toHaveLength(1)
    await wrapper.setProps({ busy: false, saveError: '版本冲突，请重试' })
    expect(wrapper.findComponent(ProductCatalogSelection).props('selection')?.draft?.material).toBe('铝')
    expect(button('取消').attributes('disabled')).toBeDefined()
    expect(body().text()).toContain('版本冲突')
    await button('保存本次产品核对').trigger('click')
    expect(wrapper.emitted('confirm')).toHaveLength(2)
    await wrapper.setProps({ modelValue: false, reviewed: true })
    expect(body().get('.app-window-overlay').isVisible()).toBe(false)
  })

  it('字典失败可以原地重试，输入不重置', async () => {
    catalogApi.options.mockRejectedValueOnce(new Error('读取失败'))
    open()
    await flushPromises()
    await body().get('input[aria-label="产品库材质"]').setValue('铝')
    const retry = button('重新读取')
    expect(retry).toBeDefined()
    await retry.trigger('click')
    await flushPromises()
    expect(catalogApi.options).toHaveBeenCalledTimes(2)
    expect((body().get('input[aria-label="产品库材质"]').element as HTMLInputElement).value).toBe('铝')
  })

  it('普通询盘仍允许取消与最小化', async () => {
    const wrapper = open()
    await wrapper.setProps({ scene: 'inquiry' })
    await flushPromises()
    expect(body().find('[aria-label="最小化"]').exists()).toBe(true)
    await button('取消').trigger('click')
    expect(wrapper.emitted('update:modelValue')).toEqual([[false]])
  })
})
