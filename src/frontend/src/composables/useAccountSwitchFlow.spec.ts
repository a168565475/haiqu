import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { AxiosError, AxiosHeaders } from 'axios'
import { ElMessageBox } from 'element-plus'
import { createPinia, setActivePinia } from 'pinia'
import { defineComponent, h, onUnmounted } from 'vue'
import { createMemoryHistory, createRouter, onBeforeRouteLeave, RouterView, type NavigationGuardReturn } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useAuthStore } from '@/stores/auth'
import type { AuthResponse } from '@/types/auth'
import { createAccountSwitchFlow } from './useAccountSwitchFlow'

const api = vi.hoisted(() => ({ me: vi.fn(), switch: vi.fn(), back: vi.fn() }))
vi.mock('@/api/auth', () => ({ fetchCurrentUser: api.me, switchAccount: api.switch, returnAdmin: api.back,
  fetchSwitchTargets: vi.fn(), login: vi.fn(), logout: vi.fn() }))
const employeeId = 'bb00d4cc-505d-42cd-98a7-8e770fc21545'
function identity(id = 1, version = 'private-v1', waiting = false): AuthResponse {
  return { authenticated: true, user: { id, username: id === 1 ? 'admin' : 'worker', display_name: id === 1 ? '管理员' : '员工',
    is_superuser: id === 1, employee: id === 1 ? null : { id: employeeId, employee_code: 'E002', display_name: '员工', status: 'ACTIVE' },
    permissions: [], data_scope: 'ALL', waiting_for_role: waiting },
  account_switch: { active: id !== 1, can_return: id !== 1, identity_version: version } }
}
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(r => { resolve = r }); return { promise, resolve } }
const mounted: VueWrapper[] = []
beforeEach(() => { vi.resetAllMocks(); api.switch.mockResolvedValue(identity(2, 'private-v2')); api.back.mockResolvedValue(identity(1, 'private-v3')) })
afterEach(() => { mounted.splice(0).forEach(wrapper => wrapper.unmount()); vi.restoreAllMocks() })
async function setup(initial = identity()) {
  const pinia = createPinia(); setActivePinia(pinia)
  const auth = useAuthStore(); auth.applyAuthResponse(initial)
  const events: string[] = []
  const leave: { action: () => NavigationGuardReturn | Promise<NavigationGuardReturn> } = { action: () => true }
  const Form = defineComponent({ setup() {
    onBeforeRouteLeave(() => { events.push(`leave:${auth.user?.username}`); return leave.action() })
    onUnmounted(() => { events.push(`unmount:${auth.user?.username}`) })
    return () => h('input', { 'data-test': 'old-form', value: '尚未保存' })
  } })
  const Page = defineComponent({ render: () => h('main') })
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/objects/:id', name: 'object', component: Form },
    { path: '/auth/account-switch-transition', name: 'account-switch-transition', component: Page },
    { path: '/', name: 'home', component: Page },
    { path: '/production', name: 'production-overview', component: Page },
    { path: '/workshop', name: 'workshop-workbench', component: Page },
    { path: '/waiting', name: 'waiting-role', component: Page },
    { path: '/login', name: 'login', component: Page },
    { path: '/other', name: 'other', component: Page },
  ] })
  await router.push('/objects/old?restore=old#form'); await router.isReady()
  const wrapper = mount(defineComponent({ render: () => h(RouterView) }), { global: { plugins: [pinia, router] } })
  mounted.push(wrapper)
  const confirm = vi.fn().mockResolvedValue(true)
  const flow = createAccountSwitchFlow(auth, router, confirm)
  return { auth, router, wrapper, confirm, flow, leave, events }
}

describe('身份转换交互编排（内存路由与API替身，不是真实切换验收）', () => {
  it('确认→旧身份leave/unmount→纯安全页→唯一POST→新身份无旧参数落点', async () => {
    const { auth, router, wrapper, flow, events, confirm } = await setup()
    api.switch.mockImplementation(async () => {
      expect(confirm).toHaveBeenCalledWith('switch')
      expect(router.currentRoute.value.name).toBe('account-switch-transition')
      expect(auth.user?.username).toBe('admin')
      expect(events).toEqual(['leave:admin', 'unmount:admin'])
      expect(wrapper.find('[data-test="old-form"]').exists()).toBe(false)
      return identity(2, 'private-v2')
    })
    expect(await flow.switchAccount(employeeId)).toBe(true)
    expect(api.switch).toHaveBeenCalledExactlyOnceWith(employeeId)
    expect(router.currentRoute.value.fullPath).toBe('/')
    expect(auth.user?.username).toBe('worker'); expect(flow.busy.value).toBe(false)
  })
  it('全局确认取消时不离页、不发身份写、不删除旧表单', async () => {
    const { router, wrapper, flow, confirm, events } = await setup()
    confirm.mockResolvedValue(false)
    expect(await flow.switchAccount(employeeId)).toBe(false)
    expect(events).toEqual([]); expect(wrapper.get('input').element.value).toBe('尚未保存')
    expect(router.currentRoute.value.fullPath).toBe('/objects/old?restore=old#form')
    expect(api.switch).not.toHaveBeenCalled()
  })
  it.each([false, '/other'] as const)('正常leave守卫返回%j则不写；后续导航绝不恢复已取消意图', async decision => {
    const { router, flow, leave } = await setup()
    let redirected = false
    leave.action = () => {
      if (decision === false) return false
      if (redirected) return true
      redirected = true
      return decision
    }
    expect(await flow.switchAccount(employeeId)).toBe(false)
    expect(api.switch).not.toHaveBeenCalled(); expect(flow.error.value).toContain('本次身份操作已取消')
    leave.action = () => true
    await router.push({ name: 'account-switch-transition' }); await flushPromises()
    expect(api.switch).not.toHaveBeenCalled()
  })
  it('异步leave取消期间保留表单且全程互斥，不排队执行第二次动作', async () => {
    const { flow, leave, wrapper } = await setup()
    const gate = deferred<NavigationGuardReturn>(); leave.action = () => gate.promise
    const first = flow.switchAccount(employeeId); await flushPromises()
    expect(flow.phase.value).toBe('leaving'); expect(wrapper.find('input').exists()).toBe(true)
    expect(await flow.switchAccount(employeeId)).toBe(false)
    expect(await flow.returnAdmin()).toBe(false)
    gate.resolve(false); expect(await first).toBe(false)
    expect(api.switch).not.toHaveBeenCalled(); expect(api.back).not.toHaveBeenCalled()
  })
  it('确认期间身份变化则取消，普通同上下文/me不被误认为身份变化', async () => {
    const { auth, flow, confirm } = await setup()
    const gate = deferred<boolean>(); confirm.mockReturnValue(gate.promise)
    const first = flow.switchAccount(employeeId)
    auth.applyAuthResponse(identity(1, 'changed-version'))
    gate.resolve(true); expect(await first).toBe(false); expect(api.switch).not.toHaveBeenCalled()
    const same = identity(1, 'changed-version'); same.user!.display_name = '姓名更新'
    confirm.mockImplementation(async () => { auth.applyAuthResponse(same); return true })
    expect(await flow.switchAccount(employeeId)).toBe(true); expect(api.switch).toHaveBeenCalledTimes(1)
  })
  it('确认期间跳到其他页面则取消，不把新页面未保存内容静默丢弃', async () => {
    const { flow, router, confirm } = await setup()
    const gate = deferred<boolean>(); confirm.mockReturnValue(gate.promise)
    const first = flow.switchAccount(employeeId)
    await router.push('/other'); gate.resolve(true)
    expect(await first).toBe(false); expect(router.currentRoute.value.name).toBe('other')
    expect(api.switch).not.toHaveBeenCalled()
  })
  it('离开期间身份版本变化则即使已到安全页也不发POST', async () => {
    const { auth, flow, leave } = await setup()
    const gate = deferred<NavigationGuardReturn>(); leave.action = () => gate.promise
    const first = flow.switchAccount(employeeId); await flushPromises()
    auth.applyAuthResponse(identity(1, 'changed-while-leaving'))
    gate.resolve(true); expect(await first).toBe(false); expect(api.switch).not.toHaveBeenCalled()
  })
  it('已在无query/hash安全页时允许duplicate导航，不误报中止', async () => {
    const { flow, router } = await setup()
    await router.push({ name: 'account-switch-transition', query: { old: 'discard' }, hash: '#old' })
    expect(await flow.switchAccount(employeeId)).toBe(true)
    expect(api.switch).toHaveBeenCalledTimes(1)
    await router.push({ name: 'account-switch-transition' })
    expect(await flow.returnAdmin()).toBe(true)
    expect(api.back).toHaveBeenCalledTimes(1); expect(router.currentRoute.value.fullPath).toBe('/')
  })
  it.each([403, 404])('返回被确定性%j拒绝保留已知身份，只在明确操作后核验', async status => {
    const { auth, router, flow } = await setup(identity(2, 'private-v2'))
    api.back.mockRejectedValue(new AxiosError('refused', undefined, undefined, undefined, {
      status, data: {}, headers: {}, statusText: 'Refused', config: { headers: new AxiosHeaders() },
    }))
    expect(await flow.returnAdmin()).toBe(false)
    expect(auth.identityReady).toBe(true); expect(auth.canReturnAdmin).toBe(true)
    expect(router.currentRoute.value.name).toBe('account-switch-transition')
    expect(flow.error.value).toContain('重新核验身份'); expect(api.me).not.toHaveBeenCalled()
    api.me.mockResolvedValue(identity(1, 'verified-admin'))
    expect(await flow.verifyIdentity()).toBe(true)
    expect(api.back).toHaveBeenCalledTimes(1); expect(api.me).toHaveBeenCalledTimes(1)
    expect(auth.user?.username).toBe('admin'); expect(router.currentRoute.value.name).toBe('home')
  })
  it('切换未知结果只保留安全页与核验入口，不自动/me、返回或重发', async () => {
    const { auth, flow, router } = await setup()
    api.switch.mockRejectedValue(new AxiosError('timeout', 'ECONNABORTED'))
    expect(await flow.switchAccount(employeeId)).toBe(false)
    expect(auth.identityReady).toBe(false); expect(auth.user?.username).toBe('admin')
    expect(router.currentRoute.value.name).toBe('account-switch-transition')
    expect(flow.error.value).toContain('不会自动重试')
    expect(api.me).not.toHaveBeenCalled(); expect(api.back).not.toHaveBeenCalled(); expect(api.switch).toHaveBeenCalledTimes(1)
  })
  it('核验先正常离页再/me，核验后进入待授权页且没有旧redirect', async () => {
    const { auth, router, flow, events } = await setup()
    auth.requireIdentityRevalidation()
    api.me.mockImplementation(async () => {
      expect(router.currentRoute.value.name).toBe('account-switch-transition')
      expect(events).toEqual(['leave:admin', 'unmount:admin'])
      return identity(2, 'private-v2', true)
    })
    expect(await flow.verifyIdentity()).toBe(true)
    expect(router.currentRoute.value.fullPath).toBe('/waiting')
    expect(api.me).toHaveBeenCalledTimes(1); expect(api.switch).not.toHaveBeenCalled()
  })
  it('核验返回匿名时落登录页，不保留旧业务URL或自动返回管理员', async () => {
    const { auth, router, flow } = await setup()
    auth.requireIdentityRevalidation()
    api.me.mockResolvedValue({ authenticated: false, user: null, account_switch: { active: false, can_return: true, identity_version: 'anonymous-version' } })
    expect(await flow.verifyIdentity()).toBe(true)
    expect(router.currentRoute.value.fullPath).toBe('/login'); expect(api.back).not.toHaveBeenCalled()
    api.back.mockResolvedValue(identity(1, 'returned-version'))
    expect(await flow.returnAdmin()).toBe(true); expect(api.back).toHaveBeenCalledTimes(1)
  })
  it('同员工重复切换仍发唯一POST并形成新代次', async () => {
    const { auth, flow } = await setup(identity(2, 'private-v1'))
    const before = auth.identityGeneration
    expect(await flow.switchAccount(employeeId)).toBe(true)
    expect(auth.identityGeneration).toBeGreaterThan(before); expect(api.switch).toHaveBeenCalledTimes(1)
  })
  it('目标用户没有业务角色时安全落待授权；首页既有非对象分流可正常完成', async () => {
    const { router, flow } = await setup()
    api.switch.mockResolvedValueOnce(identity(2, 'private-v2', true))
    expect(await flow.switchAccount(employeeId)).toBe(true); expect(router.currentRoute.value.fullPath).toBe('/waiting')
    router.beforeEach(to => to.name === 'home' ? { name: 'production-overview' } : true)
    expect(await flow.returnAdmin()).toBe(true); expect(router.currentRoute.value.fullPath).toBe('/production')
  })
  it('新身份成功但落点被拒绝时不再写，明确区分落点失败', async () => {
    const { auth, router, flow } = await setup()
    router.beforeEach(to => to.name === 'home' ? false : true)
    expect(await flow.switchAccount(employeeId)).toBe(false)
    expect(auth.user?.username).toBe('worker'); expect(auth.identityReady).toBe(true)
    expect(router.currentRoute.value.name).toBe('account-switch-transition')
    expect(flow.error.value).toContain('不要重提'); expect(api.switch).toHaveBeenCalledTimes(1)
  })
  it('返回结果与指定目标身份不符时阻断业务并要求核验，不展示成功', async () => {
    const { auth, flow } = await setup()
    api.switch.mockResolvedValue(identity(1, 'unexpected-version'))
    expect(await flow.switchAccount(employeeId)).toBe(false)
    expect(auth.identityReady).toBe(false); expect(flow.error.value).toContain('未能确认目标身份')
  })
  it.each(['cancel', 'close'])('默认全局确认明确解释草稿边界，%s后不离页不写', async reason => {
    const { auth, router, wrapper } = await setup()
    const dialog = vi.spyOn(ElMessageBox, 'confirm').mockRejectedValue(reason)
    const flow = createAccountSwitchFlow(auth, router)
    expect(await flow.switchAccount(employeeId)).toBe(false)
    expect(dialog.mock.calls[0]?.[0]).toContain('尚未保存到服务端的内容不会随身份移交')
    expect(dialog.mock.calls[0]?.[0]).toContain('历史待核对请求不会自动重提')
    expect(wrapper.get('input').element.value).toBe('尚未保存')
    expect(api.switch).not.toHaveBeenCalled(); expect(flow.error.value).toBe('')
  })
  it('核验读被其他认证结果取代时不采信旧结果、不进入业务页', async () => {
    const { auth, router, flow } = await setup()
    auth.requireIdentityRevalidation()
    api.me.mockImplementation(async () => {
      auth.applyAuthResponse(identity(1, 'newer-context'))
      return identity(2, 'stale-read')
    })
    expect(await flow.verifyIdentity()).toBe(false)
    expect(auth.user?.username).toBe('admin')
    expect(router.currentRoute.value.name).toBe('account-switch-transition')
    expect(flow.error.value).toContain('核验结果已失效')
    expect(api.switch).not.toHaveBeenCalled(); expect(api.back).not.toHaveBeenCalled()
  })
  it('销毁全局控制器后不会将未完成确认继续成身份写', async () => {
    const { flow, confirm } = await setup()
    const gate = deferred<boolean>(); confirm.mockReturnValue(gate.promise)
    const first = flow.switchAccount(employeeId); flow.dispose(); gate.resolve(true)
    expect(await first).toBe(false); expect(api.switch).not.toHaveBeenCalled()
  })
})
