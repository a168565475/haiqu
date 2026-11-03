import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import type { VueWrapper } from '@vue/test-utils'
import { Button, Icon } from 'vant'
import WeComError from './wecom-error.vue'
import WaitingRole from './waiting-role.vue'

const mocks = vi.hoisted(() => ({
  query: {} as Record<string, unknown>, replace: vi.fn(), start: vi.fn(), inWeCom: true,
  auth: {
    user: null as { display_name: string; username: string; waiting_for_role: boolean; employee: null } | null,
    accountSwitch: null as { active: boolean; can_return: boolean; identity_version: string } | null,
    refresh: vi.fn(), logout: vi.fn(),
  },
}))
vi.mock('vue-router', () => ({ useRoute: () => ({ query: mocks.query }), useRouter: () => ({ replace: mocks.replace }) }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => mocks.auth }))
vi.mock('@/utils/wecom', async importOriginal => ({
  ...await importOriginal<typeof import('@/utils/wecom')>(),
  isWeComBrowser: () => mocks.inWeCom, startWeComLogin: mocks.start,
}))
const next = '/m/plan?schedule_product_id=plan-one&workshop_id=workshop-one'
const target = '/plan?schedule_product_id=plan-one&workshop_id=workshop-one'
const user = () => ({ display_name: '测试员工', username: 'worker-test', waiting_for_role: true, employee: null })
let wrapper: VueWrapper | undefined
function openPage(page: typeof WeComError | typeof WaitingRole) {
  wrapper = mount(page, { global: { components: { VanButton: Button, VanIcon: Icon } } })
  return wrapper
}
async function click(action: string) {
  await wrapper!.get(`[data-action="${action}"]`).trigger('click')
  await flushPromises()
}
beforeEach(() => {
  vi.resetAllMocks()
  mocks.query = { next }
  mocks.inWeCom = true
  mocks.auth.user = null
  mocks.auth.accountSwitch = null
  mocks.auth.refresh.mockResolvedValue(undefined)
  mocks.auth.logout.mockResolvedValue(undefined)
  mocks.start.mockReturnValue(true)
})
afterEach(() => { wrapper?.unmount(); wrapper = undefined })

describe('手机企业微信登录错误页', () => {
  it('使用固定原因文案，进入页面不自动授权或退出当前账号', () => {
    mocks.query.reason = 'IDENTITY_MISMATCH'
    const view = openPage(WeComError)
    expect(view.get('[role="alert"]').text()).toContain('原会话未切换')
    expect(mocks.auth.refresh).not.toHaveBeenCalled()
    expect(mocks.auth.logout).not.toHaveBeenCalled()
    expect(mocks.start).not.toHaveBeenCalled()
  })
  it.each(['<script>未知原因</script>', ['STATE_INVALID', 'LOGIN_FAILED']])('未知或重复 reason 使用通用提示，不显示传入内容：%s', reason => {
    mocks.query.reason = reason
    const view = openPage(WeComError)
    expect(view.get('[role="alert"]').text()).toContain('企业微信登录未完成')
    expect(view.text()).not.toContain('未知原因')
    expect(view.text()).not.toContain('STATE_INVALID')
  })
  it('明确重试先确认会话，再把安全手机内部地址交给授权入口', async () => {
    openPage(WeComError)
    await click('retry')
    expect(mocks.auth.refresh).toHaveBeenCalledWith(true)
    expect(mocks.start).toHaveBeenCalledExactlyOnceWith(target)
    expect(mocks.replace).not.toHaveBeenCalled()
  })
  it('重新查询后已有账号，返回当前账号而不重新授权', async () => {
    mocks.auth.refresh.mockImplementationOnce(async () => {
      mocks.auth.user = { ...user(), waiting_for_role: false }
      mocks.auth.accountSwitch = { active: true, can_return: true, identity_version: 'v2' }
    })
    openPage(WeComError)
    await click('retry')
    expect(mocks.replace).toHaveBeenCalledWith(target)
    expect(mocks.start).not.toHaveBeenCalled()
    expect(mocks.auth.logout).not.toHaveBeenCalled()
  })
  it('重新查询后匿名但有管理员返回凭据时保留会话，只提供 ERP 返回入口', async () => {
    mocks.auth.refresh.mockImplementationOnce(async () => {
      mocks.auth.accountSwitch = { active: true, can_return: true, identity_version: 'v2' }
    })
    const view = openPage(WeComError)
    await click('retry')
    expect(mocks.start).not.toHaveBeenCalled()
    expect(mocks.replace).not.toHaveBeenCalled()
    expect(mocks.auth.logout).not.toHaveBeenCalled()
    expect(view.get('a').attributes('href')).toBe('/')
    expect(view.find('[data-action="password-login"]').exists()).toBe(false)
    expect(view.text()).toContain('返回管理员账号')
  })
  it('会话查询失败不继续授权，入口无法发起时也不显示成功', async () => {
    mocks.auth.refresh.mockRejectedValueOnce(new Error('会话检查超时'))
    const view = openPage(WeComError)
    await click('retry')
    expect(view.text()).toContain('会话检查超时')
    expect(mocks.start).not.toHaveBeenCalled()
    mocks.start.mockReturnValue(false)
    await click('retry')
    expect(view.text()).toContain('暂时无法发起企业微信登录')
    expect(mocks.replace).not.toHaveBeenCalled()
  })
  it('ERP 账号入口保留安全回跳，外站地址被归到手机首页', async () => {
    mocks.query.next = 'https://example.invalid/steal'
    openPage(WeComError)
    await click('password-login')
    expect(mocks.replace).toHaveBeenCalledWith({ path: '/login', query: { redirect: '/' } })
    expect(mocks.start).not.toHaveBeenCalled()
    expect(mocks.auth.logout).not.toHaveBeenCalled()
  })
  it('普通浏览器只显示 ERP 账号主入口，不提供企微内授权重试', async () => {
    mocks.inWeCom = false
    const view = openPage(WeComError)
    expect(view.find('[data-action="retry"]').exists()).toBe(false)
    expect(view.get('[data-action="password-login"]').classes()).not.toContain('van-button--plain')
    await click('password-login')
    expect(mocks.replace).toHaveBeenCalledWith({ path: '/login', query: { redirect: target } })
    expect(mocks.start).not.toHaveBeenCalled()
  })
})

describe('手机等待授权页', () => {
  beforeEach(() => { mocks.auth.user = user() })
  it('仍待授权时留在当前页，获得权限后回原生产页面', async () => {
    const view = openPage(WaitingRole)
    expect(view.text()).toContain('测试员工')
    expect(view.text()).not.toContain('已关联企业微信')
    await click('refresh-role')
    expect(mocks.auth.refresh).toHaveBeenCalledWith(true)
    expect(view.get('[role="status"]').text()).toContain('尚未分配有效访问权限')
    expect(mocks.replace).not.toHaveBeenCalled()
    mocks.auth.refresh.mockImplementationOnce(async () => { mocks.auth.user = { ...user(), waiting_for_role: false } })
    await click('refresh-role')
    expect(mocks.replace).toHaveBeenCalledWith(target)
  })
  it('检查期间禁用重复操作，查询失败显示真实错误而不进入业务页', async () => {
    let reject!: (error: Error) => void
    mocks.auth.refresh.mockImplementationOnce(() => new Promise((_resolve, rejectPromise) => { reject = rejectPromise }))
    const view = openPage(WaitingRole)
    await click('refresh-role')
    expect(view.get('[data-action="refresh-role"]').attributes('disabled')).toBeDefined()
    expect(view.get('[data-action="logout"]').attributes('disabled')).toBeDefined()
    await click('refresh-role')
    expect(mocks.auth.refresh).toHaveBeenCalledTimes(1)
    reject(new Error('授权查询连接失败')); await flushPromises()
    expect(view.get('[role="alert"]').text()).toContain('授权查询连接失败')
    expect(mocks.replace).not.toHaveBeenCalled()
    expect(view.find('[role="status"]').exists()).toBe(false)
  })
  it('查询后登录失效，回账号登录并保留原安全业务地址', async () => {
    mocks.auth.refresh.mockImplementationOnce(async () => { mocks.auth.user = null })
    openPage(WaitingRole)
    await click('refresh-role')
    expect(mocks.replace).toHaveBeenCalledWith({ path: '/login', query: { redirect: target } })
  })
  it('退出失败停留并显示错误，退出成功才转登录且保留回跳', async () => {
    mocks.auth.logout.mockRejectedValueOnce(new Error('退出请求失败'))
    const view = openPage(WaitingRole)
    await click('logout')
    expect(view.get('[role="alert"]').text()).toContain('退出请求失败')
    expect(mocks.replace).not.toHaveBeenCalled()
    await click('logout')
    expect(mocks.auth.logout).toHaveBeenCalledTimes(2)
    expect(mocks.replace).toHaveBeenCalledWith({ path: '/login', query: { redirect: target } })
  })
  it('保留管理员返回凭据时隐藏退出，提供 ERP 入口', () => {
    mocks.auth.accountSwitch = { active: true, can_return: true, identity_version: 'v2' }
    const view = openPage(WaitingRole)
    expect(view.find('[data-action="logout"]').exists()).toBe(false)
    expect(view.get('a').attributes('href')).toBe('/')
    expect(view.text()).toContain('当前仍可返回管理员账号')
    expect(mocks.auth.logout).not.toHaveBeenCalled()
  })
})
