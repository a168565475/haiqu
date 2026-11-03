import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import type { VueWrapper } from '@vue/test-utils'
import { Button, Field, Form, Icon } from 'vant'
import LoginPage from './login.vue'

const mocks = vi.hoisted(() => ({
  query: {} as Record<string, unknown>, replace: vi.fn(), start: vi.fn(), clearAttempt: vi.fn(), inWeCom: true,
  auth: {
    user: null as { id: number } | null,
    accountSwitch: null as { active: boolean; can_return: boolean; identity_version: string } | null,
    refresh: vi.fn(), login: vi.fn(),
  },
}))
vi.mock('vue-router', () => ({ useRoute: () => ({ query: mocks.query }), useRouter: () => ({ replace: mocks.replace }) }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => mocks.auth }))
vi.mock('@/utils/wecom', async importOriginal => ({
  ...await importOriginal<typeof import('@/utils/wecom')>(),
  isWeComBrowser: () => mocks.inWeCom, startWeComLogin: mocks.start, clearWeComLoginAttempt: mocks.clearAttempt,
}))
const target = '/plan?schedule_product_id=plan-one&workshop_id=workshop-one'
let wrapper: VueWrapper | undefined
function openPage() {
  wrapper = mount(LoginPage, { global: { components: { VanButton: Button, VanIcon: Icon, VanField: Field, VanForm: Form } } })
  return wrapper
}
async function retry() {
  const button = wrapper!.findAll('button').find(item => item.text() === '使用企业微信登录')
  expect(button).toBeDefined()
  await button!.trigger('click')
  await flushPromises()
}
beforeEach(() => {
  vi.resetAllMocks()
  mocks.query = { redirect: `/m${target}` }
  mocks.inWeCom = true
  mocks.auth.user = null
  mocks.auth.accountSwitch = null
  mocks.auth.refresh.mockResolvedValue(undefined)
  mocks.auth.login.mockResolvedValue(undefined)
  mocks.start.mockReturnValue(true)
})
afterEach(() => { wrapper?.unmount(); wrapper = undefined })

describe('手机登录页企业微信恢复入口', () => {
  it('普通浏览器只有密码入口，页面本身不自动发起授权', () => {
    mocks.inWeCom = false
    const view = openPage()
    expect(view.text()).not.toContain('使用企业微信登录')
    expect(view.find('input[autocomplete="username"]').exists()).toBe(true)
    expect(mocks.auth.refresh).not.toHaveBeenCalled()
    expect(mocks.start).not.toHaveBeenCalled()
  })
  it('企微中主动点击后重新检查会话，匿名用户携安全回跳发起授权', async () => {
    openPage()
    expect(mocks.start).not.toHaveBeenCalled()
    await retry()
    expect(mocks.auth.refresh).toHaveBeenCalledWith(true)
    expect(mocks.start).toHaveBeenCalledExactlyOnceWith(target)
    expect(mocks.replace).not.toHaveBeenCalled()
  })
  it('重新检查发现已登录，直接返回业务页面而不覆盖现有账号', async () => {
    mocks.auth.refresh.mockImplementationOnce(async () => { mocks.auth.user = { id: 12 } })
    openPage()
    await retry()
    expect(mocks.replace).toHaveBeenCalledWith(target)
    expect(mocks.start).not.toHaveBeenCalled()
    expect(mocks.auth.login).not.toHaveBeenCalled()
  })
  it('匿名但保留管理员凭据时不发起授权，显示返回 ERP 的入口', async () => {
    mocks.auth.refresh.mockImplementationOnce(async () => {
      mocks.auth.accountSwitch = { active: true, can_return: true, identity_version: 'v2' }
    })
    const view = openPage()
    await retry()
    expect(mocks.start).not.toHaveBeenCalled()
    expect(mocks.replace).not.toHaveBeenCalled()
    expect(view.get('[role="alert"]').text()).toContain('恢复管理员身份')
    expect(view.get('a').attributes('href')).toBe('/')
  })
  it('检查失败与无法发起授权都给出错误，保留密码入口', async () => {
    mocks.auth.refresh.mockRejectedValueOnce(new Error('登录状态查询失败'))
    const view = openPage()
    await retry()
    expect(view.get('[role="alert"]').text()).toContain('登录状态查询失败')
    expect(mocks.start).not.toHaveBeenCalled()
    mocks.start.mockReturnValue(false)
    await retry()
    expect(view.get('[role="alert"]').text()).toContain('请使用 ERP 账号登录')
    expect(view.get('input[autocomplete="username"]').attributes('disabled')).toBeUndefined()
    expect(mocks.replace).not.toHaveBeenCalled()
  })
  it('手动授权遇到外站回跳地址时使用手机首页', async () => {
    mocks.query.redirect = '//example.invalid/steal'
    openPage()
    await retry()
    expect(mocks.start).toHaveBeenCalledWith('/')
  })
  it.each([
    [`/m${target}`, target], ['https://example.invalid/steal', '/'], ['/m/auth/wecom-error', '/'],
  ])('密码登录成功安全处理回跳 %s，并清除自动登录尝试标记', async (redirect, destination) => {
    mocks.query.redirect = redirect
    const view = openPage()
    await view.get('input[autocomplete="username"]').setValue(' worker-test ')
    await view.get('input[autocomplete="current-password"]').setValue('unit-test-password')
    view.getComponent(Form).vm.$emit('submit'); await flushPromises()
    expect(mocks.auth.login).toHaveBeenCalledWith('worker-test', 'unit-test-password')
    expect(mocks.clearAttempt).toHaveBeenCalledTimes(1)
    expect(mocks.replace).toHaveBeenCalledWith(destination)
    expect(mocks.start).not.toHaveBeenCalled()
  })
})
