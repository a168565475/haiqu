import { beforeEach, expect, it, vi } from 'vitest'
import { apiClient } from './request'
import { fetchTubeOptions, fetchTubeSource } from './tubeOutsourcing'

vi.mock('./request', () => ({ apiClient: { get: vi.fn() } }))
beforeEach(() => { vi.resetAllMocks(); vi.mocked(apiClient.get).mockResolvedValue({ data: { data: {} } }) })

it('管材选项保留原请求，裁片选项显式选择同接口类别', async () => {
  await fetchTubeOptions()
  expect(apiClient.get).toHaveBeenLastCalledWith('/api/v1/tube-outsourcing-orders/options/')
  await fetchTubeOptions('cutting')
  expect(apiClient.get).toHaveBeenLastCalledWith('/api/v1/tube-outsourcing-orders/options/', { params: { category: 'cutting' } })
})

it('裁片直发来源按工艺查询，同请求不伪造主库区', async () => {
  const params = { schedule_product_id: 'schedule-1', source_kind: 'SEWING' as const, craft_id: 'embroidery-1' }
  await fetchTubeSource(params)
  expect(apiClient.get).toHaveBeenLastCalledWith('/api/v1/tube-outsourcing-orders/source-context/', { params, timeout: 15000 })
})
