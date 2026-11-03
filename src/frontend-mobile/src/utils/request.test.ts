import { AxiosError, AxiosHeaders, isCancel } from 'axios'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { apiClient, setRequestIdentity } from './request'

afterEach(() => { setRequestIdentity(null); vi.restoreAllMocks() })
describe('手机身份请求', () => {
  it('业务接口要求企微授权时通知等待页，保留原错误', async () => {
    const notify = vi.spyOn(window, 'dispatchEvent')
    let original!: AxiosError
    const result = await apiClient.get('/api/v1/example/', { adapter: async config => {
      original = new AxiosError('waiting', 'ERR_BAD_REQUEST', config, undefined, {
        data: { error: { code: 'WECOM_ROLE_REQUIRED' } }, status: 403, statusText: 'Forbidden', headers: {}, config,
      })
      throw original
    } }).catch(error => error)
    expect(result).toBe(original)
    expect(notify).toHaveBeenCalledWith(expect.objectContaining({ type: 'mobile-role-required' }))
  })
  it('携带当前身份版本，保留 Session 和 CSRF 契约', async () => {
    setRequestIdentity('current-version')
    const response = await apiClient.get('/api/v1/example/', { adapter: async config => {
      expect(config.headers.get('X-Identity-Version')).toBe('current-version')
      expect(config.withCredentials).toBe(true)
      expect(config.xsrfHeaderName).toBe('X-CSRFToken')
      return { data: {}, status: 200, statusText: 'OK', headers: {}, config }
    } })
    expect(response.status).toBe(200)
  })
  it('拒绝身份切换前开始的旧响应', async () => {
    setRequestIdentity('old')
    let resolveResponse!: () => void
    const pending = apiClient.get('/api/v1/example/', { adapter: config => new Promise(resolve => {
      resolveResponse = () => resolve({ data: { private: true }, status: 200, statusText: 'OK', headers: {}, config })
    }) })
    setRequestIdentity('new')
    resolveResponse()
    expect(await pending.catch(isCancel)).toBe(true)
  })
  it('识别统一封装的身份冲突并通知页面退出当前上下文', async () => {
    setRequestIdentity('old')
    const notify = vi.spyOn(window, 'dispatchEvent')
    await apiClient.get('/api/v1/example/', { adapter: async config => {
      throw new AxiosError('conflict', 'ERR_BAD_REQUEST', config, undefined, {
        data: { error: { code: 'IDENTITY_VERSION_CONFLICT', message: '身份已变化' } },
        status: 409, statusText: 'Conflict', headers: {}, config,
      })
    } }).catch(() => undefined)
    expect(notify).toHaveBeenCalledWith(expect.objectContaining({ type: 'mobile-session-invalid' }))
  })
  it('不把身份头发送到外部地址', async () => {
    const adapter = vi.fn()
    await expect(apiClient.get('https://example.com/api/private/', { adapter, headers: new AxiosHeaders() })).rejects.toThrow('无效的接口地址')
    expect(adapter).not.toHaveBeenCalled()
  })
  it('普通账号身份被清除时也拒绝旧响应，即使两个身份版本都为 null', async () => {
    setRequestIdentity(null)
    let resolveResponse!: () => void
    const pending = apiClient.get('/api/v1/example/', { adapter: config => new Promise(resolve => {
      resolveResponse = () => resolve({ data: { private: true }, status: 200, statusText: 'OK', headers: {}, config })
    }) })
    setRequestIdentity(null, true)
    resolveResponse()
    expect(await pending.catch(isCancel)).toBe(true)
  })
  it('失效的切换会话通知页面重新登录，保留原错误供密码登录恢复', async () => {
    const notify = vi.spyOn(window, 'dispatchEvent')
    let original!: AxiosError
    const result = await apiClient.get('/api/auth/me/', { adapter: async config => {
      original = new AxiosError('invalid', 'ERR_BAD_REQUEST', config, undefined, {
        data: { error: { code: 'IDENTITY_CONTEXT_INVALID' } }, status: 403, statusText: 'Forbidden', headers: {}, config,
      })
      throw original
    } }).catch(error => error)
    expect(result).toBe(original)
    expect(notify).toHaveBeenCalledWith(expect.objectContaining({ type: 'mobile-session-invalid' }))
  })
})
