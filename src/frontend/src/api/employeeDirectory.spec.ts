import { AxiosError } from 'axios'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { apiClient } from './request'
import {
  employeeDirectoryError, getDepartmentMappings, getEmployeeDirectoryPreview, refreshDepartmentMappings, refreshEmployeeDirectory,
  matchEmployeeDirectory, saveDepartmentMapping, syncEmployeeDirectory,
} from './employeeDirectory'

afterEach(() => vi.restoreAllMocks())

describe('统一员工通讯录 API', () => {
  it('预览默认不补部门，保留完整来源与带引号的版本', async () => {
    const data = { corp_id: 'corp', departments: [], members: [], preview_token: 'preview', apply_departments: false }
    const get = vi.spyOn(apiClient, 'get').mockResolvedValue({ data: { data }, headers: { etag: '"directory-v1"' } })
    await expect(getEmployeeDirectoryPreview()).resolves.toEqual({ data, etag: '"directory-v1"' })
    expect(get).toHaveBeenCalledWith('/api/v1/wecom/employee-directory/', {
      timeout: 120000, params: { apply_departments: false },
    })
  })

  it('可信副本保留独立can_submit/can_refresh及签名，不因配置不可用丢弃保存预览', async () => {
    const data = { snapshot: { status: 'CONFIG_UNAVAILABLE', can_submit: true, can_refresh: false }, corp_id: 'corp', departments: [], members: [], preview_token: 'saved-source-token', apply_departments: false }
    const get = vi.spyOn(apiClient, 'get').mockResolvedValue({ data: { data }, headers: { etag: '"saved-source-v1"' } })
    const post = vi.spyOn(apiClient, 'post')
    await expect(getEmployeeDirectoryPreview()).resolves.toEqual({ data, etag: '"saved-source-v1"' })
    expect(get).toHaveBeenCalledOnce(); expect(post).not.toHaveBeenCalled()
  })

  it('只有显式启用时才预览部门补充', async () => {
    const get = vi.spyOn(apiClient, 'get').mockResolvedValue({ data: { data: { apply_departments: true } }, headers: { etag: '"v1"' } })
    await getEmployeeDirectoryPreview(true)
    expect(get).toHaveBeenCalledWith('/api/v1/wecom/employee-directory/', expect.objectContaining({ params: { apply_departments: true } }))
  })

  it.each([undefined, '', '   ', 123])('目录或映射缺失有效 ETag %s 时不返回可提交预览', async etag => {
    vi.spyOn(apiClient, 'get').mockResolvedValue({ data: { data: {} }, headers: { etag } })
    await expect(getEmployeeDirectoryPreview()).rejects.toThrow('预览版本缺失')
    await expect(getDepartmentMappings()).rejects.toThrow('预览版本缺失')
  })

  it('主动刷新使用POST，员工模式与部门空JSON准确传递', async () => {
    const data = { snapshot: { status: 'MISSING', can_submit: false }, preview_token: '' }
    const post = vi.spyOn(apiClient, 'post').mockResolvedValue({ data: { data }, headers: { etag: '"v1"' } })
    await expect(refreshEmployeeDirectory(true)).resolves.toEqual({ data, etag: '"v1"' })
    expect(post).toHaveBeenLastCalledWith('/api/v1/wecom/employee-directory/refresh/', { apply_departments: true }, { timeout: 120000 })
    await refreshDepartmentMappings()
    expect(post).toHaveBeenLastCalledWith('/api/v1/wecom/department-mappings/refresh/', {}, { timeout: 120000 })
  })

  it('同步原样提交选择与预览版本，不替用户添加重名新建确认', async () => {
    const payload = { preview_token: 'preview', user_ids: ['Member.A'] }
    const data = [{ user_id: 'Member.A', employee_id: 'employee', result: 'CREATED' }]
    const post = vi.spyOn(apiClient, 'post').mockResolvedValue({ data: { data } })
    await expect(syncEmployeeDirectory(payload, '"directory-v1"')).resolves.toEqual(data)
    expect(post).toHaveBeenCalledWith('/api/v1/wecom/employee-directory/sync/', payload, {
      timeout: 120000, headers: { 'If-Match': '"directory-v1"' },
    })
    expect(post.mock.calls[0]?.[1]).not.toHaveProperty('confirmed_new_user_ids')
    expect(payload).not.toHaveProperty('apply_departments')
  })

  it('明确确认的新建名单和部门模式原样发送并接收部门结果', async () => {
    const payload = { preview_token: 'preview', user_ids: ['Member.A'], confirmed_new_user_ids: ['Member.A'], apply_departments: true }
    const data = [{ user_id: 'Member.A', employee_id: 'employee', result: 'CREATED', department_status: 'PENDING', department_reason: '请先确认部门对应关系。' }]
    const post = vi.spyOn(apiClient, 'post').mockResolvedValue({ data: { data } })
    await expect(syncEmployeeDirectory(payload, '"v1"')).resolves.toEqual(data)
    expect(post.mock.calls[0]?.[1]).toEqual(payload)
  })

  it('人工关联分别携带目录版本和员工版本，不替用户选择员工', async () => {
    const payload = { preview_token: 'preview', user_id: 'Member.A', employee_id: 'employee', employee_etag: '"employee-v2"', confirmed: true as const, apply_departments: false }
    const data = { user_id: 'Member.A', employee_id: 'employee', result: 'MATCHED' }
    const post = vi.spyOn(apiClient, 'post').mockResolvedValue({ data: { data } })
    await expect(matchEmployeeDirectory(payload, '"directory-v1"')).resolves.toEqual(data)
    expect(post).toHaveBeenCalledWith('/api/v1/wecom/employee-directory/match/', payload, {
      timeout: 120000, headers: { 'If-Match': '"directory-v1"' },
    })
  })

  it('部门映射预览保留来源、ERP 候选、签名和独立 ETag', async () => {
    const data = { can_save_mapping: true, corp_id: 'corp', departments: [{ id: 1, parentid: 0, name: '部门', mapping: null, candidates: [] }], organizations: [], preview_token: 'mapping-preview' }
    const get = vi.spyOn(apiClient, 'get').mockResolvedValue({ data: { data }, headers: { etag: '"mapping-v1"' } })
    await expect(getDepartmentMappings()).resolves.toEqual({ data, etag: '"mapping-v1"' })
    expect(get).toHaveBeenCalledWith('/api/v1/wecom/department-mappings/', { timeout: 120000 })
  })

  it('保留独立映射能力，不因通用快照不可提交丢弃签名预览', async () => {
    const data = { can_save_mapping: true, snapshot: { status: 'CONFIG_UNAVAILABLE', can_submit: false }, preview_token: 'mapping-preview' }
    vi.spyOn(apiClient, 'get').mockResolvedValue({ data: { data }, headers: { etag: '"mapping-v1"' } })
    await expect(getDepartmentMappings()).resolves.toEqual({ data, etag: '"mapping-v1"' })
  })

  it('保存映射携带部门版本，清除映射显式提交 null 且不要求目标版本', async () => {
    const put = vi.spyOn(apiClient, 'put').mockResolvedValue({ data: { data: { id: 'mapping' } } })
    const selected = { preview_token: 'preview', organization_unit_id: 'department', organization_etag: '"department-v1"', confirmed: true as const }
    await saveDepartmentMapping(4294967295, selected, '"mapping-v1"')
    expect(put).toHaveBeenLastCalledWith('/api/v1/wecom/department-mappings/4294967295/', selected, {
      timeout: 120000, headers: { 'If-Match': '"mapping-v1"' },
    })
    const cleared = { preview_token: 'new-preview', organization_unit_id: null, confirmed: true as const }
    await expect(saveDepartmentMapping(1, cleared, '"mapping-v2"')).resolves.toEqual({ id: 'mapping' })
    expect(put).toHaveBeenLastCalledWith('/api/v1/wecom/department-mappings/1/', cleared, {
      timeout: 120000, headers: { 'If-Match': '"mapping-v2"' },
    })
  })

  it('提交超时保持失败且不自动重试，不伪装成功或空结果', async () => {
    const error = new AxiosError('timeout', 'ECONNABORTED')
    const post = vi.spyOn(apiClient, 'post').mockRejectedValue(error)
    await expect(syncEmployeeDirectory({ preview_token: 'preview', user_ids: ['Member.A'] }, '"v1"')).rejects.toBe(error)
    expect(post).toHaveBeenCalledTimes(1)
    expect(employeeDirectoryError(error)).toContain('请求未确认完成')
    expect(employeeDirectoryError(error)).toContain('核实结果')
  })

  it('保留预览、人工确认和目标字段的结构化校验错误', () => {
    const error = new AxiosError('request', undefined, undefined, undefined, {
      status: 400, data: { error: { code: 'VALIDATION_ERROR', message: '输入未通过校验', field_errors: {
        preview_token: ['预览已过期'], confirmed_new_user_ids: ['必须是所选成员'],
        organization_etag: ['缺少版本'], private_field: ['不展示的字段'],
      } } },
    } as never)
    const message = employeeDirectoryError(error)
    expect(message).toContain('预览：预览已过期')
    expect(message).toContain('确认新建的成员：必须是所选成员')
    expect(message).toContain('部门版本：缺少版本')
    expect(message).not.toContain('不展示的字段')
  })

  it('版本冲突和未就绪保留安全错误，未知服务器内容不直接展示', () => {
    for (const [status, code, message] of [
      [412, 'PRECONDITION_FAILED', '员工部门计划已变化，请重新预览。'],
      [409, 'CONFLICT', '此企业微信成员已关联其他员工。'],
      [503, 'REQUEST_FAILED', '部门映射尚未完成数据库迁移。'],
    ] as const) {
      expect(employeeDirectoryError(new AxiosError('request', undefined, undefined, undefined, {
        status, data: { error: { code, message } },
      } as never))).toBe(message)
    }
    for (const data of ['<html>private trace</html>', { error: { code: 'UNKNOWN_ERROR', message: 'private trace' } }]) {
      const error = new AxiosError('request', undefined, undefined, undefined, { status: 500, data } as never)
      expect(employeeDirectoryError(error)).not.toContain('private trace')
      expect(employeeDirectoryError(error)).toContain('未确认完成')
    }
  })
})
