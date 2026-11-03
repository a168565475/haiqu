import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mobileAuthGuard } from './authGuard'

const mocks = vi.hoisted(() => ({
  auth: { user: null as { waiting_for_role?: boolean } | null, accountSwitch: null as { can_return: boolean } | null, refresh: vi.fn() },
  start: vi.fn(), clear: vi.fn(),
}))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => mocks.auth }))
vi.mock('@/utils/wecom', async importOriginal => ({
  ...await importOriginal<object>(), startAutomaticWeComLogin: mocks.start, clearWeComLoginAttempt: mocks.clear,
}))
const route = (path = '/', query = {}) => ({ path, fullPath: path, query })
beforeEach(() => { vi.resetAllMocks(); mocks.auth.user = null; mocks.auth.accountSwitch = null })

describe('手机认证路由', () => {
  it.each(['/login', '/auth/wecom-error'])('恢复页 %s 不自动发起授权', async path => {
    expect(await mobileAuthGuard(route(path))).toBeUndefined()
    expect(mocks.auth.refresh).not.toHaveBeenCalled()
    expect(mocks.start).not.toHaveBeenCalled()
  })
  it('先核实 ERP 会话，再自动授权并中止当前导航', async () => {
    mocks.auth.refresh.mockImplementation(() => { expect(mocks.start).not.toHaveBeenCalled() })
    mocks.start.mockReturnValue(true)
    expect(await mobileAuthGuard(route('/plan?id=123'))).toBe(false)
    expect(mocks.start).toHaveBeenCalledWith('/plan?id=123', false)
  })
  it('已有有效 ERP 会话（含切换身份）直接进入业务，不强制 OAuth', async () => {
    mocks.auth.user = {}
    mocks.auth.accountSwitch = { can_return: true }
    expect(await mobileAuthGuard(route())).toBeUndefined()
    expect(mocks.clear).toHaveBeenCalledOnce()
    expect(mocks.start).not.toHaveBeenCalled()
  })
  it('将匿名可返回管理员状态传给授权入口，回到登录恢复', async () => {
    mocks.auth.accountSwitch = { can_return: true }
    expect(await mobileAuthGuard(route())).toEqual({ path: '/login', query: { redirect: '/' } })
    expect(mocks.start).toHaveBeenCalledWith('/', true)
  })
  it('会话接口网络失败不冒充匿名发起授权', async () => {
    mocks.auth.refresh.mockRejectedValue(new Error('network'))
    expect(await mobileAuthGuard(route('/plan'))).toEqual({ path: '/login', query: { redirect: '/plan', reason: 'connection' } })
    expect(mocks.start).not.toHaveBeenCalled()
  })
  it('等待授权的账号不能进入业务页且保留原目标', async () => {
    mocks.auth.user = { waiting_for_role: true }
    expect(await mobileAuthGuard(route('/report?plan=1'))).toEqual({ path: '/auth/waiting-role', query: { next: '/report?plan=1' } })
    expect(await mobileAuthGuard(route('/auth/waiting-role', { next: '/m/report?plan=1' }))).toBeUndefined()
  })
  it('分配权限后返回原手机业务页', async () => {
    mocks.auth.user = { waiting_for_role: false }
    expect(await mobileAuthGuard(route('/auth/waiting-role', { next: '/m/report?plan=1' }))).toBe('/report?plan=1')
  })
  it('匿名等待页回密码登录而不自动授权', async () => {
    expect(await mobileAuthGuard(route('/auth/waiting-role', { next: '/m/report?plan=1' }))).toEqual({ path: '/login', query: { redirect: '/report?plan=1' } })
    expect(mocks.start).not.toHaveBeenCalled()
  })
})
