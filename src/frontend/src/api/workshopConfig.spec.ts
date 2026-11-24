import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  createWorkshopConfig,
  fetchWorkshopConfigDetail,
  fetchWorkshopConfigList,
  fetchWorkshopConfigSummary,
  fetchWorkshopEmployeeOptions,
  updateWorkshopConfig,
} from '@/api/workshopConfig'
import { apiClient } from '@/api/request'

vi.mock('@/api/request', () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn() },
}))

const mockedGet = vi.mocked(apiClient.get)
const mockedPost = vi.mocked(apiClient.post)
const mockedPatch = vi.mocked(apiClient.patch)

describe('生产车间配置 API', () => {
  beforeEach(() => {
    mockedGet.mockReset()
    mockedPost.mockReset()
    mockedPatch.mockReset()
  })

  it('四类资源都使用 workshop-config 统一前缀并透传分页筛选', async () => {
    mockedGet.mockResolvedValue({ data: { data: [], meta: { page: 1, page_size: 20, total: 0, total_pages: 0 } } })
    for (const kind of ['workshops', 'employees', 'crafts', 'operations'] as const) {
      await fetchWorkshopConfigList(kind, { page: 1, page_size: 20, q: '测试' })
      expect(mockedGet).toHaveBeenLastCalledWith(`/api/v1/workshop-config/${kind}/`, {
        params: kind === 'employees'
          ? { position_state: 'ROLE_ALL', page: 1, page_size: 20, q: '测试' }
          : { page: 1, page_size: 20, q: '测试' },
      })
    }
  })

  it('详情和更新保留并发送 ETag', async () => {
    mockedGet.mockResolvedValueOnce({ data: { data: { id: 'employee-1' } }, headers: { etag: '"v1"' } })
    mockedPatch.mockResolvedValueOnce({ data: { data: { id: 'employee-1' } }, headers: { etag: '"v2"' } })
    const detail = await fetchWorkshopConfigDetail('employees', 'employee-1')
    const updated = await updateWorkshopConfig('employees', 'employee-1', { status: 'LEFT' }, detail.etag)
    expect(detail.etag).toBe('"v1"')
    expect(updated.etag).toBe('"v2"')
    expect(mockedPatch).toHaveBeenCalledWith(
      '/api/v1/workshop-config/employees/employee-1/',
      { status: 'LEFT' },
      { headers: { 'If-Match': '"v1"' } },
    )
  })

  it('只为工艺创建资料，员工通过既有ID更新', async () => {
    const payload = { craft_type: 'EXTERNAL' as const, workshop: null, name: '测试工艺', status: 'ACTIVE' as const, plan_category: null, outsourcing_code: null }
    mockedPost.mockResolvedValueOnce({ data: { data: { id: 'craft-1' } }, headers: { etag: '"v1"' } })
    await createWorkshopConfig('crafts', payload)
    expect(mockedPost).toHaveBeenCalledWith('/api/v1/workshop-config/crafts/', payload)
  })

  it('统计接口位于各资源内部', async () => {
    mockedGet.mockResolvedValueOnce({ data: { data: { total: 81, active: 74, left: 7 } } })
    await expect(fetchWorkshopConfigSummary('employees')).resolves.toEqual({ total: 81, active: 74, left: 7 })
    expect(mockedGet).toHaveBeenCalledWith('/api/v1/workshop-config/employees/summary/')
  })

  it('员工车间选项使用员工自身权限并保留独立查看和修改范围', async () => {
    const options = { workshops: [{ id: 'metal', name: '金工车间', status: 'ACTIVE' }], editable_workshops: [] }
    mockedGet.mockResolvedValueOnce({ data: { data: options } })
    await expect(fetchWorkshopEmployeeOptions()).resolves.toEqual(options)
    expect(mockedGet).toHaveBeenCalledExactlyOnceWith('/api/v1/workshop-config/employees/options/')
  })
})
