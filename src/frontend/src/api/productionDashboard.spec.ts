import { beforeEach, describe, expect, it, vi } from 'vitest'
import { apiClient } from './request'
import { fetchProductionDashboard } from './productionDashboard'

vi.mock('./request', () => ({ apiClient: { get: vi.fn() } }))

describe('生产工作台只读请求', () => {
  beforeEach(() => vi.clearAllMocks())

  it('传递筛选和取消信号，只返回服务端数据', async () => {
    const payload = { generated_at: '2026-10-17T12:00:00+08:00', sections: {} }
    vi.mocked(apiClient.get).mockResolvedValue({ data: { data: payload } })
    const controller = new AbortController()
    const query = { days: 3 as const, q: '折叠椅', focus: 'OVERDUE' as const }
    expect(await fetchProductionDashboard(query, controller.signal)).toBe(payload)
    expect(apiClient.get).toHaveBeenCalledWith('/api/v1/production-dashboard/', { params: query, signal: controller.signal })
  })

  it('保留权限或网络错误，不用空数据掩盖失败', async () => {
    const error = new Error('403')
    vi.mocked(apiClient.get).mockRejectedValue(error)
    await expect(fetchProductionDashboard({})).rejects.toBe(error)
  })
})
