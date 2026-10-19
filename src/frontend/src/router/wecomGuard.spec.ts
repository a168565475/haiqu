import { describe, expect, it } from 'vitest'
import { wecomRouteRedirect } from './wecomGuard'

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
