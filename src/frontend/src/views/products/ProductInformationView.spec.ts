import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElMessage } from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import ProductInformationView from './ProductInformationView.vue'

const fixtures = vi.hoisted(() => ({
  granted: new Set<string>(),
  row: {
    id: 'product-1', product_number: 'CP00001', product_code: 'A-001',
    category: 'category-1', category_name: '办公椅', product_name: '云端办公椅',
    specification: '黑色标准款', unit: 'unit-1', unit_code: 'PCS', unit_name: 'PCS',
    item: 'item-1', item_number: 'HH001', item_category_name: '办公椅',
    category_item_mismatch: false, warehouse_number: 'CK01', warehouse_name: '成品仓',
    scale: 'CUSTOM', status: 'ACTIVE', created_at: '2026-09-11T00:00:00Z',
    updated_at: '2026-09-11T00:00:00Z', archived_at: null,
  },
}))

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({
    user: { is_superuser: false },
    hasPermission: (permission: string) => fixtures.granted.has(permission),
  }),
}))

const apiMocks = vi.hoisted(() => ({
  fetchProductOptions: vi.fn(),
  fetchProducts: vi.fn(),
}))

vi.mock('@/api/products', () => ({
  fetchProductOptions: apiMocks.fetchProductOptions,
  fetchProducts: apiMocks.fetchProducts,
}))

const mountView = () => mount(ProductInformationView, {
  global: {
    plugins: [ElementPlus],
    stubs: { ProductInformationDrawer: true },
  },
})

describe('ProductInformationView', () => {
  beforeEach(() => {
    document.body.innerHTML = ''
    fixtures.granted.clear()
    fixtures.granted.add('products.view_productinformation')
    fixtures.granted.add('products.add_productinformation')
    fixtures.granted.add('products.change_productinformation')
    apiMocks.fetchProductOptions.mockReset().mockResolvedValue({ categories: [], units: [], items: [] })
    apiMocks.fetchProducts.mockReset().mockResolvedValue({
      data: [fixtures.row],
      meta: { page: 1, page_size: 50, total: 126, total_pages: 3 },
    })
  })

  it('默认按品号升序请求 50 条并为规模和状态使用标签', async () => {
    const wrapper = mountView()
    await flushPromises()

    expect(apiMocks.fetchProducts).toHaveBeenCalledWith(expect.objectContaining({
      page: 1, page_size: 50, ordering: 'product_number',
    }))
    expect(wrapper.text()).toContain('126 条')
    expect(wrapper.text()).toContain('CP00001')
    expect(wrapper.find('.scale-tag').text()).toBe('定制')
    expect(wrapper.find('.scale-tag').classes()).toContain('is-custom')
    expect(wrapper.find('.status-tag').classes()).toContain('is-active')
    expect(wrapper.find('.scale-tag').classes()).toContain('warm-tag')
    expect(wrapper.find('.status-tag').classes()).toContain('warm-tag')
  })

  it('定制、常规、正常、废弃四种语义都映射到独立标签类', async () => {
    apiMocks.fetchProducts.mockResolvedValueOnce({
      data: [
        { ...fixtures.row, id: 'custom-active', scale: 'CUSTOM', status: 'ACTIVE' },
        { ...fixtures.row, id: 'regular-inactive', product_number: 'CP00002', scale: 'REGULAR', status: 'INACTIVE' },
      ],
      meta: { page: 1, page_size: 50, total: 2, total_pages: 1 },
    })
    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.get('.scale-tag.is-custom').text()).toBe('定制')
    expect(wrapper.get('.scale-tag.is-regular').text()).toBe('常规')
    expect(wrapper.get('.status-tag.is-active').text()).toBe('正常')
    expect(wrapper.get('.status-tag.is-inactive').text()).toBe('废弃')
  })

  it('产品主列把排序方向传给后端', async () => {
    const wrapper = mountView()
    await flushPromises()
    const table = wrapper.findComponent({ name: 'ElTable' })

    for (const key of ['product_number', 'product_code', 'product_name'] as const) {
      table.vm.$emit('sort-change', { prop: key, order: 'descending' })
      await flushPromises()
      expect(apiMocks.fetchProducts).toHaveBeenLastCalledWith(expect.objectContaining({ ordering: `-${key}` }))
    }
  })

  it('工具栏排序同步表头箭头，空排序事件不会伪装成升序', async () => {
    const wrapper = mountView()
    await flushPromises()
    const table = wrapper.findComponent({ name: 'ElTable' })
    const exposed = (table.vm.$ as unknown as { exposed: { sort: (prop: string, order: string) => void } }).exposed
    const sort = vi.spyOn(exposed, 'sort')
    const toolbar = wrapper.findAllComponents({ name: 'ElSelect' })
      .find((select) => select.props('ariaLabel') === '产品排序')!

    toolbar.vm.$emit('update:modelValue', '-product_number')
    await flushPromises()
    expect(sort).toHaveBeenCalledWith('product_number', 'descending')
    const callsBeforeNull = apiMocks.fetchProducts.mock.calls.length
    table.vm.$emit('sort-change', { prop: 'product_number', order: null })
    await flushPromises()
    expect(apiMocks.fetchProducts).toHaveBeenCalledTimes(callsBeforeNull)
  })

  it('选项失败不遮挡已经成功加载的产品列表', async () => {
    apiMocks.fetchProductOptions.mockRejectedValueOnce(new Error('options unavailable'))
    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain('CP00001')
    expect(wrapper.text()).toContain('筛选选项加载失败')
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
  })

  it('保存后的刷新被更新查询取代时不误报刷新失败', async () => {
    const wrapper = mountView()
    await flushPromises()
    expect(wrapper.findComponent({ name: 'ProductInformationDrawer' }).exists()).toBe(false)
    await wrapper.find('.edit-button').trigger('click')
    await flushPromises()
    let resolveOld!: (value: unknown) => void
    apiMocks.fetchProducts
      .mockImplementationOnce(() => new Promise((resolve) => { resolveOld = resolve }))
      .mockResolvedValueOnce({ data: [fixtures.row], meta: { page: 1, page_size: 50, total: 1, total_pages: 1 } })
    const warning = vi.spyOn(ElMessage, 'warning')

    wrapper.findComponent({ name: 'ProductInformationDrawer' }).vm.$emit('saved')
    wrapper.findComponent({ name: 'ElTable' }).vm.$emit('sort-change', { prop: 'product_name', order: 'descending' })
    await flushPromises()
    resolveOld({ data: [fixtures.row], meta: { page: 1, page_size: 50, total: 1, total_pages: 1 } })
    await flushPromises()

    expect(warning).not.toHaveBeenCalled()
  })
})
