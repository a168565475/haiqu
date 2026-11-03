import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { defineComponent, h, nextTick, onMounted } from 'vue'
import { isNavigationFailure, NavigationFailureType, onBeforeRouteLeave, useRoute } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '@/App.vue'
import { router } from './index'
import { useAuthStore } from '@/stores/auth'
import type { AuthResponse } from '@/types/auth'

const api = vi.hoisted(() => ({ me: vi.fn(), autoLogin: vi.fn() }))
vi.mock('@/api/auth', () => ({ fetchCurrentUser: api.me, login: vi.fn(), logout: vi.fn(),
  fetchSwitchTargets: vi.fn(), switchAccount: vi.fn(), returnAdmin: vi.fn() }))
vi.mock('./wecomGuard', async importOriginal => ({
  ...await importOriginal<typeof import('./wecomGuard')>(), startWeComLoginIfNeeded: api.autoLogin,
}))
vi.mock('@/api/wecomSession', () => ({ installWeComRoleGuard: () => () => undefined }))
vi.mock('@/composables/usePageTabsIdentitySync', () => ({ usePageTabsIdentitySync: () => undefined }))
vi.mock('@/composables/useReferenceCacheSync', () => ({ useReferenceCacheSync: () => undefined }))
vi.mock('@/views/workbench/WorkbenchLandingView.vue', () => ({ default: { template: '<main data-clean-home />' } }))
vi.mock('@/views/workbench/production/ProductionDashboardView.vue', () => ({ default: { template: '<main data-clean-home />' } }))
vi.mock('@/views/LoginView.vue', () => ({ default: { template: '<main data-clean-login />' } }))
vi.mock('@/views/auth/WaitingRoleView.vue', () => ({ default: { template: '<main data-clean-waiting />' } }))

function identity(id: number, version = `v${id}`): AuthResponse {
  return { authenticated: true, user: { id, username: id === 1 ? 'admin' : `employee${id}`,
    display_name: '当前身份', is_superuser: id === 1, employee: null, permissions: [], data_scope: 'ALL' },
  account_switch: { active: id !== 1, can_return: id !== 1, identity_version: version } }
}
function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>(r => { resolve = r })
  return { promise, resolve }
}

// Real App + production router + real Pinia. The API boundary and unrelated shell/services
// are unit doubles; these checks are not browser/real-account acceptance.
describe('普通认证刷新跨层身份边界', () => {
  let wrapper: VueWrapper | undefined
  let cleanups: Array<() => void>
  let mounts: Array<{ uid: number | undefined; id: unknown }>
  let leaveAllowed: boolean
  let leaveWait: Promise<boolean> | undefined
  let leaveUids: Array<number | undefined>
  const oldUrl = '/identity-boundary-test/old-object/edit?source=previous-owner#old-anchor'

  beforeEach(async () => {
    vi.resetAllMocks()
    api.autoLogin.mockReturnValue(false)
    setActivePinia(createPinia())
    cleanups = []
    mounts = []
    leaveUids = []
    leaveAllowed = true
    leaveWait = undefined
    const Editor = defineComponent({ setup() {
      const auth = useAuthStore()
      const route = useRoute()
      onMounted(() => mounts.push({ uid: auth.user?.id, id: route.params.id }))
      onBeforeRouteLeave(() => { leaveUids.push(auth.user?.id); return leaveWait ?? leaveAllowed })
      return () => h('input', { 'data-old-editor': '', value: '原身份未保存草稿' })
    } })
    cleanups.push(router.addRoute({ path: '/identity-boundary-test/:id/edit', name: 'identity-boundary-editor',
      component: Editor, meta: { requiresAuth: true, layout: 'erp' } }))
    cleanups.push(router.addRoute({ path: '/identity-boundary-test/:id/detail', name: 'identity-boundary-detail',
      component: Editor, meta: { requiresAuth: true, layout: 'erp' } }))
    await router.replace({ name: 'account-switch-transition' })
  })
  afterEach(async () => {
    wrapper?.unmount()
    wrapper = undefined
    cleanups.reverse().forEach(remove => remove())
    await router.replace({ name: 'account-switch-transition' })
  })
  function render() {
    wrapper = mount(App, { global: { plugins: [router], stubs: {
      AccountSwitchControls: true, AppHeader: true, AppSidebar: true,
      ErpLayout: { template: '<div><slot name="header" /><slot /></div>' },
      PageContainer: { template: '<section><slot /></section>' },
    } } })
    return wrapper
  }
  // A trusted external identity read also changes the simulated server fixture.
  // Never inherit a preceding test's anonymous /me implementation during safe recovery.
  function applyIdentity(response: AuthResponse, forceIdentityBoundary = false) {
    api.me.mockResolvedValue(response)
    useAuthStore().applyAuthResponse(response, forceIdentityBoundary)
  }
  async function oldEditor() {
    applyIdentity(identity(1))
    await router.replace(oldUrl)
    render()
    await flushPromises()
    expect(mounts).toEqual([{ uid: 1, id: 'old-object' }])
  }
  function refreshTo(response: AuthResponse) {
    api.me.mockResolvedValue(response)
    useAuthStore().invalidateAuthenticationVerification()
  }
  function target() {
    return { name: 'identity-boundary-detail', params: { id: 'old-object' }, query: { owner: 'old' }, hash: '#old' }
  }

  it('新身份应用到提交安全落点之间不重新挂载旧对象，也不承接旧目标参数', async () => {
    await oldEditor()
    const landing = deferred<boolean>()
    cleanups.push(router.beforeResolve(to => to.name === 'home' ? landing.promise : true))
    refreshTo(identity(2))
    const navigation = router.push(target())
    await flushPromises()
    expect(router.currentRoute.value.fullPath).toBe(oldUrl)
    expect(wrapper!.find('[data-old-editor]').exists()).toBe(false)
    expect(wrapper!.text()).toContain('此页不载入业务单据')
    expect(mounts).toEqual([{ uid: 1, id: 'old-object' }])
    expect(leaveUids).toEqual([1])
    landing.resolve(true)
    await navigation
    await flushPromises()
    expect(router.currentRoute.value).toMatchObject({ name: 'home', params: {}, query: {}, hash: '' })
    expect(wrapper!.find('[data-clean-home]').exists()).toBe(true)
    expect(mounts).toHaveLength(1)
  })

  it.each([true, false])('旧身份异步离开确认期间换身份，确认=%s也不把旧目标交给新UID', async allowed => {
    await oldEditor()
    const confirmation = deferred<boolean>()
    leaveWait = confirmation.promise
    const navigation = router.push(target())
    await flushPromises()
    applyIdentity(identity(2))
    await nextTick()
    expect(wrapper!.find('[data-old-editor]').exists()).toBe(false)
    confirmation.resolve(allowed)
    const failure = await navigation
    await flushPromises()
    expect(mounts).toEqual([{ uid: 1, id: 'old-object' }])
    if (allowed) {
      expect(router.currentRoute.value).toMatchObject({ name: 'home', params: {}, query: {}, hash: '' })
    } else {
      expect(isNavigationFailure(failure, NavigationFailureType.aborted)).toBe(true)
      expect(router.currentRoute.value.fullPath).toBe(oldUrl)
    }
  })

  it('异步离开期间no-op认证读取不取消原身份的正常导航', async () => {
    await oldEditor()
    const confirmation = deferred<boolean>()
    leaveWait = confirmation.promise
    const navigation = router.push(target())
    await flushPromises()
    applyIdentity(identity(1))
    confirmation.resolve(true)
    await navigation
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('identity-boundary-detail')
    expect(mounts.every(item => item.uid === 1)).toBe(true)
  })

  it('普通匿名显式登录后的初始目标仍可正常到达', async () => {
    api.me.mockResolvedValue({ authenticated: false, user: null })
    await router.push({ name: 'login', query: { redirect: oldUrl } })
    render()
    applyIdentity(identity(2), true)
    await router.push(oldUrl)
    await flushPromises()
    expect(router.currentRoute.value.fullPath).toBe(oldUrl)
    expect(mounts).toEqual([{ uid: 2, id: 'old-object' }])
  })

  it('认证已完成但异步导航未提交时换身份，迟到旧目标也不能取得新身份授权', async () => {
    await oldEditor()
    const pending = deferred<boolean>()
    cleanups.push(router.beforeResolve(to => to.name === 'identity-boundary-detail' ? pending.promise : true))
    const navigation = router.push(target())
    await flushPromises()
    applyIdentity(identity(2))
    await nextTick()
    expect(wrapper!.find('[data-old-editor]').exists()).toBe(false)
    pending.resolve(true)
    await navigation
    await flushPromises()
    expect(mounts).toEqual([{ uid: 1, id: 'old-object' }])
    expect(router.currentRoute.value).toMatchObject({ name: 'home', params: {}, query: {}, hash: '' })
  })

  it('新身份后的安全导航被拒绝时保持封闭，不恢复旧页面', async () => {
    await oldEditor()
    cleanups.push(router.beforeResolve(to => to.name !== 'home'))
    refreshTo(identity(2))
    expect(isNavigationFailure(await router.push(target()), NavigationFailureType.aborted)).toBe(true)
    await flushPromises()
    expect(router.currentRoute.value.fullPath).toBe(oldUrl)
    expect(wrapper!.find('[data-old-editor]').exists()).toBe(false)
    expect(mounts).toHaveLength(1)
  })

  it('同身份/me且后续导航取消保留原表单实例和内容', async () => {
    await oldEditor()
    await wrapper!.get('input').setValue('继续填写的原草稿')
    cleanups.push(router.beforeResolve(() => false))
    refreshTo(identity(1))
    await router.push(target())
    await flushPromises()
    expect((wrapper!.get('input').element as HTMLInputElement).value).toBe('继续填写的原草稿')
    expect(mounts).toHaveLength(1)
  })

  it('正常离开拒绝在/me前执行，不在旧身份上越过确认', async () => {
    await oldEditor()
    leaveAllowed = false
    refreshTo(identity(2))
    expect(isNavigationFailure(await router.push(target()), NavigationFailureType.aborted)).toBe(true)
    expect(api.me).not.toHaveBeenCalled()
    expect(useAuthStore().user?.id).toBe(1)
    expect(wrapper!.find('[data-old-editor]').exists()).toBe(true)
  })

  it('初次已授权深链接仍可载入，不把首次初始化误当身份切换', async () => {
    api.me.mockResolvedValue(identity(2))
    render()
    await router.push(oldUrl)
    await flushPromises()
    expect(router.currentRoute.value.fullPath).toBe(oldUrl)
    expect(mounts).toEqual([{ uid: 2, id: 'old-object' }])
  })

  it.each(['version', 'permissions'] as const)('同UID的%s边界同样只落干净首页', async change => {
    await oldEditor()
    const response = identity(1, change === 'version' ? 'new-version' : 'v1')
    if (change === 'permissions') response.user!.permissions = ['new.permission']
    refreshTo(response)
    await router.push(target())
    await flushPromises()
    // Keep the existing administrator home -> workshop-workbench policy.
    expect(router.currentRoute.value).toMatchObject({ name: 'workshop-workbench', params: {}, query: {}, hash: '' })
    expect(mounts).toHaveLength(1)
  })

  it('新身份待授权时落干净等待页', async () => {
    await oldEditor()
    const response = identity(2)
    response.user!.waiting_for_role = true
    refreshTo(response)
    await router.push(target())
    expect(router.currentRoute.value).toMatchObject({ name: 'waiting-role', params: {}, query: {}, hash: '' })
    expect(mounts).toHaveLength(1)
  })

  it('清洁首页重复导航能恢复渲染，旧对象重复导航不能重新授权', async () => {
    await oldEditor()
    applyIdentity(identity(2))
    await nextTick()
    expect(isNavigationFailure(await router.push(oldUrl), NavigationFailureType.duplicated)).toBe(true)
    await nextTick()
    expect(wrapper!.find('[data-old-editor]').exists()).toBe(false)
    expect(mounts).toHaveLength(1)
    await router.push({ name: 'home' })
    applyIdentity(identity(3))
    await nextTick()
    expect(wrapper!.find('[data-clean-home]').exists()).toBe(false)
    expect(isNavigationFailure(await router.push({ name: 'home' }), NavigationFailureType.duplicated)).toBe(true)
    await nextTick()
    expect(wrapper!.find('[data-clean-home]').exists()).toBe(true)
  })

  it('携带旧query/hash的首页重复导航也不能重新授权', async () => {
    applyIdentity(identity(2))
    await router.push({ name: 'home', query: { oldObject: 'private' }, hash: '#old' })
    render()
    applyIdentity(identity(3))
    await nextTick()
    expect(isNavigationFailure(await router.push({ name: 'home', query: { oldObject: 'private' }, hash: '#old' }),
      NavigationFailureType.duplicated)).toBe(true)
    await nextTick()
    expect(wrapper!.find('[data-clean-home]').exists()).toBe(false)
    await router.push({ name: 'home', query: {}, hash: '' })
    await nextTick()
    expect(wrapper!.find('[data-clean-home]').exists()).toBe(true)
  })

  it('从首页刷新身份后取消旧对象意图，即使清洁首页重定向被视为重复', async () => {
    applyIdentity(identity(2))
    await router.push({ name: 'home' })
    render()
    refreshTo(identity(3))
    await router.push(target())
    await flushPromises()
    expect(router.currentRoute.value).toMatchObject({ name: 'home', params: {}, query: {}, hash: '' })
    expect(wrapper!.find('[data-clean-home]').exists()).toBe(true)
    expect(mounts).toEqual([])
  })

  it('匿名但保有原管理员能力时优先进入干净登录页，不调用自动OAuth', async () => {
    api.me.mockResolvedValue({ authenticated: false, user: null,
      account_switch: { active: true, can_return: true, identity_version: 'return-proof' } })
    await router.push(oldUrl)
    expect(router.currentRoute.value).toMatchObject({ name: 'login', params: {}, query: {}, hash: '' })
    expect(useAuthStore().canReturnAdmin).toBe(true)
    // Only the public login route reaches the existing helper; the protected old
    // URL must never reach its automatic OAuth branch.
    expect(api.autoLogin).toHaveBeenCalledExactlyOnceWith('login', false, false, '/login')
  })

  it('普通匿名仍交给原自动OAuth入口，未自动返回管理员', async () => {
    api.me.mockResolvedValue({ authenticated: false, user: null })
    api.autoLogin.mockReturnValue(true)
    await router.push(oldUrl)
    expect(api.autoLogin).toHaveBeenCalledExactlyOnceWith('identity-boundary-editor', true, false, oldUrl)
    expect(router.currentRoute.value.name).toBe('account-switch-transition')
    expect(useAuthStore().canReturnAdmin).toBe(false)
  })
})
