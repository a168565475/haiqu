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
        params: { page: 1, page_size: 20, q: '测试' },
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

  it('创建车间任职提交统一员工 ID 与主管值，不提交姓名', async () => {
    const payload = {
      workshop: 'workshop-1',
      position: '组长',
      employee: 'unified-employee-1',
      is_supervisor: true,
      status: 'ACTIVE' as const,
    }
    mockedPost.mockResolvedValueOnce({ data: { data: { id: 'employee-1' } }, headers: { etag: '"v1"' } })
    await createWorkshopConfig('employees', payload)
    expect(mockedPost).toHaveBeenCalledWith('/api/v1/workshop-config/employees/', payload)
    expect(mockedPost.mock.calls[0]?.[1]).not.toHaveProperty('name')
  })

  it('员工候选使用车间接口并透传搜索与分页，保留候选版本', async () => {
    const response = {
      data: [{ id: 'unified-1', employee_code: 'E001', display_name: '员工甲', status: 'ACTIVE', etag: '"employee-v1"' }],
      meta: { page: 2, page_size: 50, total: 51, total_pages: 2 },
    }
    mockedGet.mockResolvedValueOnce({ data: response })
    await expect(fetchWorkshopEmployeeOptions({ q: 'E001', page: 2, page_size: 50 })).resolves.toEqual(response)
    expect(mockedGet).toHaveBeenCalledWith('/api/v1/workshop-config/employees/employee-options/', {
      params: { q: 'E001', page: 2, page_size: 50 },
    })
  })

  it('候选权限错误保留给页面处理，不伪装为空列表', async () => {
    const error = { response: { status: 403, data: { error: { message: '没有员工配置权限' } } } }
    mockedGet.mockRejectedValueOnce(error)
    await expect(fetchWorkshopEmployeeOptions({ page: 1, page_size: 50 })).rejects.toBe(error)
  })

  it('统计接口位于各资源内部', async () => {
    mockedGet.mockResolvedValueOnce({ data: { data: { total: 81, active: 74, left: 7 } } })
    await expect(fetchWorkshopConfigSummary('employees')).resolves.toEqual({ total: 81, active: 74, left: 7 })
    expect(mockedGet).toHaveBeenCalledWith('/api/v1/workshop-config/employees/summary/')
  })
})
