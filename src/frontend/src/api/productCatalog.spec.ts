import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  addProductCatalogColor, createProductCatalog, createProductCatalogName, deleteProductCatalogColor,
  fetchProductCatalog, fetchProductCatalogNames, fetchProductCatalogOptions, fetchProductCatalogs,
  fetchProductCatalogName, productCatalogError, updateProductCatalog, updateProductCatalogName,
} from './productCatalog'

const client = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() }))
vi.mock('./request', () => ({ apiClient: client }))
const base = '/api/v1/product-catalog/'
const record = { id: 'p1', product_code: '', unit: '', colors: [{ id: 'c1', value: '白色' }] }
const response = { data: { data: record }, headers: { etag: '"v2"' } }
beforeEach(() => { vi.resetAllMocks(); Object.values(client).forEach(method => method.mockResolvedValue(response)) })

describe('独立产品目录 API 契约', () => {
  it('名称列表没有分页截断，产品列表保留分页元数据', async () => {
    client.get.mockResolvedValueOnce({ data: { data: { categories: [], units: [], scales: [] } } })
    expect(await fetchProductCatalogOptions()).toEqual({ categories: [], units: [], scales: [] })
    await fetchProductCatalogNames({ category_id: 'c1', q: '桌' })
    expect(client.get).toHaveBeenLastCalledWith(`${base}names/`, { params: { category_id: 'c1', q: '桌' } })
    client.get.mockResolvedValueOnce({ data: { data: [record], meta: { page: 2, page_size: 50, total: 51, total_pages: 2 } } })
    const result = await fetchProductCatalogs({ name_id: 'n1', page: 2, page_size: 50 })
    expect(result.meta.total).toBe(51)
    expect(client.get).toHaveBeenLastCalledWith(base, { params: { name_id: 'n1', page: 2, page_size: 50 } })
  })

  it('详情与新增不丢版本，业务原文和空单位不被改写', async () => {
    expect(await fetchProductCatalog('p/1')).toEqual({ data: record, etag: '"v2"' })
    expect(client.get).toHaveBeenLastCalledWith(`${base}p%2F1/`)
    const payload = { name_id: 'n1', product_code: '', item_number: 'A  1', specification: '  原文 ', unit: '', scale: '' }
    await createProductCatalog(payload)
    expect(client.post).toHaveBeenLastCalledWith(base, payload)
    await createProductCatalogName({ category_id: 'c1', name: '桌子' })
    expect(client.post).toHaveBeenLastCalledWith(`${base}names/`, { category_id: 'c1', name: '桌子' })
  })

  it('名称、产品字段及颜色写入都发送自己的 If-Match，删除返回完整产品', async () => {
    const config = { headers: { 'If-Match': '"v1"' } }
    await fetchProductCatalogName('n1')
    expect(client.get).toHaveBeenLastCalledWith(`${base}names/n1/`)
    await updateProductCatalogName('n1', { name: '新名' }, '"v1"')
    expect(client.patch).toHaveBeenLastCalledWith(`${base}names/n1/`, { name: '新名' }, config)
    await updateProductCatalog('p1', { unit: '箱/套' }, '"v1"')
    expect(client.patch).toHaveBeenLastCalledWith(`${base}p1/`, { unit: '箱/套' }, config)
    await addProductCatalogColor('p1', { value: '黑色' }, '"v1"')
    expect(client.post).toHaveBeenLastCalledWith(`${base}p1/colors/`, { value: '黑色' }, config)
    expect(await deleteProductCatalogColor('p1', 'c/1', '"v1"')).toEqual({ data: record, etag: '"v2"' })
    expect(client.delete).toHaveBeenLastCalledWith(`${base}p1/colors/c%2F1/`, config)
  })

  it('缺失版本不伪造，字段、权限和冲突错误保留真实原因', async () => {
    client.get.mockResolvedValue({ ...response, headers: {} })
    expect((await fetchProductCatalog('p1')).etag).toBe('')
    expect(productCatalogError({ response: { status: 412 } })).toContain('重新读取')
    expect(productCatalogError({ response: { status: 428 } })).toContain('重新读取')
    expect(productCatalogError({ response: { status: 400, data: { error: { field_errors: { value: ['颜色已存在'] } } } } })).toBe('颜色已存在')
    expect(productCatalogError({ response: { status: 403, data: { detail: '没有修改权限' } } })).toBe('没有修改权限')
  })
})
