import { AxiosError, isCancel, type InternalAxiosRequestConfig } from 'axios'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { apiClient } from './request'
import { installIdentityRequestGuard } from './identityGuard'
import { dispositionFilename, fetchProtectedResource, locateResource, safeResourceFilename } from './protectedResources'

// 真实 Axios/拦截器 + 内存 adapter；不是真实 Session 或员工验收。
const defaults = { adapter: apiClient.defaults.adapter, baseURL: apiClient.defaults.baseURL }
const disposers: Array<() => void> = []
const context = { generation: 1, version: null as string | null, blocked: false }
let conflict = vi.fn()
function response(config: InternalAxiosRequestConfig, data: unknown) {
  return { config, data, status: 200, statusText: 'OK', headers: {} }
}
function fail(config: InternalAxiosRequestConfig, status: number, data: unknown) {
  return new AxiosError('读取失败', undefined, config, undefined, { ...response(config, data), status })
}
beforeEach(() => {
  apiClient.defaults.baseURL = 'https://api.test'
  Object.assign(context, { generation: 1, version: null, blocked: false })
  conflict = vi.fn()
  disposers.push(installIdentityRequestGuard(apiClient, () => context, conflict))
})
afterEach(() => { disposers.splice(0).forEach(dispose => dispose()); Object.assign(apiClient.defaults, defaults) })

describe('受保护资源请求契约', () => {
  it('普通登录、A、B、同账号新版本、返回管理员始终使用当前版本及既有凭据配置', async () => {
    const adapter = vi.fn(async (config: InternalAxiosRequestConfig) => response(config, new Blob(['image'], { type: 'image/png' })))
    apiClient.defaults.adapter = adapter
    for (const version of [null, 'A1', 'B1', 'B2', 'ADMIN2']) {
      context.version = version; context.generation++
      const controller = new AbortController()
      const result = await fetchProtectedResource('/api/v1/files/1/?revision=2', { signal: controller.signal })
      expect(result.blob.size).toBe(5)
      const config = adapter.mock.calls.at(-1)![0]
      expect(config.url).toBe('https://api.test/api/v1/files/1/?revision=2')
      expect(config.headers.get('X-Identity-Version') || null).toBe(version)
      expect(config).toMatchObject({ withCredentials: true, withXSRFToken: true, responseType: 'blob', timeout: 5000 })
      expect(config.headers.get('Accept')).toBe('application/json')
      expect(config.signal).toBe(controller.signal)
    }
  })

  it.each([
    ['/api/v1/files/1/', 'protected'], ['api/v1/files/1/', 'protected'],
    ['https://api.test/api/v1/files/1/', 'protected'], ['https://browser.test/api/v1/files/1/', 'protected'],
    ['/assets/static.png', 'public'], ['blob:https://browser.test/local', 'public'], ['data:image/png;base64,eA==', 'public'],
    ['https://outside.test/static.png', 'public'], ['https://outside.test/api/v1/files/1/', 'invalid'],
    ['//outside.test/api/v1/files/1/', 'invalid'], ['https://user:pass@api.test/api/v1/files/1/', 'invalid'],
    ['javascript:alert(1)', 'invalid'], ['/a/../%61pi/v1/files/1/', 'invalid'],
    ['/api%252fv1/files/1/', 'invalid'], ['/api\\v1/files/1/', 'invalid'], ['/api', 'invalid'],
  ])('正确分类 %s → %s', (source, kind) => {
    const result = locateResource(source, { apiBaseURL: 'https://api.test', browserURL: 'https://browser.test/page' })
    expect(result.kind).toBe(kind)
    if (kind === 'protected') expect(result.url.startsWith('https://api.test/api/')).toBe(true)
  })

  it('相对 API 配置和开发代理只归一化到可信客户端 origin', () => {
    expect(locateResource('/api/v1/f/', { apiBaseURL: '/', browserURL: 'https://erp.test/page' }))
      .toMatchObject({ kind: 'protected', url: 'https://erp.test/api/v1/f/' })
    expect(locateResource('http://erp.test:8080/api/v1/f/?v=2', { apiBaseURL: 'http://erp.test:8000', browserURL: 'http://erp.test:8080/p' }))
      .toMatchObject({ kind: 'protected', url: 'http://erp.test:8000/api/v1/f/?v=2' })
  })

  it('未知外站、静态或本地地址不会进入带凭据客户端', async () => {
    const adapter = vi.fn(); apiClient.defaults.adapter = adapter
    for (const source of ['https://outside.test/api/v1/files/1/', '/assets/1.png', 'blob:local', 'data:image/png;base64,eA==']) {
      await expect(fetchProtectedResource(source)).rejects.toThrow('可信')
    }
    expect(adapter).not.toHaveBeenCalled()
  })

  it.each([new Blob([]), new Blob(['{"error":{}}'], { type: 'application/json' }), new Blob(['<html>login</html>'], { type: 'text/html' }), 'not a blob'])('损坏或非文件响应不会变成成功文件 %#', async data => {
    apiClient.defaults.adapter = async config => response(config, data)
    await expect(fetchProtectedResource('/api/v1/files/1/')).rejects.toThrow('有效文件')
  })

  it('保留 Content-Disposition 文件名并清理路径与控制字符', async () => {
    apiClient.defaults.adapter = async config => ({ ...response(config, new Blob(['xlsx'])),
      headers: { 'content-disposition': "attachment; filename*=UTF-8''%E6%A8%A1%E6%9D%BF.xlsx" } })
    expect((await fetchProtectedResource('/api/v1/template/')).filename).toBe('模板.xlsx')
    expect(dispositionFilename('attachment; filename*=UTF-8\'\'%XX; filename="fallback.pdf"')).toBe('fallback.pdf')
    expect(safeResourceFilename('../a\u0000.xlsx')).toBe('.._a_.xlsx')
  })
})

describe('Blob 身份错误', () => {
  it.each([[409, 'IDENTITY_VERSION_CONFLICT'], [428, 'IDENTITY_VERSION_REQUIRED']])('%i + %s 准确通知且同代去重，不重试', async (status, code) => {
    const adapter = vi.fn(async (config: InternalAxiosRequestConfig) => { throw fail(config, Number(status), new Blob([JSON.stringify({ error: { code } })], { type: 'application/json' })) })
    apiClient.defaults.adapter = adapter
    await Promise.all([1, 2].map(() => fetchProtectedResource('/api/v1/files/1/').catch(error => error)))
    expect(conflict).toHaveBeenCalledOnce(); expect(adapter).toHaveBeenCalledTimes(2)
  })

  it.each([
    [409, 'BUSINESS_CONFLICT', 'application/json'], [403, 'IDENTITY_VERSION_CONFLICT', 'application/json'],
    [404, 'NOT_FOUND', 'application/json'], [500, 'IDENTITY_VERSION_CONFLICT', 'application/json'],
    [428, 'IDENTITY_VERSION_REQUIRED', 'text/html'],
  ])('普通错误 %i/%s/%s 不误判', async (status, code, type) => {
    apiClient.defaults.adapter = async config => { throw fail(config, status, new Blob([JSON.stringify({ error: { code } })], { type })) }
    await expect(fetchProtectedResource('/api/v1/files/1/')).rejects.toBeInstanceOf(AxiosError)
    expect(conflict).not.toHaveBeenCalled()
  })

  it.each(['{bad', 'x'.repeat(65 * 1024)])('损坏或过大的 JSON 保留原错误 %#', async body => {
    apiClient.defaults.adapter = async config => { throw fail(config, 428, new Blob([body], { type: 'application/json' })) }
    await expect(fetchProtectedResource('/api/v1/files/1/')).rejects.toBeInstanceOf(AxiosError)
    expect(conflict).not.toHaveBeenCalled()
  })

  it.each(['identity', 'abort'])('异步 Blob 解析期间 %s 变化，丢弃旧错误', async change => {
    let finish!: (text: string) => void
    let started!: () => void
    const reading = new Promise<void>(resolve => { started = resolve })
    const blob = new Blob(['error'], { type: 'application/json' })
    Object.defineProperty(blob, 'text', { value: () => { started(); return new Promise<string>(resolve => { finish = resolve }) } })
    const controller = new AbortController()
    apiClient.defaults.adapter = async config => { throw fail(config, 428, blob) }
    const pending = fetchProtectedResource('/api/v1/files/1/', { signal: controller.signal }).catch(error => error)
    await reading
    if (change === 'identity') { context.generation++; context.version = 'new-user' } else controller.abort()
    finish('{"error":{"code":"IDENTITY_VERSION_REQUIRED"}}')
    const error = await pending
    expect(isCancel(error)).toBe(true); expect(error.response).toBeUndefined()
    expect(conflict).not.toHaveBeenCalled()
  })

  it('网络失败不触发身份冲突', async () => {
    apiClient.defaults.adapter = async () => { throw new AxiosError('Network Error', 'ERR_NETWORK') }
    await expect(fetchProtectedResource('/api/v1/files/1/')).rejects.toMatchObject({ code: 'ERR_NETWORK' })
    expect(conflict).not.toHaveBeenCalled()
  })
})
