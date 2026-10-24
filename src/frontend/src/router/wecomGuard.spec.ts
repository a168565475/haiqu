import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { startWeComLoginIfNeeded, wecomRouteRedirect } from './wecomGuard'

describe('企业微信待授权路由边界', () => {
  it('等待用户访问业务或密码登录页时回到等待页', () => {
    expect(wecomRouteRedirect('customers', true, true)).toEqual({ name: 'waiting-role' })
    expect(wecomRouteRedirect('login', true, true)).toEqual({ name: 'waiting-role' })
  })
  it('等待页和错误页不重定向自身，授权后离开等待页', () => {
    expect(wecomRouteRedirect('waiting-role', true, true)).toBeUndefined()
    expect(wecomRouteRedirect('wecom-error', true, true)).toBeUndefined()
    expect(wecomRouteRedirect('waiting-role', true, false)).toEqual({ name: 'home' })
  })
  it('旧密码账号和匿名用户仍由现有登录守卫处理', () => {
    expect(wecomRouteRedirect('customers', true, false)).toBeUndefined()
    expect(wecomRouteRedirect('waiting-role', false, false)).toBeUndefined()
  })
})

describe('企业微信根网址自动授权入口', () => {
  const replace = vi.fn()
  const storage = window.sessionStorage
  beforeEach(() => {
    replace.mockClear()
    storage.clear()
    vi.stubGlobal('window', { location: { replace }, sessionStorage: storage })
    vi.stubGlobal('navigator', { userAgent: 'Mozilla/5.0 MicroMessenger/8.0 wxwork/4.1.0' })
  })
  afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); storage.clear() })

  it('企业微信匿名访问根页时跳固定授权入口并传本站回跳路径', () => {
    expect(startWeComLoginIfNeeded('home', true, false)).toBe(true)
    expect(replace).toHaveBeenCalledExactlyOnceWith('/api/auth/wecom/start/?next=%2F')
  })
  it('卡片通知参数作为一个编码后的next传递，由后端校验并绑定会话', () => {
    const path = '/?notification=12345678-1234-1234-1234-123456789abc'
    expect(startWeComLoginIfNeeded('home', true, false, path)).toBe(true)
    expect(replace).toHaveBeenCalledExactlyOnceWith(`/api/auth/wecom/start/?next=${encodeURIComponent(path)}`)
  })
  it('Windows 企业微信受保护深链接也会发起授权', () => {
    vi.stubGlobal('navigator', { userAgent: 'Mozilla/5.0 WindowsWechat WXWork/4.1.36' })
    expect(startWeComLoginIfNeeded('customers', true, false)).toBe(true)
  })
  it.each(['Mozilla/5.0 Chrome/131.0', 'Mozilla/5.0 MicroMessenger/8.0', ''])('普通浏览器和个人微信保留密码入口：%s', userAgent => {
    vi.stubGlobal('navigator', { userAgent })
    expect(startWeComLoginIfNeeded('home', true, false)).toBe(false)
    expect(replace).not.toHaveBeenCalled()
  })
  it.each([['login', false], ['wecom-error', false], ['waiting-role', true]] as const)('%s 不自动授权', (name, requiresAuth) => {
    expect(startWeComLoginIfNeeded(name, requiresAuth, false)).toBe(false)
    expect(replace).not.toHaveBeenCalled()
  })
  it('有效会话直接使用现有身份，不发起企微授权', () => {
    expect(startWeComLoginIfNeeded('home', true, true)).toBe(false)
    expect(replace).not.toHaveBeenCalled()
  })
  it('全页回跳后仍匿名时不重复发起，避免 Cookie 异常引起循环', () => {
    expect(startWeComLoginIfNeeded('home', true, false)).toBe(true)
    expect(startWeComLoginIfNeeded('home', true, false)).toBe(false)
    expect(replace).toHaveBeenCalledTimes(1)
    expect(Object.values(storage)).toEqual(['1'])
  })
  it.each([['login', false, false], ['wecom-error', false, false], ['home', true, true]] as const)('到达 %s 后允许下一次明确进入主页再尝试', (name, requiresAuth, authenticated) => {
    startWeComLoginIfNeeded('home', true, false)
    startWeComLoginIfNeeded(name, requiresAuth, authenticated)
    expect(startWeComLoginIfNeeded('home', true, false)).toBe(true)
    expect(replace).toHaveBeenCalledTimes(2)
  })
  it('会话存储不可写时降级密码登录，不发起无法防循环的授权', () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new DOMException('不可用', 'SecurityError') })
    expect(startWeComLoginIfNeeded('home', true, false)).toBe(false)
    expect(replace).not.toHaveBeenCalled()
  })
})
