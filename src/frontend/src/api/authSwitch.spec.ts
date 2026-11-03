import { AxiosError, isCancel } from 'axios'
import type { InternalAxiosRequestConfig } from 'axios'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { fetchCurrentUser, fetchSwitchTargets, returnAdmin, switchAccount } from './auth'
import { apiClient } from './request'
import type { AuthResponse, SwitchTargetsResponse } from '@/types/auth'

// Contract unit tests only: the real Axios pipeline ends at this in-memory adapter.
// No request reaches a server and no actual identity switch is performed.
const originalAdapter = apiClient.defaults.adapter
const employeeId = '00000000-0000-4000-8000-000000000001'
let requests: InternalAxiosRequestConfig[]
let responseData: unknown

function authResponse(active: boolean): AuthResponse {
  return {
    authenticated: true,
    user: {
      id: active ? 7 : 1,
      username: active ? 'employee-one' : 'admin',
      display_name: active ? '测试员工' : '管理员',
      is_superuser: !active,
      employee: active ? { id: employeeId, employee_code: 'E001', display_name: '测试员工', status: 'ACTIVE' } : null,
      permissions: [],
      data_scope: active ? 'ASSIGNED_AND_GRANTED' : 'ALL',
    },
    account_switch: {
      active,
      can_return: active,
      identity_version: active ? 'opaque-employee-version' : 'opaque-admin-version',
    },
  }
}

beforeEach(() => {
  requests = []
  responseData = { results: [], identity_version: 'opaque-current-version' } satisfies SwitchTargetsResponse
  apiClient.defaults.adapter = async config => {
    requests.push(config)
    return { status: 200, statusText: 'OK', config, headers: {}, data: responseData }
  }
})

afterEach(() => {
  apiClient.defaults.adapter = originalAdapter
})

describe('账号切换 API 契约（真实 Axios、内存适配器）', () => {
  it('部门和角色通过Axios查询参数提交，保持取消信号及GET行为', async () => {
    const signal = new AbortController().signal
    await fetchSwitchTargets('李', signal, { department_id: employeeId, role_id: employeeId })
    expect(requests[0]!.params).toEqual({ q: '李', department_id: employeeId, role_id: employeeId })
    expect(requests[0]!.signal).toBe(signal)
    expect(requests[0]!.method).toBe('get')
    expect(requests[0]!.data).toBeUndefined()
  })

  it('候选查询使用精确 GET 路径、原样 q 和调用方取消信号，保留完整响应', async () => {
    const signal = new AbortController().signal
    const body: SwitchTargetsResponse = {
      results: [{ employee_id: employeeId, user_id: 7, username: 'employee-one', employee_code: 'E001', display_name: '测试员工' }],
      identity_version: 'opaque-list-version',
    }
    responseData = body

    expect(await fetchSwitchTargets(' E001 +& ', signal)).toBe(body)
    expect(requests).toHaveLength(1)
    const request = requests[0]!
    expect(request.url).toBe('/api/auth/switch-targets/')
    expect(request.method).toBe('get')
    expect(request.params).toEqual({ q: ' E001 +& ' })
    expect(request.signal).toBe(signal)
    expect(request.data).toBeUndefined()
  })

  it('由 Axios 序列化查询字符串，不手拼 URL 或吞掉特殊字符', async () => {
    await fetchSwitchTargets('E 001+&')

    expect(apiClient.getUri(requests[0]!)).toBe(
      `${apiClient.defaults.baseURL?.replace(/\/$/, '')}/api/auth/switch-targets/?q=E+001%2B%26`,
    )
  })

  it('省略 q 和 signal 时仍查询候选，未定义参数不进入最终 URL', async () => {
    const result = await fetchSwitchTargets()

    expect(result).toBe(responseData)
    expect(requests).toHaveLength(1)
    expect(requests[0]!.url).toBe('/api/auth/switch-targets/')
    expect(requests[0]!.params).toEqual({ q: undefined })
    expect(requests[0]!.signal).toBeUndefined()
    expect(apiClient.getUri(requests[0]!)).toBe(
      `${apiClient.defaults.baseURL?.replace(/\/$/, '')}/api/auth/switch-targets/`,
    )
  })

  it.each(['', '   ', '员工/Case', 'x'.repeat(101)])('查询 %j 原样提交给后端校验，不按前端规则改写', async q => {
    await fetchSwitchTargets(q)

    expect(requests).toHaveLength(1)
    expect(requests[0]!.params).toEqual({ q })
  })

  it('已取消的候选读取由 Axios 拒绝，不调用适配器也不返回伪空列表', async () => {
    const controller = new AbortController()
    controller.abort()

    const result = await fetchSwitchTargets('E001', controller.signal).catch(error => error)

    expect(isCancel(result)).toBe(true)
    expect(requests).toHaveLength(0)
  })

  it('切换仅 POST 字符串 employee_id，真实 Axios 将请求体编码为精确 JSON', async () => {
    const body = authResponse(true)
    responseData = body

    expect(await switchAccount(employeeId)).toBe(body)
    expect(requests).toHaveLength(1)
    const request = requests[0]!
    expect(request.url).toBe('/api/auth/switch/')
    expect(request.method).toBe('post')
    expect(request.data).toBe(JSON.stringify({ employee_id: employeeId }))
    expect(request.params).toBeUndefined()
    expect(request.headers.get('Content-Type')).toBe('application/json')
  })

  it('返回管理员只 POST 空 JSON 对象，不提交任何管理员或员工标识', async () => {
    const body = authResponse(false)
    responseData = body

    expect(await returnAdmin()).toBe(body)
    expect(requests).toHaveLength(1)
    const request = requests[0]!
    expect(request.url).toBe('/api/auth/return-admin/')
    expect(request.method).toBe('post')
    expect(request.data).toBe('{}')
    expect(request.params).toBeUndefined()
    expect(request.headers.get('Content-Type')).toBe('application/json')
  })

  it('三个新接口沿用既有 Session/CSRF Axios 配置，不另建无凭据客户端', async () => {
    await fetchSwitchTargets()
    responseData = authResponse(true)
    await switchAccount(employeeId)
    responseData = authResponse(false)
    await returnAdmin()

    expect(requests).toHaveLength(3)
    for (const request of requests) {
      expect(request.baseURL).toBe(apiClient.defaults.baseURL)
      expect(request.timeout).toBe(5000)
      expect(request.withCredentials).toBe(true)
      expect(request.withXSRFToken).toBe(true)
      expect(request.xsrfCookieName).toBe('csrftoken')
      expect(request.xsrfHeaderName).toBe('X-CSRFToken')
      expect(request.headers.get('Accept')).toBe('application/json')
    }
  })

  it('API 层不把响应版本写回请求默认头，也不额外刷新身份或自动发起转换', async () => {
    const headersBefore = JSON.stringify(apiClient.defaults.headers)
    await fetchSwitchTargets()
    responseData = authResponse(true)
    await switchAccount(employeeId)
    responseData = authResponse(false)
    await returnAdmin()

    expect(JSON.stringify(apiClient.defaults.headers)).toBe(headersBefore)
    expect(requests.map(request => [request.method, request.url])).toEqual([
      ['get', '/api/auth/switch-targets/'],
      ['post', '/api/auth/switch/'],
      ['post', '/api/auth/return-admin/'],
    ])
    expect(requests.every(request => request.headers.get('X-Identity-Version') === undefined)).toBe(true)
  })

  it('兼容缺少可选 account_switch 的既有认证响应，不补造可返回状态或版本', async () => {
    const body: AuthResponse = { authenticated: false, user: null }
    responseData = body

    expect(await fetchCurrentUser()).toBe(body)
    expect(await returnAdmin()).toBe(body)
    expect(body).not.toHaveProperty('account_switch')
    expect(requests.map(request => request.url)).toEqual(['/api/auth/me/', '/api/auth/return-admin/'])
  })

  it.each([400, 403, 404, 409, 428, 500])('三个新接口的 %i 适配器错误原样拒绝，不包装成功、不重试', async status => {
    let adapterError: AxiosError | undefined
    const errorBody = { error: { code: 'SERVER_ERROR', message: '后端拒绝', field_errors: {}, request_id: 'trace-unit' } }
    apiClient.defaults.adapter = async config => {
      requests.push(config)
      adapterError = new AxiosError('rejected', undefined, config, undefined, {
        status, statusText: 'Rejected', config, headers: {}, data: errorBody,
      })
      throw adapterError
    }

    for (const request of [() => fetchSwitchTargets('E001'), () => switchAccount(employeeId), () => returnAdmin()]) {
      const countBefore = requests.length
      const result = await request().catch(error => error)
      expect(result).toBe(adapterError)
      expect(result.response.status).toBe(status)
      expect(result.response.data).toBe(errorBody)
      expect(requests).toHaveLength(countBefore + 1)
    }
  })
})
