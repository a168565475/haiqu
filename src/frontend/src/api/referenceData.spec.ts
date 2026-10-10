import { beforeEach, describe, expect, it, vi } from 'vitest'

import { fetchAllMasterDataRecords, fetchPublishedOptions } from '@/api/referenceData'
import { apiClient } from '@/api/request'
import type { Currency } from '@/types/referenceData'

vi.mock('@/api/request', () => ({
  apiClient: {
    get: vi.fn(),
  },
}))

const mockedGet = vi.mocked(apiClient.get)

function currency(code: string): Currency {
  return { code } as Currency
}

describe('reference data api', () => {
  beforeEach(() => mockedGet.mockReset())

  it('同一轮不同字典合并为一个请求，单项缺失不影响其他字典', async () => {
    mockedGet.mockResolvedValue({ data: { data: { CUSTOMER_GRADE: [], CUSTOMER_TYPE: [] }, errors: { UNKNOWN: '不存在' }, meta: { config_version: 3 } } })
    const results = await Promise.allSettled([
      fetchPublishedOptions('customer_grade'), fetchPublishedOptions('CUSTOMER_TYPE'), fetchPublishedOptions('UNKNOWN'),
    ])
    expect(mockedGet).toHaveBeenCalledTimes(1)
    expect(mockedGet).toHaveBeenCalledWith('/api/v1/reference-data/options-batch/', { params: { type_codes: 'CUSTOMER_GRADE,CUSTOMER_TYPE,UNKNOWN' } })
    expect(results.map(result => result.status)).toEqual(['fulfilled', 'fulfilled', 'rejected'])
  })

  it('历史停用项仍走带 current_id 的单项接口', async () => {
    mockedGet.mockResolvedValue({ data: { data: [], meta: { config_version: 3 } } })
    await fetchPublishedOptions('CUSTOMER_GRADE', 'historical-id')
    expect(mockedGet).toHaveBeenCalledWith('/api/v1/reference-data/options/CUSTOMER_GRADE/', { params: { current_id: 'historical-id' } })
  })

  it('自动读取主数据的全部分页', async () => {
    mockedGet
      .mockResolvedValueOnce({
        data: {
          data: [currency('CNY')],
          meta: { page: 1, page_size: 100, total: 2, total_pages: 2 },
        },
      })
      .mockResolvedValueOnce({
        data: {
          data: [currency('USD')],
          meta: { page: 2, page_size: 100, total: 2, total_pages: 2 },
        },
      })

    await expect(fetchAllMasterDataRecords<Currency>('currencies', { status: 'ACTIVE' }))
      .resolves.toEqual([currency('CNY'), currency('USD')])
    expect(mockedGet).toHaveBeenNthCalledWith(
      2,
      '/api/v1/reference-data/currencies/',
      { params: { status: 'ACTIVE', page: 2, page_size: 100 } },
    )
  })
})
