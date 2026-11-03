import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { defineComponent } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ProductManagementView from './ProductManagementView.vue'
import type { ProductCatalog } from '@/types/productCatalog'

const auth = vi.hoisted(() => ({ permissions: new Set<string>() }))
const confirm = vi.hoisted(() => vi.fn())
const guards = vi.hoisted(() => ({ leave: vi.fn(), update: vi.fn() }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: (key: string) => auth.permissions.has(key) }) }))
vi.mock('vue-router', () => ({ onBeforeRouteLeave: guards.leave, onBeforeRouteUpdate: guards.update }))
vi.mock('element-plus', async original => ({ ...await original<object>(), ElMessageBox: { confirm } }))
const api = vi.hoisted(() => ({
  fetchProductCatalogOptions: vi.fn(), fetchProductCatalogNames: vi.fn(), fetchProductCatalogEditor: vi.fn(),
  createProductCatalogEditor: vi.fn(), saveProductCatalogEditor: vi.fn(), deleteProductCatalogName: vi.fn(),
}))
vi.mock('@/api/productCatalog', async original => ({ ...await original<object>(), ...api }))
const name = (id = 'n1', text = '桌子', count = 1, category = 'cat1') => ({ id, name: text, category_id: category, category_name: '家具', product_count: count, updated_at: '2026-10-31' })
const product = (id = 'p1'): ProductCatalog => ({ id, name_id: 'n1', name: '桌子', category_id: 'cat1', category_name: '家具', product_code: 'P001', item_number: 'H001', specification: '120×80', unit: '', scale: '常规', colors: [{ id: 'color1', value: '白色' }], materials: [], thicknesses: [], updated_at: '2026-10-31' })
const editor = (products = [product()], group = name(), etag = '"editor1"') => ({ data: { name: { ...group, product_count: products.length }, products }, etag })
const SelectStub = defineComponent({
  props: ['modelValue', 'options', 'ariaLabel', 'disabled', 'placeholder'],
  emits: ['update:modelValue', 'change'],
  template: '<select :value="modelValue" :aria-label="ariaLabel" :disabled="disabled" @change="$emit(\'update:modelValue\', $event.target.value); $emit(\'change\', $event.target.value)"><option value="">{{ placeholder }}</option><option v-for="option in options" :key="option.value" :value="option.value" :disabled="option.disabled">{{ option.label }}</option></select>',
})
const SaveStub = defineComponent({
  props: ['label', 'ariaLabel', 'loading', 'disabled'],
  emits: ['click'],
  template: '<button :aria-label="ariaLabel" :disabled="disabled || loading" :aria-busy="loading" @click="$emit(\'click\', $event)">{{ label }}</button>',
})
let wrapper: VueWrapper
async function setup() {
  wrapper = mount(ProductManagementView, { attachTo: document.body, global: { stubs: { MaterialCatalogSelect: SelectStub, ProductCatalogSaveButton: SaveStub } } })
  await flushPromises()
}
const row = (id = 'p1') => wrapper.get(`[data-product-id="${id}"]`)
const save = async () => { await wrapper.get('[data-action="save-draft"]').trigger('click'); await flushPromises() }
beforeEach(() => {
  vi.resetAllMocks()
  confirm.mockResolvedValue('confirm')
  auth.permissions = new Set(['view', 'add', 'change'].map(action => `product_catalog.${action}_productcatalog`))
  api.fetchProductCatalogOptions.mockResolvedValue({ categories: [{ id: 'cat1', name: '家具', name_count: 2 }, { id: 'cat2', name: '配件', name_count: 0 }], units: ['套', '件'], scales: ['常规', '定制'] })
  api.fetchProductCatalogNames.mockResolvedValue([name(), name('n2', '椅子')])
  api.fetchProductCatalogEditor.mockImplementation(async (id: string) => id === 'n1' ? editor() : editor([], name(id, '椅子')))
  api.saveProductCatalogEditor.mockResolvedValue(editor())
  api.createProductCatalogEditor.mockResolvedValue(editor([], name('n3', '新桌子')))
  api.deleteProductCatalogName.mockResolvedValue(undefined)
})
afterEach(() => { wrapper?.unmount(); document.body.innerHTML = ''; vi.useRealTimers() })

describe('产品管理整组草稿', () => {
  it('品名和原字段、多值只有顶部保存一次提交，未 blur 的最后输入也收集', async () => {
    await setup()
    await wrapper.get('[aria-label="品名"]').setValue('新桌子')
    await row().get('[aria-label="货号"]').setValue('H002')
    for (const [label, value] of [['颜色', '黑色'], ['材质', '铝'], ['壁厚', '1.2']]) {
      await row().get(`[aria-label="添加${label}"]`).trigger('click')
      await row().findAll(`[data-field="${label === '颜色' ? 'colors' : label === '材质' ? 'materials' : 'thicknesses'}"] input`).at(-1)!.setValue(value)
    }
    await row().get('[aria-label="货号"]').trigger('blur')
    await row().get('[aria-label="壁厚1"]').trigger('keydown', { key: 'Enter' })
    expect(api.saveProductCatalogEditor).not.toHaveBeenCalled()
    expect(wrapper.findAll('[data-action="save-draft"]')).toHaveLength(1)
    expect(wrapper.find('.catalog-sidebar [data-action="save-draft"]').exists()).toBe(false)
    api.saveProductCatalogEditor.mockResolvedValue(editor([{ ...product(), item_number: 'H002', materials: ['铝'], thicknesses: ['1.2'] }], name('n1', '新桌子'), '"editor2"'))
    await save()
    expect(api.saveProductCatalogEditor).toHaveBeenCalledExactlyOnceWith('n1', {
      name: '新桌子', products: [{ id: 'p1', product_code: 'P001', item_number: 'H002', specification: '120×80', unit: '', scale: '常规', colors: ['白色', '黑色'], materials: ['铝'], thicknesses: ['1.2'] }], delete_product_ids: [],
    }, '"editor1"')
    expect(wrapper.get('button[data-name-id="n1"] .product-name-label').text()).toBe('新桌子')
  })

  it('新增空框不验证，顶部保存处理空值和重复，删除一框保留其他框', async () => {
    await setup()
    await row().get('[aria-label="添加材质"]').trigger('click')
    await row().get('[aria-label="添加材质"]').trigger('click')
    expect(row().findAll('[data-field="materials"] input')).toHaveLength(2)
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    await row().get('[aria-label="材质1"]').setValue('铝')
    await save()
    expect(wrapper.text()).toContain('请填写或删除空的材质输入框')
    expect(api.saveProductCatalogEditor).not.toHaveBeenCalled()
    await row().get('[aria-label="材质2"]').setValue(' 铝 ')
    await save()
    expect(wrapper.text()).toContain('材质不能重复')
    await row().get('[aria-label="删除材质2"]').trigger('click')
    expect((row().get('[aria-label="材质1"]').element as HTMLInputElement).value).toBe('铝')
    await save()
    expect(api.saveProductCatalogEditor.mock.calls[0]![1].products[0].materials).toEqual(['铝'])
  })

  it('同组完整加载一次，跨50条分页编辑、新增和删除均保留，只提交改动行', async () => {
    const all = Array.from({ length: 51 }, (_, index) => product(`p${index + 1}`))
    api.fetchProductCatalogEditor.mockResolvedValue(editor(all))
    await setup()
    expect(wrapper.findAll('[data-product-id]')).toHaveLength(50)
    expect(wrapper.get('button[data-name-id="n1"] .product-name-count').text()).toBe('51')
    await row().get('[aria-label="规格"]').setValue('第一页暂存')
    await row('p2').get('[aria-label="删除产品"]').trigger('click')
    await wrapper.get('[data-action="add-product"]').trigger('click'); await flushPromises()
    await wrapper.get('[data-new-product] [aria-label="货号"]').setValue('新增货号')
    await wrapper.get('[aria-label="上一页产品"]').trigger('click')
    expect((row().get('[aria-label="规格"]').element as HTMLInputElement).value).toBe('第一页暂存')
    expect(api.fetchProductCatalogEditor).toHaveBeenCalledTimes(1)
    expect(api.saveProductCatalogEditor).not.toHaveBeenCalled()
    await save()
    const payload = api.saveProductCatalogEditor.mock.calls[0]![1]
    expect(payload.products).toHaveLength(2)
    expect(payload.products[0]).toMatchObject({ id: 'p1', specification: '第一页暂存' })
    expect(payload.products[1]).toMatchObject({ item_number: '新增货号', colors: [], materials: [], thicknesses: [] })
    expect(payload.products[1]).not.toHaveProperty('id')
    expect(payload.products[1]).not.toHaveProperty('key')
    expect(payload.delete_product_ids).toEqual(['p2'])
  })

  it('新增品名在右侧同一保存入口提交，失败保留全部草稿', async () => {
    await setup()
    await wrapper.get('[data-action="add-name"]').trigger('click')
    expect(wrapper.find('.catalog-sidebar input[aria-label="新品名"]').exists()).toBe(false)
    await wrapper.get('[aria-label="品名"]').setValue('新桌子')
    await wrapper.get('[data-action="add-product"]').trigger('click')
    await wrapper.get('[data-new-product] [aria-label="货号"]').setValue('NEW')
    api.createProductCatalogEditor.mockRejectedValueOnce(new Error('网络错误'))
    await save()
    expect(wrapper.text()).toContain('网络错误')
    expect((wrapper.get('[aria-label="品名"]').element as HTMLInputElement).value).toBe('新桌子')
    expect((wrapper.get('[data-new-product] [aria-label="货号"]').element as HTMLInputElement).value).toBe('NEW')
    await save()
    expect(api.createProductCatalogEditor).toHaveBeenCalledTimes(2)
    expect(api.createProductCatalogEditor.mock.calls[0]![0]).toMatchObject({ category_id: 'cat1', name: '新桌子', products: [{ item_number: 'NEW' }] })
    expect(wrapper.get('button[data-name-id="n3"]').attributes('aria-current')).toBe('true')
  })

  it.each([400, 403, 412, 428])('%s 保存错误不丢草稿，版本冲突不自动读取或偷偷重试', async status => {
    await setup()
    await row().get('[aria-label="规格"]').setValue('未保存规格')
    api.saveProductCatalogEditor.mockRejectedValue({ response: { status, data: { detail: '保存失败' } } })
    await save()
    expect((row().get('[aria-label="规格"]').element as HTMLInputElement).value).toBe('未保存规格')
    expect(api.fetchProductCatalogEditor).toHaveBeenCalledTimes(1)
    expect(wrapper.find('[role="alert"]').exists()).toBe(true)
    if ([412, 428].includes(status)) {
      confirm.mockRejectedValueOnce('cancel')
      await wrapper.get('[data-action="reload"]').trigger('click'); await flushPromises()
      expect(api.fetchProductCatalogEditor).toHaveBeenCalledTimes(1)
      expect((row().get('[aria-label="规格"]').element as HTMLInputElement).value).toBe('未保存规格')
      await wrapper.get('[data-action="reload"]').trigger('click'); await flushPromises()
      expect(api.fetchProductCatalogEditor).toHaveBeenCalledTimes(2)
    }
  })

  it('品名切换、路由更新和离开均提示，取消保稿，保存中不允许离开', async () => {
    await setup()
    await row().get('[aria-label="货号"]').setValue('草稿')
    confirm.mockRejectedValueOnce('cancel')
    await wrapper.get('button[data-name-id="n2"]').trigger('click'); await flushPromises()
    expect((row().get('[aria-label="货号"]').element as HTMLInputElement).value).toBe('草稿')
    confirm.mockRejectedValueOnce('cancel')
    expect(await guards.update.mock.calls[0]![0]()).toBe(false)
    const event = new Event('beforeunload', { cancelable: true })
    window.dispatchEvent(event)
    expect(event.defaultPrevented).toBe(true)
    let finish!: (value: unknown) => void
    api.saveProductCatalogEditor.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    await wrapper.get('[data-action="save-draft"]').trigger('click'); await flushPromises()
    expect(await guards.leave.mock.calls[0]![0]()).toBe(false)
    expect(wrapper.get('button[data-name-id="n2"]').attributes('disabled')).toBeDefined()
    finish(editor()); await flushPromises()
    expect(await guards.leave.mock.calls[0]![0]()).toBe(true)
    await wrapper.get('button[data-name-id="n2"]').trigger('click'); await flushPromises()
    expect(api.fetchProductCatalogEditor).toHaveBeenLastCalledWith('n2')
  })

  it('整品名删除确认显示全分页数量，取消不删除，引用阻止删除仍保留草稿', async () => {
    api.fetchProductCatalogEditor.mockResolvedValue(editor(Array.from({ length: 51 }, (_, index) => product(`p${index + 1}`))))
    await setup()
    await row().get('[aria-label="规格"]').setValue('保留草稿')
    confirm.mockRejectedValueOnce('cancel')
    await wrapper.get('[aria-label="删除品名桌子"]').trigger('click'); await flushPromises()
    expect(confirm.mock.calls[0]![0]).toContain('全部 51 条产品')
    expect(api.deleteProductCatalogName).not.toHaveBeenCalled()
    api.deleteProductCatalogName.mockRejectedValueOnce(new Error('已有业务引用，不能删除'))
    await wrapper.get('[aria-label="删除品名桌子"]').trigger('click'); await flushPromises()
    expect(api.deleteProductCatalogName).toHaveBeenCalledWith('n1', '"editor1"')
    expect(wrapper.text()).toContain('已有业务引用')
    expect((row().get('[aria-label="规格"]').element as HTMLInputElement).value).toBe('保留草稿')
    expect(wrapper.find('button button').exists()).toBe(false)
  })

  it('成功删除当前整品名后移除左侧记录并打开下一品名', async () => {
    await setup()
    await wrapper.get('[aria-label="删除品名桌子"]').trigger('click'); await flushPromises()
    expect(wrapper.find('button[data-name-id="n1"]').exists()).toBe(false)
    expect(wrapper.get('button[data-name-id="n2"]').attributes('aria-current')).toBe('true')
    expect(api.fetchProductCatalogEditor).toHaveBeenLastCalledWith('n2')
  })

  it('只读不提供写入口，ADD-only可新建但不能改旧组，CHANGE-only可删而不能新增', async () => {
    auth.permissions = new Set(['product_catalog.view_productcatalog'])
    await setup()
    expect(row().find('input').exists()).toBe(false)
    expect(wrapper.find('[data-action="save-draft"]').exists()).toBe(false)
    expect(wrapper.find('[aria-label="删除品名桌子"]').exists()).toBe(false)
    wrapper.unmount()
    auth.permissions.add('product_catalog.add_productcatalog')
    await setup()
    expect(wrapper.find('[data-action="add-product"]').exists()).toBe(false)
    await wrapper.get('[data-action="add-name"]').trigger('click')
    expect(wrapper.find('[data-action="save-draft"]').exists()).toBe(true)
    expect(wrapper.find('[data-action="add-product"]').exists()).toBe(true)
    wrapper.unmount()
    auth.permissions = new Set(['product_catalog.view_productcatalog', 'product_catalog.change_productcatalog'])
    await setup()
    expect(wrapper.find('[data-action="add-name"]').exists()).toBe(false)
    expect(wrapper.find('[data-action="add-product"]').exists()).toBe(false)
    expect(wrapper.find('[aria-label="删除品名桌子"]').exists()).toBe(true)
  })

  it('无查看权限不读取数据', async () => {
    auth.permissions.clear()
    await setup()
    expect(wrapper.text()).toContain('无权查看')
    expect(api.fetchProductCatalogOptions).not.toHaveBeenCalled()
  })

  it('单位只从维护候选选择，旧单位原文保留并可保存其他字段', async () => {
    api.fetchProductCatalogEditor.mockResolvedValue(editor([{ ...product(), unit: ' 旧箱/套 ' }]))
    await setup()
    const unit = row().get('[aria-label="单位"]')
    expect(unit.findAll('option').map(option => option.text())).toContain('套')
    expect(unit.findAll('option').find(option => option.text() === '旧箱/套')?.attributes('disabled')).toBeDefined()
    await row().get('[aria-label="货号"]').setValue('H2')
    await save()
    expect(api.saveProductCatalogEditor.mock.calls[0]![1].products[0].unit).toBe(' 旧箱/套 ')
    await row().get('[aria-label="单位"]').setValue('件')
    await save()
    expect(api.saveProductCatalogEditor.mock.calls[1]![1].products[0].unit).toBe('件')
  })

  it('缺少ETag不得保存；重新读取之前输入保持', async () => {
    api.fetchProductCatalogEditor.mockResolvedValue(editor([product()], name(), ''))
    await setup()
    await row().get('[aria-label="规格"]').setValue('草稿')
    await save()
    expect(wrapper.text()).toContain('未取得品名编辑版本')
    expect(api.saveProductCatalogEditor).not.toHaveBeenCalled()
    expect((row().get('[aria-label="规格"]').element as HTMLInputElement).value).toBe('草稿')
  })

  it('较早详情迟到不覆盖新选择，失败不冒充成功内容', async () => {
    let finishOld!: (value: unknown) => void
    api.fetchProductCatalogEditor.mockImplementationOnce(() => new Promise(resolve => { finishOld = resolve }))
      .mockResolvedValueOnce(editor([], name('n2', '椅子')))
    await setup()
    await wrapper.get('button[data-name-id="n2"]').trigger('click'); await flushPromises()
    finishOld(editor()); await flushPromises()
    expect((wrapper.get('[aria-label="品名"]').element as HTMLInputElement).value).toBe('椅子')
    expect(wrapper.find('[data-product-id="p1"]').exists()).toBe(false)
    api.fetchProductCatalogEditor.mockRejectedValueOnce(new Error('读取失败'))
    await wrapper.get('button[data-name-id="n1"]').trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('读取失败')
    expect(wrapper.find('[data-product-id="p1"]').exists()).toBe(false)
    expect(wrapper.get('[data-action="save-draft"]').attributes('disabled')).toBeDefined()
  })

  it('搜索应用取消重复防抖，拒绝筛选时还原关键词和草稿', async () => {
    await setup()
    vi.useFakeTimers()
    api.fetchProductCatalogNames.mockClear()
    await wrapper.get('[aria-label="搜索品名"]').setValue('折叠桌')
    await wrapper.get('.erp-list-filter-actions').findAll('button')[1]!.trigger('click'); await flushPromises()
    await vi.advanceTimersByTimeAsync(250)
    expect(api.fetchProductCatalogNames).toHaveBeenCalledExactlyOnceWith({ category_id: 'cat1', q: '折叠桌' })
    await row().get('[aria-label="规格"]').setValue('草稿')
    confirm.mockRejectedValueOnce('cancel')
    await wrapper.get('[aria-label="搜索品名"]').setValue('椅子')
    await vi.advanceTimersByTimeAsync(250); await flushPromises()
    expect((wrapper.get('[aria-label="搜索品名"]').element as HTMLInputElement).value).toBe('折叠桌')
    expect((row().get('[aria-label="规格"]').element as HTMLInputElement).value).toBe('草稿')
  })

  it('类别切换需要放弃确认，迟到的旧类别结果忽略', async () => {
    await setup()
    await row().get('[aria-label="规格"]').setValue('草稿')
    confirm.mockRejectedValueOnce('cancel')
    await wrapper.get('[aria-label="产品类别"]').setValue('cat2'); await flushPromises()
    expect(api.fetchProductCatalogNames).toHaveBeenCalledTimes(1)
    expect((row().get('[aria-label="规格"]').element as HTMLInputElement).value).toBe('草稿')
    let finishOld!: (value: unknown) => void
    api.fetchProductCatalogNames.mockImplementationOnce(() => new Promise(resolve => { finishOld = resolve })).mockResolvedValueOnce([name()])
    await wrapper.get('[aria-label="产品类别"]').setValue('cat2'); await flushPromises()
    await wrapper.get('[aria-label="产品类别"]').setValue('cat1'); await flushPromises()
    finishOld([name('old', '旧类别', 0, 'cat2')]); await flushPromises()
    expect(wrapper.text()).not.toContain('旧类别')
    expect(wrapper.find('button[data-name-id="n1"]').exists()).toBe(true)
  })
})
