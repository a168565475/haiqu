import { defineComponent, type PropType } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { ElMessage } from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import { useAuthStore } from '@/stores/auth'
import type { SystemSettingsKey } from '@/config/systemSettings'
import SystemSettingsView from './SystemSettingsView.vue'

const navigation = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn(), leave: vi.fn() }))
const pages = vi.hoisted(() => {
  const canClose = vi.fn(), created = vi.fn()
  function component(name: string) {
    return { props: ['section', 'embedded'], setup(_: unknown, context: { expose: (value: unknown) => void }) {
      created(name); context.expose({ canClose: () => canClose(name) }); return { pageName: name }
    }, template: '<div :data-loaded-page="pageName" :data-section="section" :data-embedded="embedded">{{ pageName }}</div>' }
  }
  return { canClose, created, component }
})
vi.mock('vue-router', () => ({ useRouter: () => navigation, onBeforeRouteLeave: (guard: unknown) => navigation.leave(guard) }))
vi.mock('@/directives/glassSpotlight', () => ({ vGlassSpotlight: {} }))
vi.mock('./ProductionDataView.vue', () => ({ default: pages.component('production') }))
vi.mock('./EmailAccountSettingsView.vue', () => ({ default: pages.component('email') }))
vi.mock('./InquiryHandlingSettingsView.vue', () => ({ default: pages.component('inquiry') }))
vi.mock('./MasterDataCenterView.vue', () => ({ default: pages.component('masterData') }))
vi.mock('./NumberRulesView.vue', () => ({ default: pages.component('numberRules') }))
vi.mock('./NotificationRulesView.vue', () => ({ default: pages.component('notifications') }))
vi.mock('./ThemeSettingsView.vue', () => ({ default: pages.component('theme') }))
vi.mock('./ReferenceDataSettingsView.vue', () => ({ default: pages.component('referenceData') }))
vi.mock('./WeComSettingsView.vue', () => ({ default: pages.component('wecom') }))
vi.mock('./AccessManagementView.vue', () => ({ default: pages.component('access') }))

const dialogStub = defineComponent({
  props: { modelValue: Boolean, title: String, width: Number, height: Number, fullscreen: Boolean, edgeToEdge: Boolean, destroyOnClose: Boolean, closeOnClickModal: Boolean,
    beforeClose: { type: Function as PropType<(done: () => void) => void | Promise<void>>, required: true } },
  emits: ['update:modelValue', 'closed'],
  setup(props, { emit }) {
    async function close() { await props.beforeClose(() => { emit('update:modelValue', false); emit('closed') }) }
    return { close }
  },
  template: '<section v-if="modelValue" role="dialog" :aria-label="title"><button data-close-window @click="close">关闭窗口</button><slot /></section>',
})
const wrappers: ReturnType<typeof mount>[] = []
function render() {
  const wrapper = mount(SystemSettingsView, { global: { stubs: { AppWindowDialog: dialogStub, SystemSettingsIcon: true } } })
  wrappers.push(wrapper); return wrapper
}
function keys(wrapper: ReturnType<typeof mount>) { return wrapper.findAll('[data-settings-key]').map(button => button.attributes('data-settings-key')) }
async function open(wrapper: ReturnType<typeof mount>, key: SystemSettingsKey) {
  await wrapper.get(`[data-settings-key="${key}"]`).trigger('click'); await flushPromises()
}
function leave() { return (navigation.leave.mock.calls.at(-1)![0] as () => Promise<boolean>)() }
beforeEach(() => {
  setActivePinia(createPinia()); vi.resetAllMocks()
  const auth = useAuthStore()
  auth.applyAuthResponse({ authenticated: true, user: { id: 1, username: 'admin', display_name: '管理员', is_superuser: true,
    employee: { id: 'admin', employee_code: 'ADMIN', display_name: '管理员', status: 'ACTIVE' }, permissions: ['workflow.view_slapolicy'], data_scope: 'ALL' } })
  vi.spyOn(auth, 'ensureFreshAuthentication').mockResolvedValue()
  pages.canClose.mockResolvedValue(true)
  vi.spyOn(ElMessage, 'warning').mockImplementation(() => ({ close: vi.fn() }))
  vi.spyOn(ElMessage, 'info').mockImplementation(() => ({ close: vi.fn() }))
  vi.spyOn(ElMessage, 'error').mockImplementation(() => ({ close: vi.fn() }))
})
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()); vi.restoreAllMocks() })

describe('系统配置卡片与页面窗口', () => {
  it('首页展示11个入口，未点击时不实例化任何业务页面', () => {
    const wrapper = render()
    expect(keys(wrapper)).toHaveLength(11)
    expect(pages.created).not.toHaveBeenCalled()
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
  })
  it('按当前用户过滤卡片，普通员工邮件与主题入口不被字典权限挡住', () => {
    useAuthStore().user = { ...useAuthStore().user!, username: 'worker', is_superuser: false, permissions: [] }
    const wrapper = render()
    expect(keys(wrapper)).toEqual(['email', 'theme'])
    expect(wrapper.find('[data-settings-key="access"]').exists()).toBe(false)
  })
  it('未登录显示明确空状态且不能打开业务页面', () => {
    useAuthStore().clearAuthentication()
    const wrapper = render()
    expect(keys(wrapper)).toEqual([])
    expect(wrapper.text()).toContain('当前账号没有可用的配置入口')
    expect(pages.created).not.toHaveBeenCalled()
  })
  it.each([
    ['production', 'production'], ['email', 'email'], ['inquiry', 'inquiry'], ['masterData', 'masterData'],
    ['numberRules', 'numberRules'], ['notifications', 'notifications'], ['theme', 'theme'],
    ['parameters', 'referenceData'], ['wecom', 'wecom'], ['access', 'access'], ['dictionary', 'referenceData'],
  ] as const)('%s 加载原来的 %s 页面并保持当前路由', async (key, target) => {
    const wrapper = render()
    await open(wrapper, key)
    expect(wrapper.get('[data-loaded-page]').attributes('data-loaded-page')).toBe(target)
    expect(pages.created).toHaveBeenCalledExactlyOnceWith(target)
    expect(useAuthStore().ensureFreshAuthentication).toHaveBeenCalledTimes(1)
    expect(navigation.push).not.toHaveBeenCalled()
    expect(navigation.replace).not.toHaveBeenCalled()
    const dialog = wrapper.findComponent(AppWindowDialog)
    expect(dialog.props()).toMatchObject({ fullscreen: true, edgeToEdge: true, destroyOnClose: true, closeOnClickModal: false, width: 1120, height: 740 })
    if (key === 'parameters' || key === 'dictionary') expect(wrapper.get('[data-loaded-page]').attributes('data-section')).toBe(key)
    if (['production', 'email', 'inquiry', 'masterData', 'numberRules', 'notifications', 'wecom', 'access'].includes(key)) expect(wrapper.get('[data-loaded-page]').attributes('data-embedded')).toBe('true')
  })
  it('子页面拒绝关闭时保留窗口和路由，通过后销毁且可再次打开', async () => {
    const wrapper = render()
    await open(wrapper, 'access')
    pages.canClose.mockResolvedValue(false)
    await wrapper.get('[data-close-window]').trigger('click'); await flushPromises()
    expect(wrapper.find('[data-loaded-page="access"]').exists()).toBe(true)
    expect(await leave()).toBe(false)
    pages.canClose.mockResolvedValue(true)
    expect(await leave()).toBe(true)
    await wrapper.get('[data-close-window]').trigger('click'); await flushPromises()
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
    await open(wrapper, 'dictionary')
    expect(wrapper.get('[data-loaded-page]').attributes('data-section')).toBe('dictionary')
  })
  it('已打开窗口时不能绕过关闭检查直接切换卡片', async () => {
    const wrapper = render()
    await open(wrapper, 'access')
    await open(wrapper, 'wecom')
    expect(wrapper.get('[data-loaded-page]').attributes('data-loaded-page')).toBe('access')
    expect(ElMessage.info).toHaveBeenCalledWith('请先还原或关闭当前配置窗口。')
    expect(pages.created).toHaveBeenCalledTimes(1)
  })
  it('权限撤销立即移除内容，恢复后重新加载原页', async () => {
    const wrapper = render()
    await open(wrapper, 'wecom')
    pages.canClose.mockResolvedValue(false)
    useAuthStore().user!.is_superuser = false
    await flushPromises()
    expect(wrapper.find('[data-loaded-page]').exists()).toBe(false)
    expect(wrapper.text()).toContain('当前账号已无权访问此配置')
    expect(await leave()).toBe(true)
    expect(pages.canClose).not.toHaveBeenCalled()
    useAuthStore().user!.is_superuser = true
    await flushPromises()
    expect(wrapper.find('[data-loaded-page="wecom"]').exists()).toBe(true)
    expect(pages.created).toHaveBeenCalledTimes(2)
  })
  it('身份确认失败不打开配置，也不误报已登录', async () => {
    const errorLog = vi.spyOn(console, 'error').mockImplementation(() => undefined)
    vi.mocked(useAuthStore().ensureFreshAuthentication).mockRejectedValueOnce(new Error('offline'))
    const wrapper = render()
    await open(wrapper, 'dictionary')
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
    expect(ElMessage.error).toHaveBeenCalledWith('无法确认登录状态，请稍后重试。')
    expect(pages.created).not.toHaveBeenCalled()
    expect(navigation.replace).not.toHaveBeenCalled()
    expect(errorLog).toHaveBeenCalledWith('配置入口身份检查失败', expect.any(Error))
  })
  it('身份刷新发现会话失效时转到登录页并保留配置返回地址', async () => {
    vi.mocked(useAuthStore().ensureFreshAuthentication).mockImplementationOnce(async () => { useAuthStore().clearAuthentication() })
    const wrapper = render()
    await open(wrapper, 'dictionary')
    expect(navigation.replace).toHaveBeenCalledWith({ name: 'login', query: { redirect: '/settings' } })
    expect(pages.created).not.toHaveBeenCalled()
  })
  it('身份刷新进入待授权状态时转到待授权页', async () => {
    vi.mocked(useAuthStore().ensureFreshAuthentication).mockImplementationOnce(async () => { useAuthStore().user!.waiting_for_role = true })
    const wrapper = render()
    await open(wrapper, 'dictionary')
    expect(navigation.replace).toHaveBeenCalledWith({ name: 'waiting-role' })
    expect(pages.created).not.toHaveBeenCalled()
  })
  it('身份刷新撤销目标权限时再次判断，不能按旧卡片打开', async () => {
    vi.mocked(useAuthStore().ensureFreshAuthentication).mockImplementationOnce(async () => { useAuthStore().user!.is_superuser = false })
    const wrapper = render()
    await open(wrapper, 'wecom')
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
    expect(ElMessage.warning).toHaveBeenCalledWith('当前账号没有该配置的访问权限。')
    expect(pages.created).not.toHaveBeenCalled()
  })
  it('身份确认期间卸载后，迟到的失效响应不能导航或加载页面', async () => {
    let finish!: () => void
    vi.mocked(useAuthStore().ensureFreshAuthentication).mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    const wrapper = render()
    await wrapper.get('[data-settings-key="dictionary"]').trigger('click')
    wrapper.unmount(); wrappers.splice(wrappers.indexOf(wrapper), 1)
    useAuthStore().clearAuthentication()
    finish(); await flushPromises()
    expect(navigation.replace).not.toHaveBeenCalled()
    expect(pages.created).not.toHaveBeenCalled()
  })
})
