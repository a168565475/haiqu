import { beforeEach, describe, expect, it, vi } from 'vitest'

import { createSupplier, fetchSupplier, fetchSuppliers, updateSupplier } from '@/api/suppliers'
import { apiClient } from '@/api/request'
import type { SupplierInput } from '@/types/supplier'

vi.mock('@/api/request', () => ({
  apiClient: {
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
  },
}))

const mockedGet = vi.mocked(apiClient.get)
const mockedPost = vi.mocked(apiClient.post)
const mockedPatch = vi.mocked(apiClient.patch)

const payload: SupplierInput = {
  supplier_type: 'MATERIAL',
  supplier_categories: ['FABRIC'],
  supplier_name: '浙江弘达环保科技有限公司',
  payment_cycle: 'MONTHLY',
  remark: '',
  phone: '13586081399',
  is_disabled: true,
}

describe('供应商 API', () => {
  beforeEach(() => {
    mockedGet.mockReset()
    mockedPost.mockReset()
    mockedPatch.mockReset()
  })

  it('列表筛选参数原样交给后端', async () => {
    mockedGet.mockResolvedValueOnce({
      data: { data: [], meta: { page: 1, page_size: 20, total: 0, total_pages: 0 } },
    })

    await fetchSuppliers({ page: 1, page_size: 20, q: '弘达', category: 'FABRIC', is_disabled: true })

    expect(mockedGet).toHaveBeenCalledWith('/api/v1/suppliers/', {
      params: { page: 1, page_size: 20, q: '弘达', category: 'FABRIC', is_disabled: true },
    })
  })

  it('读取详情并保留响应 ETag', async () => {
    mockedGet.mockResolvedValueOnce({
      data: { data: { id: 'supplier-1', supplier_number: 'GYS00257' } },
      headers: { etag: '"supplier-v1"' },
    })

    const result = await fetchSupplier('supplier-1')

    expect(result.etag).toBe('"supplier-v1"')
    expect(mockedGet).toHaveBeenCalledWith('/api/v1/suppliers/supplier-1/')
  })

  it('创建与更新使用同一份业务字段，更新携带 If-Match', async () => {
    mockedPost.mockResolvedValueOnce({ data: { data: { id: 'supplier-1' } }, headers: { etag: '"v1"' } })
    mockedPatch.mockResolvedValueOnce({ data: { data: { id: 'supplier-1' } }, headers: { etag: '"v2"' } })

    await createSupplier(payload)
    await updateSupplier('supplier-1', payload, '"v1"')

    expect(mockedPost).toHaveBeenCalledWith('/api/v1/suppliers/', payload)
    expect(mockedPatch).toHaveBeenCalledWith(
      '/api/v1/suppliers/supplier-1/',
      payload,
      { headers: { 'If-Match': '"v1"' } },
    )
  })
})
