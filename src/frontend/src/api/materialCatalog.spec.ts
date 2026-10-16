import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  addMaterialAllowedUnit, addMaterialAttributeValue, createMaterialCatalog, deleteMaterialAllowedUnit,
  deleteMaterialAttributeValue, fetchMaterialCatalog, fetchMaterialCatalogOptions, fetchMaterialCatalogs,
  materialCatalogError, updateMaterialCatalog,
} from './materialCatalog'

const client = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() }))
vi.mock('./request', () => ({ apiClient: client }))
const base = '/api/v1/material-catalog/'
const record = { id: 'catalog', name: '测试品名', values: [], units: [] }
const response = { data: { data: record }, headers: { etag: '"version-2"' } }
beforeEach(() => { vi.resetAllMocks(); Object.values(client).forEach(method => method.mockResolvedValue(response)) })

describe('独立原料管理接口契约', () => {
  it('读取定义、过滤列表及详情并保留响应版本', async () => {
    client.get.mockResolvedValueOnce({ data: { data: { categories: [], spray_fields: [], units: [] } } })
    expect(await fetchMaterialCatalogOptions()).toEqual({ categories: [], spray_fields: [], units: [] })
    expect(client.get).toHaveBeenLastCalledWith(`${base}options/`)
    const query = { category: 'TUBE', q: '铁管', page: 1, page_size: 50 }
    await fetchMaterialCatalogs(query)
    expect(client.get).toHaveBeenLastCalledWith(base, { params: query })
    expect(await fetchMaterialCatalog('catalog')).toEqual({ data: record, etag: '"version-2"' })
    expect(client.get).toHaveBeenLastCalledWith(`${base}catalog/`)
  })

  it('新建使用类别模板，喷塑更新使用同档 If-Match', async () => {
    const input = { name: '测试品名', category_key: 'TUBE', template_key: 'TUBE' }
    await createMaterialCatalog(input)
    expect(client.post).toHaveBeenLastCalledWith(base, input)
    await updateMaterialCatalog('catalog', { spray_enabled: true }, '"version-1"')
    expect(client.patch).toHaveBeenLastCalledWith(`${base}catalog/`, { spray_enabled: true }, { headers: { 'If-Match': '"version-1"' } })
  })

  it('属性与单位增删全部发送主档版本，删除读取完整更新详情', async () => {
    const attribute = { scope: 'BASE' as const, field_key: 'section_size', value: '20×20', parent_id: 'shape' }
    const versionHeaders = { headers: { 'If-Match': '"version-1"' } }
    await addMaterialAttributeValue('catalog', attribute, '"version-1"')
    expect(client.post).toHaveBeenLastCalledWith(`${base}catalog/values/`, attribute, versionHeaders)
    expect(await deleteMaterialAttributeValue('catalog', 'value', '"version-1"')).toEqual({ data: record, etag: '"version-2"' })
    expect(client.delete).toHaveBeenLastCalledWith(`${base}catalog/values/value/`, versionHeaders)
    await addMaterialAllowedUnit('catalog', { scope: 'SPRAY', unit_id: 'unit' }, '"version-1"')
    expect(client.post).toHaveBeenLastCalledWith(`${base}catalog/units/`, { scope: 'SPRAY', unit_id: 'unit' }, versionHeaders)
    expect(await deleteMaterialAllowedUnit('catalog', 'option', '"version-1"')).toEqual({ data: record, etag: '"version-2"' })
    expect(client.delete).toHaveBeenLastCalledWith(`${base}catalog/units/option/`, versionHeaders)
  })

  it('缺失 ETag 不虚构版本，接口错误展示具体原因', async () => {
    client.get.mockResolvedValue({ ...response, headers: {} })
    expect((await fetchMaterialCatalog('catalog')).etag).toBe('')
    expect(materialCatalogError({ response: { status: 400, data: { error: { message: '错误', field_errors: { name: ['品名已存在'] } } } } })).toBe('品名已存在')
    expect(materialCatalogError({ response: { data: { detail: '没有操作权限' } } })).toBe('没有操作权限')
    expect(materialCatalogError({ response: { status: 428 } })).toContain('重新读取')
    expect(materialCatalogError(new Error('网络中断'))).toBe('网络中断')
  })
})
