import { beforeEach, describe, expect, it, vi } from 'vitest'
import { apiClient } from './request'
import * as access from './access'
import type { AccessDepartment, AccessEmployee, AccessRole } from '@/types/access'

vi.mock('./request', () => ({ apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), put: vi.fn() } }))
beforeEach(() => vi.resetAllMocks())

describe('组织管理请求契约', () => {
  it('读取全部分页，避免只显示前100个部门', async () => {
    vi.mocked(apiClient.get).mockResolvedValueOnce({ data: { data: [{ id: 'one' }], meta: { total_pages: 2 } } })
      .mockResolvedValueOnce({ data: { data: [{ id: 'two' }], meta: { total_pages: 2 } } })
    expect(await access.getDepartments()).toEqual([{ id: 'one' }, { id: 'two' }])
    expect(apiClient.get).toHaveBeenLastCalledWith('/api/v1/access/departments/', expect.objectContaining({ params: { page: 2, page_size: 100 } }))
  })
  it('部门修改携带资源版本；不发送编码或父级的隐式修改', async () => {
    vi.mocked(apiClient.patch).mockResolvedValue({ data: {} })
    await access.updateDepartment({ id: 'department', etag: 'dep-v1' } as AccessDepartment, { status: 'INACTIVE' })
    expect(apiClient.patch).toHaveBeenCalledWith('/api/v1/access/departments/department/', { status: 'INACTIVE' }, expect.objectContaining({ headers: { 'If-Match': 'dep-v1' } }))
  })
  it('解除角色分类发送null，保留角色版本，不发送授权变更', async () => {
    vi.mocked(apiClient.put).mockResolvedValue({ data: {} })
    await access.setRoleDepartment({ id: 'role', etag: 'role-v1' } as AccessRole, null)
    expect(apiClient.put).toHaveBeenCalledWith('/api/v1/access/roles/role/department/', { department_id: null }, expect.objectContaining({ headers: { 'If-Match': 'role-v1' } }))
  })
  it('员工调整使用历史查询返回版本，保留主部门和岗位字段', async () => {
    vi.mocked(apiClient.put).mockResolvedValue({ data: {} })
    const rows = [{ department_id: 'department', is_primary: true, position_title: '主任' }]
    await access.assignDepartments({ id: 'employee', etag: 'old-version' } as AccessEmployee, rows, 'history-v2')
    expect(apiClient.put).toHaveBeenCalledWith('/api/v1/access/employees/employee/departments/', { departments: rows }, expect.objectContaining({ headers: { 'If-Match': 'history-v2' } }))
  })
})
