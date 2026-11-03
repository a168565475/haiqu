import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { markRaw, nextTick, reactive, ref } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import App from '@/App.vue'
import { useAuthStore } from '@/stores/auth'

const useFlow = vi.hoisted(() => vi.fn())
vi.mock('@/composables/useAccountSwitchFlow', () => ({ useAccountSwitchFlow: useFlow }))
vi.mock('@/api/wecomSession', () => ({ installWeComRoleGuard: () => () => undefined }))
vi.mock('@/composables/usePageTabsIdentitySync', () => ({ usePageTabsIdentitySync: () => undefined }))
vi.mock('@/composables/useReferenceCacheSync', () => ({ useReferenceCacheSync: () => undefined }))
vi.mock('vue-router', async importOriginal => ({
  ...await importOriginal<typeof import('vue-router')>(),
  useRoute: () => route, useRouter: () => ({ currentRoute: { value: route }, afterEach: () => () => undefined }),
}))
const route = reactive({ name: 'home', path: '/', fullPath: '/', params: {}, meta: { layout: 'erp' } })
const page = markRaw({ template: '<article data-route-page>当前路由页面</article>' })

beforeEach(() => {
  useFlow.mockReset().mockReturnValue({ busy: ref(false), phase: ref('idle'), error: ref(''),
    switchAccount: vi.fn().mockResolvedValue(false), returnAdmin: vi.fn().mockResolvedValue(false), verifyIdentity: vi.fn().mockResolvedValue(false) })
  route.name = 'home'
  route.meta.layout = 'erp'
  setActivePinia(createPinia())
  useAuthStore().applyAuthResponse({ authenticated: true, user: {
    id: 1, username: 'admin', display_name: '当前管理员', is_superuser: true, employee: null, permissions: [], data_scope: 'ALL',
  }, account_switch: { active: false, can_return: false, identity_version: 'v1' } })
  vi.spyOn(useAuthStore(), 'loadSwitchTargets').mockResolvedValue({ results: [], identity_version: 'v1' })
})

function render() {
  return mount(App, { global: { stubs: {
    RouterView: { setup: () => ({ route, page }), template: '<slot :Component="page" :route="route" />' },
    AppHeader: { name: 'AppHeader', props: ['switchBusy'], emits: ['switch-account', 'return-admin', 'verify-identity'], template: '<button data-header-switch :disabled="switchBusy" @click="$emit(\'switch-account\')">切换员工</button>' },
    AppSidebar: true,
    ErpLayout: { template: '<div data-erp-layout><slot name="header" /><slot name="sidebar" /><slot /></div>' },
    PageContainer: { template: '<main><slot /></main>' },
    AppWindowDialog: { props: ['modelValue'], template: '<section v-if="modelValue" role="dialog"><slot /><slot name="footer" /></section>' },
  } } })
}

describe('App根控制器跨布局保留', () => {
  it('返回浏览器和切换可见状态不会使已登录身份失效', async () => {
    const auth = useAuthStore()
    const verified = auth.authenticationVerified
    const initialize = vi.spyOn(auth, 'initialize').mockResolvedValue()
    const wrapper = render()
    try {
      window.dispatchEvent(new Event('focus'))
      document.dispatchEvent(new Event('visibilitychange'))
      await auth.ensureAuthentication()
      expect(auth.authenticationVerified).toBe(verified)
      expect(initialize).not.toHaveBeenCalled()
    } finally {
      wrapper.unmount()
    }
  })
  it('Header只打开根控制器，跨布局不重建flow，也不显示独立账号操作入口', async () => {
    const wrapper = render()
    expect(useFlow).toHaveBeenCalledTimes(1)
    expect(wrapper.find('[data-erp-layout]').exists()).toBe(true)
    await wrapper.get('[data-header-switch]').trigger('click')
    await flushPromises()
    expect(useAuthStore().loadSwitchTargets).toHaveBeenCalledTimes(1)
    expect(wrapper.find('[role="dialog"]').exists()).toBe(true)
    for (const name of ['account-switch-transition', 'waiting-role', 'production-overview', 'login']) {
      route.name = name
      route.meta.layout = 'none'
      await nextTick()
      expect(wrapper.find('[data-account-switch-banner]').exists()).toBe(false)
      expect(wrapper.find('[data-standalone-account-menu]').exists()).toBe(false)
      expect(wrapper.find('[data-route-page]').exists()).toBe(true)
      expect(wrapper.find('[data-erp-layout]').exists()).toBe(false)
      expect(useFlow).toHaveBeenCalledTimes(1)
    }
    useAuthStore().applyAuthResponse({ authenticated: false, user: null, account_switch: { active: true, can_return: true, identity_version: 'v2' } })
    await nextTick()
    expect(wrapper.find('[data-standalone-account-menu]').exists()).toBe(false)
    expect(useFlow).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })
  it('Header返回和核验事件复用唯一的根flow，错误状态传回Header', async () => {
    const auth = useAuthStore()
    auth.accountSwitch = { active: true, can_return: true, identity_version: 'v1' }
    const wrapper = render()
    const header = wrapper.getComponent({ name: 'AppHeader' })
    header.vm.$emit('return-admin')
    await flushPromises()
    const currentFlow = useFlow.mock.results[0]!.value
    expect(currentFlow.returnAdmin).toHaveBeenCalledTimes(1)
    header.vm.$emit('verify-identity')
    await flushPromises()
    expect(currentFlow.verifyIdentity).toHaveBeenCalledTimes(1)
    expect(useFlow).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })
  it('根flow busy传给Header防止并发命令', async () => {
    const wrapper = render()
    const currentFlow = useFlow.mock.results[0]!.value
    currentFlow.busy.value = true
    await nextTick()
    expect((wrapper.get('[data-header-switch]').element as HTMLButtonElement).disabled).toBe(true)
    wrapper.unmount()
  })
})
