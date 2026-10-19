import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { WeComQrSession } from '@/types/auth'
import type { WeComLoginSdk } from './wecomLoginSdk'

function session(): WeComQrSession {
  return { login_type: 'CorpApp', appid: 'ww123456789', agentid: '1000010', state: 'a'.repeat(43), redirect_uri: `${window.location.origin}/api/auth/wecom/callback/`, expires_at: new Date(Date.now() + 300_000).toISOString() }
}

describe('官方企业微信扫码 SDK 边界', () => {
  beforeEach(() => { vi.resetModules(); delete window.ww })
  afterEach(() => {
    vi.useRealTimers()
    delete window.ww
    document.querySelectorAll('script[data-wecom-login-sdk]').forEach(script => script.remove())
  })

  it('只加载固定官方地址，并复用并发加载', async () => {
    const { loadWeComLoginSdk } = await import('./wecomLoginSdk')
    const first = loadWeComLoginSdk()
    const second = loadWeComLoginSdk()
    expect(first).toBe(second)
    const script = document.querySelector<HTMLScriptElement>('script[data-wecom-login-sdk]')!
    expect(script.src).toBe('https://wwcdn.weixin.qq.com/node/wework/wwopen/js/wecom-jssdk-2.4.0.js')
    window.ww = { createWWLoginPanel: vi.fn() } as WeComLoginSdk
    script.dispatchEvent(new Event('load'))
    expect(await first).toBe(window.ww)
  })

  it('加载失败删除本次脚本，下次可重试', async () => {
    const { loadWeComLoginSdk } = await import('./wecomLoginSdk')
    const first = loadWeComLoginSdk()
    const rejected = expect(first).rejects.toThrow('无法加载')
    document.querySelector('script[data-wecom-login-sdk]')!.dispatchEvent(new Event('error'))
    await rejected
    expect(document.querySelector('script[data-wecom-login-sdk]')).toBeNull()
    const second = loadWeComLoginSdk()
    const sdk = { createWWLoginPanel: vi.fn() } as WeComLoginSdk
    window.ww = sdk
    document.querySelector('script[data-wecom-login-sdk]')!.dispatchEvent(new Event('load'))
    expect(await second).toBe(sdk)
  })

  it('超时可恢复，不永久挂起', async () => {
    vi.useFakeTimers()
    const { loadWeComLoginSdk } = await import('./wecomLoginSdk')
    const pending = loadWeComLoginSdk()
    const rejected = expect(pending).rejects.toThrow('加载超时')
    await vi.advanceTimersByTimeAsync(15_000)
    await rejected
  })

  it('只接受同源固定回调，拒绝外站和改写路径', async () => {
    const { validateWeComQrSession } = await import('./wecomLoginSdk')
    expect(() => validateWeComQrSession(session())).not.toThrow()
    for (const redirect_uri of ['https://other.example/api/auth/wecom/callback/', `${window.location.origin}/login`, `${window.location.origin}/api/auth/wecom/callback/?next=https://other.example`]) {
      expect(() => validateWeComQrSession({ ...session(), redirect_uri })).toThrow('固定地址')
    }
  })

  it('回调使用本次会话 state，凭证编码后仅跳固定站内路径', async () => {
    const { buildWeComCallbackUrl } = await import('./wecomLoginSdk')
    const current = session()
    const callback = new URL(buildWeComCallbackUrl(current, 'code+with&symbols'))
    expect(callback.origin).toBe(window.location.origin)
    expect(callback.pathname).toBe('/api/auth/wecom/callback/')
    expect(callback.searchParams.get('state')).toBe(current.state)
    expect(callback.searchParams.get('code')).toBe('code+with&symbols')
    expect(() => buildWeComCallbackUrl(current, 'bad\ncode')).toThrow('凭证无效')
    expect(() => buildWeComCallbackUrl({ ...current, expires_at: '2000-01-01T00:00:00Z' }, 'valid-code')).toThrow('已失效')
  })
})
