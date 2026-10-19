import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as authApi from './auth'
import { apiClient } from './request'

vi.mock('./request', () => ({ apiClient: { get: vi.fn(), post: vi.fn(), delete: vi.fn() } }))

describe('企业微信扫码 API', () => {
  beforeEach(() => vi.clearAllMocks())

  it('先初始化匿名会话和 CSRF，再申请扫码会话', async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ data: { authenticated: false, user: null } })
    const session = { login_type: 'CorpApp', appid: 'ww-example', agentid: '1000010', state: 'state-one', redirect_uri: 'https://erp.example/api/auth/wecom/callback/', expires_at: '2026-10-19T12:00:00Z' }
    vi.mocked(apiClient.post).mockResolvedValue({ data: session })
    expect(authApi.createWeComQrSession).toBeTypeOf('function')
    expect(await authApi.createWeComQrSession('/customers')).toEqual(session)
    expect(apiClient.get).toHaveBeenCalledWith('/api/auth/me/')
    expect(apiClient.post).toHaveBeenCalledWith('/api/auth/wecom/qr/', { next: '/customers' })
    expect(vi.mocked(apiClient.get).mock.invocationCallOrder[0]).toBeLessThan(vi.mocked(apiClient.post).mock.invocationCallOrder[0]!)
  })

  it('已有登录会话时不创建另一个扫码会话', async () => {
    const response = { authenticated: true, user: { username: 'existing-user' } }
    vi.mocked(apiClient.get).mockResolvedValue({ data: response })
    expect(authApi.createWeComQrSession).toBeTypeOf('function')
    await expect(authApi.createWeComQrSession('/')).rejects.toMatchObject({ response })
    expect(apiClient.post).not.toHaveBeenCalled()
  })

  it('取消绑定具体 state，接口失败继续向调用方报告', async () => {
    vi.mocked(apiClient.delete).mockRejectedValue(new Error('network unavailable'))
    expect(authApi.cancelWeComQrSession).toBeTypeOf('function')
    await expect(authApi.cancelWeComQrSession('state-one')).rejects.toThrow('network unavailable')
    expect(apiClient.delete).toHaveBeenCalledWith('/api/auth/wecom/qr/', { data: { state: 'state-one' } })
  })
})
