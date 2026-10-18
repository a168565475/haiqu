import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElMessageBox } from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import ProductInformationDrawer from './ProductInformationDrawer.vue'

const fixture = {
  id: 'product-1', product_number: 'CP00001', product_type: 'FINISHED' as const,
  product_type_label: '成品', product_code: '', category: 'category-1', category_name: '办公椅',
  product_name: '云端办公椅', specification: '黑色标准款', unit: 'unit-1', unit_code: 'PCS',
  unit_name: 'PCS', product_item: 'item-1', item_number: 'HH001', item_category_id: 'category-1',
  item_category_name: '办公椅', category_item_mismatch: false, warehouse_number: 'CK01',
  warehouse_name: '成品仓', scale: 'CUSTOM' as const, status: 'ACTIVE' as const,
  created_at: '2026-09-11T00:00:00Z', updated_at: '2026-09-11T00:00:00Z', archived_at: null,
}

const apiMocks = vi.hoisted(() => ({
  fetchProductOptions: vi.fn(), fetchProduct: vi.fn(), createProduct: vi.fn(), updateProduct: vi.fn(),
}))

vi.mock('@/api/products', () => apiMocks)

const appWindowDialogStub = {
  name: 'AppWindowDialog',
  props: ['modelValue', 'title', 'width', 'closeOnClickModal'],
  template: '<div v-if="modelValue" class="app-window-dialog"><slot name="title" /><slot /><slot name="footer" /></div>',
}

const mountDrawer = (product = fixture) => {
  apiMocks.fetchProduct.mockResolvedValue({ data: product, etag: '"etag-1"' })
  return mount(ProductInformationDrawer, {
    props: { modelValue: true, mode: 'edit', productId: product.id },
    global: { plugins: [ElementPlus], stubs: { AppWindowDialog: appWindowDialogStub } },
  })
}

describe('ProductInformationDrawer', () => {
  beforeEach(() => {
    document.body.innerHTML = ''
    vi.clearAllMocks()
    apiMocks.fetchProductOptions.mockResolvedValue({
      categories: [{ id: 'category-1', category_name: '办公椅' }],
      units: [{ id: 'unit-1', unit_code: 'PCS', unit_name: 'PCS' }],
      items: [{ id: 'item-1', item_number: 'HH001', category_id: 'category-1', category_name: '办公椅' }],
    })
    apiMocks.updateProduct.mockResolvedValue({ data: fixture, etag: '"etag-2"' })
  })

  it('编辑态展示 12 个字段并使用 748px 窗口', async () => {
    const wrapper = mountDrawer()
    await flushPromises()

    expect(wrapper.findComponent({ name: 'AppWindowDialog' }).props('width')).toBe('748px')
    for (const label of ['品号', '类型', '产品编码', '品名', '类别', '货号', '规格', '单位', '仓库号', '仓库名称', '规模', '状态']) {
      expect(wrapper.text()).toContain(label)
    }
    expect(apiMocks.fetchProduct).toHaveBeenCalledWith('product-1')
  })

  it('双击保存只发送一次带 ETag 的更新请求', async () => {
    let resolveUpdate!: (value: unknown) => void
    apiMocks.updateProduct.mockReturnValue(new Promise((resolve) => { resolveUpdate = resolve }))
    const wrapper = mountDrawer()
    await flushPromises()
    const saveButton = wrapper.findAll('button').find((button) => button.text().includes('保存修改'))!

    await Promise.all([saveButton.trigger('click'), saveButton.trigger('click')])
    await flushPromises()
    expect(apiMocks.updateProduct).toHaveBeenCalledTimes(1)
    expect(apiMocks.updateProduct).toHaveBeenCalledWith(
      'product-1', expect.objectContaining({ product_number: 'CP00001' }), '"etag-1"',
    )
    await expect((wrapper.vm as unknown as { canLeave: () => Promise<boolean> }).canLeave()).resolves.toBe(false)
    resolveUpdate({ data: fixture, etag: '"etag-2"' })
    await flushPromises()
  })

  it('412 冲突时保留本地输入并允许历史类别货号原样保存', async () => {
    const historical = {
      ...fixture, category_item_mismatch: true, item_category_id: 'category-2', item_category_name: '历史类别',
    }
    apiMocks.fetchProductOptions.mockResolvedValue({
      categories: [{ id: 'category-1', category_name: '办公椅' }],
      units: [{ id: 'unit-1', unit_code: 'PCS', unit_name: 'PCS' }],
      items: [],
    })
    apiMocks.updateProduct.mockRejectedValueOnce({ response: { status: 412, data: {} } })
    const wrapper = mountDrawer(historical)
    await flushPromises()
    const nameInput = wrapper.find('input[placeholder="请输入品名"]')
    await nameInput.setValue('冲突后仍保留')
    await wrapper.findAll('button').find((button) => button.text().includes('保存修改'))!.trigger('click')
    await flushPromises()

    expect(apiMocks.updateProduct).toHaveBeenCalledTimes(1)
    expect((nameInput.element as HTMLInputElement).value).toBe('冲突后仍保留')
    expect(wrapper.text()).toContain('数据已被其他人更新，本次未保存')
  })

  it('冲突后重读最新版本仍可恢复本地草稿', async () => {
    apiMocks.updateProduct.mockRejectedValueOnce({ response: { status: 412, data: {} } })
    apiMocks.fetchProduct
      .mockResolvedValueOnce({ data: fixture, etag: '"etag-1"' })
      .mockResolvedValueOnce({ data: { ...fixture, product_name: '服务器新值' }, etag: '"etag-2"' })
    const wrapper = mountDrawer()
    await flushPromises()
    await wrapper.find('input[placeholder="请输入品名"]').setValue('我的草稿')
    await wrapper.findAll('button').find((button) => button.text().includes('保存修改'))!.trigger('click')
    await flushPromises()

    await wrapper.findAll('button').find((button) => button.text().includes('重新读取最新资料'))!.trigger('click')
    await flushPromises()
    expect((wrapper.find('input[placeholder="请输入品名"]').element as HTMLInputElement).value).toBe('服务器新值')
    vi.spyOn(ElMessageBox, 'confirm').mockRejectedValueOnce('继续编辑')
    await expect((wrapper.vm as unknown as { canLeave: () => Promise<boolean> }).canLeave()).resolves.toBe(false)
    await wrapper.findAll('button').find((button) => button.text().includes('恢复旧草稿'))!.trigger('click')
    await flushPromises()
    expect((wrapper.find('input[placeholder="请输入品名"]').element as HTMLInputElement).value).toBe('我的草稿')
    await wrapper.findAll('button').find((button) => button.text().includes('保存修改'))!.trigger('click')
    await flushPromises()
    expect(apiMocks.updateProduct.mock.calls[1][2]).toBe('"etag-2"')
  })

  it('冲突后重新读取失败会恢复草稿和冲突状态', async () => {
    apiMocks.updateProduct.mockRejectedValueOnce({ response: { status: 412, data: {} } })
    apiMocks.fetchProduct
      .mockResolvedValueOnce({ data: fixture, etag: '"etag-1"' })
      .mockRejectedValueOnce(new Error('network'))
    const wrapper = mountDrawer()
    await flushPromises()
    await wrapper.find('input[placeholder="请输入品名"]').setValue('网络失败草稿')
    await wrapper.findAll('button').find((button) => button.text().includes('保存修改'))!.trigger('click')
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text().includes('重新读取最新资料'))!.trigger('click')
    await flushPromises()

    expect((wrapper.find('input[placeholder="请输入品名"]').element as HTMLInputElement).value).toBe('网络失败草稿')
    expect(wrapper.text()).toContain('数据已被其他人更新，本次未保存')
  })
})
