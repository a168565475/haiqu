import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { clearWeComLoginAttempt, isWeComBrowser, resolveMobileRedirect, startAutomaticWeComLogin, startWeComLogin } from './wecom'

const replace = vi.fn()
beforeEach(() => {
  sessionStorage.clear()
  replace.mockClear()
  vi.stubGlobal('window', { sessionStorage, location: { replace } })
  vi.stubGlobal('navigator', { userAgent: 'MicroMessenger/8 wxwork/4.1' })
})
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks() })

describe('手机企微入口与回跳', () => {
  it.each(['wxwork/4.1', 'MicroMessenger/8 WXWork/4.0 Windows'])('识别企业微信 %s', value => {
    expect(isWeComBrowser(value)).toBe(true)
  })
  it.each(['MicroMessenger/8', 'Mozilla/5.0 Chrome/140', 'notwxwork/4'])('普通微信和浏览器不自动授权 %s', value => {
    expect(isWeComBrowser(value)).toBe(false)
  })
  it.each([
    ['/m/', '/'], ['/m', '/'], ['/m/plan?id=123&category=CUTTING', '/plan?id=123&category=CUTTING'],
    ['/report?plan=123#workers', '/report?plan=123#workers'],
  ])('安全业务路径 %s 变为内部路由', (value, result) => {
    expect(resolveMobileRedirect(value)).toBe(result)
  })
  it.each([undefined, ['//evil.test'], 'https://evil.test', '//evil.test', '/m//evil.test', '/\\evil.test',
    '/m/%5cevil.test', '/%2fexample.test', '/m/../api', '/m/%2e%2e/api', '/m/login', '/m/auth/wecom-error',
    '/AUTH/waiting-role', '/m/%61uth/waiting-role', '/api/auth/wecom/start/', '/admin', '/m/m/plan', '/m/%', '/plan?x=%0a'])('拒绝外站、认证循环与非法路径 %s', value => {
    expect(resolveMobileRedirect(value)).toBe('/')
  })
  it('完整手机深链只编码一次并发往同源 ERP OAuth', () => {
    expect(startWeComLogin('/plan?id=abc&category=CUTTING')).toBe(true)
    expect(replace).toHaveBeenCalledWith('/api/auth/wecom/start/?next=%2Fm%2Fplan%3Fid%3Dabc%26category%3DCUTTING')
  })
  it('Cookie 丢失后的匿名回跳只自动尝试一次，明确重试仍可发起', () => {
    expect(startAutomaticWeComLogin('/', false)).toBe(true)
    expect(startAutomaticWeComLogin('/', false)).toBe(false)
    expect(startWeComLogin('/')).toBe(true)
    expect(replace).toHaveBeenCalledTimes(2)
    clearWeComLoginAttempt()
    expect(startAutomaticWeComLogin('/', false)).toBe(true)
  })
  it('匿名但能返回管理员时不覆盖原有身份恢复凭据', () => {
    expect(startAutomaticWeComLogin('/', true)).toBe(false)
    expect(replace).not.toHaveBeenCalled()
  })
  it('普通浏览器不发起自动授权', () => {
    vi.stubGlobal('navigator', { userAgent: 'MicroMessenger/8' })
    expect(startAutomaticWeComLogin('/', false)).toBe(false)
    expect(replace).not.toHaveBeenCalled()
  })
  it('会话存储禁用时保留密码入口，不能进入无限授权', () => {
    vi.stubGlobal('window', { get sessionStorage() { throw new Error('disabled') }, location: { replace } })
    expect(startAutomaticWeComLogin('/', false)).toBe(false)
    expect(startWeComLogin('/')).toBe(false)
    expect(clearWeComLoginAttempt()).toBe(false)
    expect(replace).not.toHaveBeenCalled()
  })
})
