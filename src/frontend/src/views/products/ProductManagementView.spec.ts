import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ProductManagementView from './ProductManagementView.vue'
import MaterialCatalogSelect from '@/components/products/MaterialCatalogSelect.vue'

const auth = vi.hoisted(() => ({ permissions: new Set<string>() }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: (key: string) => auth.permissions.has(key) }) }))
const api = vi.hoisted(() => ({
  fetchProductCatalogOptions: vi.fn(), fetchProductCatalogNames: vi.fn(), fetchProductCatalogs: vi.fn(),
  fetchProductCatalog: vi.fn(), createProductCatalog: vi.fn(), updateProductCatalog: vi.fn(),
  fetchProductCatalogName: vi.fn(), createProductCatalogName: vi.fn(), updateProductCatalogName: vi.fn(),
  addProductCatalogColor: vi.fn(), deleteProductCatalogColor: vi.fn(),
}))
vi.mock('@/api/productCatalog', async original => ({ ...await original<object>(), ...api }))
const name = (id = 'n1', text = '桌子') => ({ id, name: text, category_id: 'cat1', category_name: '家具', product_count: 1, updated_at: '2026-10-16' })
const product = (id = 'p1') => ({ id, name_id: 'n1', name: '桌子', category_id: 'cat1', category_name: '家具', product_code: 'P001', item_number: 'H001', specification: '120×80', unit: '', scale: '常规', colors: [{ id: 'color1', value: '白色' }], updated_at: '2026-10-16', created_at: '2026-10-16', source: null })
const page = (data = [product()], current = 1, total = data.length) => ({ data, meta: { page: current, page_size: 50, total, total_pages: Math.ceil(total / 50) } })
let wrapper: VueWrapper
const row = () => wrapper.get('[data-product-id="p1"]')
const field = (key: string) => row().get(`[data-field="${key}"]`)
async function setup() { wrapper = mount(ProductManagementView, { attachTo: document.body }); await flushPromises() }
async function edit(key: string, value: string) {
  await field(key).get('[data-action="edit"]').trigger('click'); await flushPromises()
  await field(key).get('input').setValue(value)
}
beforeEach(() => {
  vi.resetAllMocks()
  auth.permissions = new Set(['view', 'add', 'change'].map(action => `product_catalog.${action}_productcatalog`))
  api.fetchProductCatalogOptions.mockResolvedValue({ categories: [{ id: 'cat1', name: '家具', name_count: 2 }, { id: 'cat2', name: '配件', name_count: 0 }], units: ['套'], scales: ['常规', '定制'] })
  api.fetchProductCatalogNames.mockResolvedValue([name(), name('n2', '椅子')])
  api.fetchProductCatalogs.mockResolvedValue(page())
  api.fetchProductCatalog.mockResolvedValue({ data: product(), etag: '"v1"' })
  api.fetchProductCatalogName.mockResolvedValue({ data: name(), etag: '"n1"' })
})
afterEach(() => { wrapper?.unmount(); document.body.innerHTML = ''; vi.useRealTimers() })

describe('独立产品管理', () => {
  it('类别显示全部品名数，品名显示产品总数，搜索不缩减类别计数', async () => {
    api.fetchProductCatalogNames.mockResolvedValue([name(), { ...name('n2', '椅子'), product_count: 0 }])
    api.fetchProductCatalogs.mockResolvedValue(page([product()], 1, 51))
    await setup()
    expect(wrapper.get('[data-name-id="n1"] .product-name-count').text()).toBe('51')
    expect(wrapper.get('[data-name-id="n2"] .product-name-count').text()).toBe('0')
    await wrapper.get('.catalog-sidebar .el-select__wrapper').trigger('click'); await flushPromises()
    expect(document.querySelector('[data-category-count="cat1"]')?.textContent).toBe('2')
    expect(document.querySelector('[data-category-count="cat2"]')?.textContent).toBe('0')
    api.fetchProductCatalogNames.mockResolvedValue([name()])
    vi.useFakeTimers()
    await wrapper.get('[aria-label="搜索品名"]').setValue('桌子')
    await vi.advanceTimersByTimeAsync(250); await flushPromises()
    expect(wrapper.findAll('.product-name-count')).toHaveLength(1)
    expect(document.querySelector('[data-category-count="cat1"]')?.textContent).toBe('2')
  })

  it('完整显示品名，按所选品名分页产品，重复字段的产品仍各占一行', async () => {
    api.fetchProductCatalogNames.mockResolvedValue(Array.from({ length: 105 }, (_, index) => name(`n${index + 1}`, `品名${index + 1}`)))
    api.fetchProductCatalogs.mockResolvedValueOnce(page([product(), product('p2')], 1, 51)).mockResolvedValueOnce(page([product('p51')], 2, 51))
    await setup()
    expect(wrapper.get('[data-testid="product-names"]').findAll('[data-name-id]')).toHaveLength(105)
    expect(wrapper.findAll('[data-product-id]')).toHaveLength(2)
    expect(row().text()).toContain('无单位')
    await wrapper.get('[aria-label="下一页产品"]').trigger('click'); await flushPromises()
    expect(api.fetchProductCatalogs).toHaveBeenLastCalledWith({ name_id: 'n1', page: 2, page_size: 50 })
    expect(wrapper.find('[data-product-id="p51"]').exists()).toBe(true)
  })

  it('字段只有点击保存才写入，成功刷新值且保留单位原文', async () => {
    await setup(); await edit('unit', ' 箱/套 ')
    await field('unit').get('input').trigger('blur')
    expect(api.updateProductCatalog).not.toHaveBeenCalled()
    api.updateProductCatalog.mockResolvedValue({ data: { ...product(), unit: ' 箱/套 ' }, etag: '"v2"' })
    await field('unit').get('[data-action="save"]').trigger('click'); await flushPromises()
    expect(api.updateProductCatalog).toHaveBeenCalledWith('p1', { unit: ' 箱/套 ' }, '"v1"')
    expect(field('unit').text()).toContain('箱/套')
    expect(field('unit').find('input').exists()).toBe(false)
  })

  it.each([400, 403, 412, 428])('%s 保存失败保留编辑输入', async status => {
    await setup(); await edit('specification', '未保存规格')
    api.updateProductCatalog.mockRejectedValue({ response: { status, data: { detail: '保存失败' } } })
    await field('specification').get('[data-action="save"]').trigger('click'); await flushPromises()
    expect((field('specification').get('input').element as HTMLInputElement).value).toBe('未保存规格')
    expect(wrapper.find('[role="alert"]').exists()).toBe(true)
    if ([412, 428].includes(status)) {
      api.fetchProductCatalog.mockResolvedValue({ data: { ...product(), specification: '他人修改' }, etag: '"v3"' })
      await row().get('[data-action="reload"]').trigger('click'); await flushPromises()
      expect((field('specification').get('input').element as HTMLInputElement).value).toBe('未保存规格')
      api.updateProductCatalog.mockResolvedValue({ data: { ...product(), specification: '未保存规格' }, etag: '"v4"' })
      await field('specification').get('[data-action="save"]').trigger('click'); await flushPromises()
      expect(api.updateProductCatalog).toHaveBeenLastCalledWith('p1', { specification: '未保存规格' }, '"v3"')
    }
  })

  it('颜色加删只更新当前产品，连续写入使用新的产品版本', async () => {
    await setup()
    await row().get('[data-action="add-color"]').trigger('click'); await flushPromises()
    await row().get('[aria-label="新颜色"]').setValue('黑色')
    const colored = { ...product(), colors: [...product().colors, { id: 'color2', value: '黑色' }] }
    api.addProductCatalogColor.mockResolvedValue({ data: colored, etag: '"v2"' })
    await row().get('[data-action="save-color"]').trigger('click'); await flushPromises()
    expect(row().findAll('[data-color-id]')).toHaveLength(2)
    expect(wrapper.findAll('[data-product-id]')).toHaveLength(1)
    api.deleteProductCatalogColor.mockResolvedValue({ data: product(), etag: '"v3"' })
    await row().get('[aria-label="删除颜色黑色"]').trigger('click'); await flushPromises()
    expect(api.deleteProductCatalogColor).toHaveBeenCalledWith('p1', 'color2', '"v2"')
    expect(row().findAll('[data-color-id]')).toHaveLength(1)
  })

  it('新增产品在表尾草稿行提交，空字段合法且不自动创建颜色', async () => {
    await setup(); await wrapper.get('[data-action="add-product"]').trigger('click')
    const draft = wrapper.get('[data-new-product]')
    await draft.get('[aria-label="新产品货号"]').setValue('H001')
    api.createProductCatalog.mockResolvedValue({ data: { ...product('p2'), product_code: '', specification: '', item_number: 'H001', scale: '', colors: [] }, etag: '"new"' })
    api.fetchProductCatalogs.mockResolvedValue(page([product(), { ...product('p2'), colors: [] }]))
    await draft.get('[data-action="save-product"]').trigger('click'); await flushPromises()
    expect(api.createProductCatalog).toHaveBeenCalledWith({ name_id: 'n1', product_code: '', item_number: 'H001', specification: '', unit: '', scale: '' })
    expect(api.addProductCatalogColor).not.toHaveBeenCalled()
    expect(wrapper.find('[data-new-product]').exists()).toBe(false)
    expect(wrapper.get('[data-name-id="n1"] .product-name-count').text()).toBe('2')
  })

  it('新增品名失败保留输入，成功选中新品名并显示空产品状态', async () => {
    await setup(); await wrapper.get('[data-action="add-name"]').trigger('click')
    await wrapper.get('[aria-label="新品名"]').setValue(' 新桌子（完整名称） ')
    api.createProductCatalogName.mockRejectedValueOnce(new Error('网络错误'))
    await wrapper.get('[data-action="save-name"]').trigger('click'); await flushPromises()
    expect((wrapper.get('[aria-label="新品名"]').element as HTMLInputElement).value).toBe(' 新桌子（完整名称） ')
    expect(api.createProductCatalogName).toHaveBeenCalledWith({ category_id: 'cat1', name: ' 新桌子（完整名称） ' })
    expect(document.querySelector('[data-category-count="cat1"]')?.textContent).toBe('2')
    api.createProductCatalogName.mockResolvedValue({ data: { ...name('n3', '新桌子'), product_count: 0 }, etag: '"n3"' })
    api.fetchProductCatalogNames.mockResolvedValue([name(), name('n3', '新桌子')])
    api.fetchProductCatalogs.mockResolvedValue(page([]))
    await wrapper.get('[data-action="save-name"]').trigger('click'); await flushPromises()
    expect(wrapper.get('[data-name-id="n3"]').attributes('aria-current')).toBe('true')
    expect(wrapper.text()).toContain('暂无产品')
    expect(wrapper.get('[data-name-id="n3"] .product-name-count').text()).toBe('0')
    expect(document.querySelector('[data-category-count="cat1"]')?.textContent).toBe('3')
  })

  it('只读权限没有写入口，无查看权限不读取数据', async () => {
    auth.permissions = new Set(['product_catalog.view_productcatalog'])
    await setup()
    expect(wrapper.find('[data-action="add-product"]').exists()).toBe(false)
    expect(row().find('[data-action="edit"]').exists()).toBe(false)
    wrapper.unmount(); api.fetchProductCatalogOptions.mockClear(); auth.permissions.clear()
    await setup()
    expect(wrapper.text()).toContain('无权查看')
    expect(api.fetchProductCatalogOptions).not.toHaveBeenCalled()
  })

  it('类别选择使用共享控件，切换后重置品名及产品页', async () => {
    await setup()
    const category = wrapper.findAllComponents(MaterialCatalogSelect).find(control => control.props('ariaLabel') === '产品类别')!
    category.vm.$emit('update:modelValue', 'cat2'); category.vm.$emit('change', 'cat2'); await flushPromises()
    expect(api.fetchProductCatalogNames).toHaveBeenLastCalledWith({ category_id: 'cat2', q: '' })
    expect(wrapper.find('select').exists()).toBe(false)
  })

  it('翻页读取失败不把上一页产品冒充当前页，重试恢复当前页', async () => {
    api.fetchProductCatalogs.mockResolvedValueOnce(page([product()], 1, 51)).mockRejectedValueOnce(new Error('页面读取失败')).mockResolvedValueOnce(page([product('p51')], 2, 51))
    await setup()
    await wrapper.get('[aria-label="下一页产品"]').trigger('click'); await flushPromises()
    expect(wrapper.find('[data-product-id="p1"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('页面读取失败')
    await wrapper.get('.catalog-detail .error-message button').trigger('click'); await flushPromises()
    expect(wrapper.find('[data-product-id="p51"]').exists()).toBe(true)
  })

  it('未保存字段时禁止切换品名，取消编辑后恢复', async () => {
    await setup(); await edit('item_number', '暂存货号')
    expect(wrapper.get('button[data-name-id="n2"]').attributes('disabled')).toBeDefined()
    await field('item_number').get('[aria-label="取消编辑货号"]').trigger('click'); await flushPromises()
    expect(wrapper.get('button[data-name-id="n2"]').attributes('disabled')).toBeUndefined()
    await wrapper.get('button[data-name-id="n2"]').trigger('click'); await flushPromises()
    expect(api.fetchProductCatalogs).toHaveBeenLastCalledWith({ name_id: 'n2', page: 1, page_size: 50 })
  })

  it('品名内联重命名发送名称版本且成功更新左侧名称', async () => {
    await setup()
    await wrapper.get('[aria-label="编辑品名"]').trigger('click'); await flushPromises()
    await wrapper.get('[aria-label="品名"]').setValue(' 折叠桌（完整名称） ')
    api.updateProductCatalogName.mockResolvedValue({ data: name('n1', '折叠桌'), etag: '"n2"' })
    await wrapper.get('[aria-label="保存品名"]').trigger('click'); await flushPromises()
    expect(api.updateProductCatalogName).toHaveBeenCalledWith('n1', { name: ' 折叠桌（完整名称） ' }, '"n1"')
    expect(wrapper.get('button[data-name-id="n1"] .product-name-label').text()).toBe('折叠桌')
  })

  it('同产品同时提交两个字段时排队使用最新版本，不丢另一字段', async () => {
    await setup(); await edit('product_code', 'P002'); await edit('unit', '套')
    let finishFirst!: (value: unknown) => void
    api.updateProductCatalog.mockImplementationOnce(() => new Promise(resolve => { finishFirst = resolve }))
      .mockResolvedValueOnce({ data: { ...product(), product_code: 'P002', unit: '套' }, etag: '"v3"' })
    const firstSave = field('product_code').get('[data-action="save"]')
    ;(firstSave.element as HTMLButtonElement).focus()
    const first = field('product_code').get('form').trigger('submit')
    const second = field('unit').get('form').trigger('submit')
    await Promise.all([first, second]); await flushPromises()
    expect(api.updateProductCatalog).toHaveBeenCalledTimes(1)
    expect(firstSave.attributes('aria-busy')).toBe('true')
    expect(firstSave.attributes('disabled')).toBeUndefined()
    expect(firstSave.find('[data-save-spinner]').exists()).toBe(true)
    expect(document.activeElement).toBe(firstSave.element)
    finishFirst({ data: { ...product(), product_code: 'P002' }, etag: '"v2"' }); await flushPromises()
    expect(api.updateProductCatalog).toHaveBeenNthCalledWith(2, 'p1', { unit: '套' }, '"v2"')
    expect(field('product_code').text()).toContain('P002')
    expect(field('unit').text()).toContain('套')
  })

  it('颜色校验失败保留输入，删除最后颜色显示真实空状态', async () => {
    await setup(); await row().get('[data-action="add-color"]').trigger('click'); await flushPromises()
    await row().get('[aria-label="新颜色"]').setValue('白色')
    api.addProductCatalogColor.mockRejectedValue({ response: { status: 400, data: { error: { field_errors: { value: ['颜色重复'] } } } } })
    await row().get('[data-action="save-color"]').trigger('click'); await flushPromises()
    expect((row().get('[aria-label="新颜色"]').element as HTMLInputElement).value).toBe('白色')
    expect(row().text()).toContain('颜色重复')
    await row().get('[aria-label="取消添加颜色"]').trigger('click')
    api.deleteProductCatalogColor.mockResolvedValue({ data: { ...product(), colors: [] }, etag: '"v2"' })
    await row().get('[aria-label="删除颜色白色"]').trigger('click'); await flushPromises()
    expect(row().text()).toContain('尚未维护颜色')
    expect(row().find('[data-color-id]').exists()).toBe(false)
  })

  it('缺失ETag阻止字段保存并保留输入，重新读取后可继续', async () => {
    api.fetchProductCatalog.mockResolvedValue({ data: product(), etag: '' })
    await setup(); await edit('unit', '套')
    expect(row().text()).toContain('未取得产品版本')
    await field('unit').get('form').trigger('submit'); await flushPromises()
    expect(api.updateProductCatalog).not.toHaveBeenCalled()
    expect((field('unit').get('input').element as HTMLInputElement).value).toBe('套')
  })

  it('快速切换类别时忽略较早请求的迟到结果', async () => {
    await setup()
    let finishOld!: (value: unknown) => void
    api.fetchProductCatalogNames.mockImplementationOnce(() => new Promise(resolve => { finishOld = resolve }))
      .mockResolvedValueOnce([name('new-name', '当前类别品名')])
    const category = wrapper.findAllComponents(MaterialCatalogSelect).find(control => control.props('ariaLabel') === '产品类别')!
    category.vm.$emit('update:modelValue', 'cat2'); category.vm.$emit('change', 'cat2'); await flushPromises()
    category.vm.$emit('update:modelValue', 'cat1'); category.vm.$emit('change', 'cat1'); await flushPromises()
    finishOld([name('old-name', '过时品名')]); await flushPromises()
    expect(wrapper.get('[data-testid="product-names"]').text()).toContain('当前类别品名')
    expect(wrapper.get('[data-testid="product-names"]').text()).not.toContain('过时品名')
  })
})
