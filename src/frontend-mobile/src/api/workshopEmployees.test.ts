import { beforeEach, describe, expect, it, vi } from 'vitest'
import { deleteWorkshopEmployee, fetchWorkshopEmployee, fetchWorkshopEmployees, fetchWorkshopEmployeeOptions, updateWorkshopEmployee } from './workshopEmployees'

const client = vi.hoisted(() => ({ get: vi.fn(), patch: vi.fn(), delete: vi.fn() }))
vi.mock('@/utils/request', () => ({ apiClient: client }))
const employee = { id: 'worker-1', name: '员工甲', can_edit: true }
beforeEach(() => vi.resetAllMocks())

describe('手机员工配置接口', () => {
  it('保持服务端分页与授权选项，不自行推算车间范围', async () => {
    client.get.mockResolvedValueOnce({ data: { data: [employee], meta: { page: 2, page_size: 20, total: 21, total_pages: 2 } } })
    const response = await fetchWorkshopEmployees({ page: 2, q: '甲', workshop: 'metal' })
    expect(response.meta.total).toBe(21)
    expect(client.get).toHaveBeenLastCalledWith('/api/v1/workshop-config/employees/', expect.objectContaining({ params: { page: 2, page_size: 20, q: '甲', workshop: 'metal' } }))
    client.get.mockResolvedValueOnce({ data: { data: { workshops: [], editable_workshops: [] } } })
    expect(await fetchWorkshopEmployeeOptions()).toEqual({ workshops: [], editable_workshops: [] })
  })
  it('传递待设置岗位筛选，不在前端猜测岗位状态', async () => {
    client.get.mockResolvedValueOnce({ data: { data: [employee], meta: { page: 1, page_size: 20, total: 1, total_pages: 1 } } })
    await fetchWorkshopEmployees({ page: 1, position_state: 'UNSET' })
    expect(client.get).toHaveBeenLastCalledWith('/api/v1/workshop-config/employees/', expect.objectContaining({
      params: { page: 1, page_size: 20, position_state: 'UNSET' },
    }))
  })
  it('详情读取版本，修改和解除安排都发送原版本', async () => {
    client.get.mockResolvedValue({ data: { data: employee }, headers: { etag: '"v1"' } })
    expect((await fetchWorkshopEmployee('worker-1')).etag).toBe('"v1"')
    client.patch.mockResolvedValue({ data: { data: employee }, headers: { etag: '"v2"' } })
    expect((await updateWorkshopEmployee('worker-1', { status: 'LEFT' }, '"v1"')).etag).toBe('"v2"')
    expect(client.patch).toHaveBeenCalledWith('/api/v1/workshop-config/employees/worker-1/', { status: 'LEFT' }, expect.objectContaining({ headers: { 'If-Match': '"v1"' } }))
    await deleteWorkshopEmployee('worker-1', '"v2"')
    expect(client.delete).toHaveBeenCalledWith('/api/v1/workshop-config/employees/worker-1/', expect.objectContaining({ headers: { 'If-Match': '"v2"' } }))
  })
  it('缺少版本或保存结果时拒绝假成功和无版本写入', async () => {
    client.get.mockResolvedValue({ data: { data: employee }, headers: {} })
    await expect(fetchWorkshopEmployee('worker-1')).rejects.toThrow()
    await expect(updateWorkshopEmployee('worker-1', { status: 'LEFT' }, '')).rejects.toThrow()
    expect(client.patch).not.toHaveBeenCalled()
    client.patch.mockResolvedValue({ data: {}, headers: { etag: '"v2"' } })
    await expect(updateWorkshopEmployee('worker-1', { status: 'LEFT' }, '"v1"')).rejects.toThrow()
  })
})
