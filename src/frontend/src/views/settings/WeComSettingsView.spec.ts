import { DOMWrapper, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { AxiosError } from 'axios'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import WeComSettingsView from './WeComSettingsView.vue'
import viewSource from './WeComSettingsView.vue?raw'
import { useAuthStore } from '@/stores/auth'
import type { WeComConfig } from '@/types/wecom'

const api = vi.hoisted(() => ({ getWeComConfig: vi.fn(), saveWeComConfig: vi.fn(), checkWeComConnection: vi.fn(), getWeComBindings: vi.fn(), getWeComEmployees: vi.fn(), bindWeComEmployee: vi.fn(), getWeComAudits: vi.fn() }))
vi.mock('@/api/wecom', async importOriginal => ({ ...await importOriginal<object>(), ...api }))
const push = vi.hoisted(() => vi.fn())
vi.mock('vue-router', () => ({ useRouter: () => ({ push }), onBeforeRouteLeave: vi.fn() }))
const config: WeComConfig = { corp_id: 'corp', agent_id: '1', erp_origin: 'https://erp.test', enabled: false, has_secret: true, has_callback_token: false, has_callback_aes_key: false, encryption_ready: true, configuration_complete: true, last_check_status: 'NOT_CHECKED', last_check_message: '', last_checked_at: null, login_url: 'https://erp.test/api/auth/wecom/start/', callback_url: 'https://erp.test/api/auth/wecom/callback/', trusted_domain: 'erp.test' }
const wrappers: ReturnType<typeof mount>[] = []
async function render() { const wrapper = mount(WeComSettingsView, { attachTo: document.body }); wrappers.push(wrapper); await flushPromises(); return wrapper }
function button(text: string) { return new DOMWrapper(Array.from(document.querySelectorAll('button')).find(item => item.textContent?.trim() === text)!) }
beforeEach(() => {
  setActivePinia(createPinia()); vi.clearAllMocks()
  useAuthStore().applyAuthResponse({ authenticated: true, user: { id: 1, username: 'admin', display_name: '管理员', is_superuser: true, employee: { id: 'admin', employee_code: 'ADMIN', display_name: '管理员', status: 'ACTIVE' }, permissions: [], data_scope: 'ALL' } })
  api.getWeComConfig.mockResolvedValue({ data: { ...config }, etag: 'v1' })
  api.saveWeComConfig.mockResolvedValue({ data: { ...config, has_callback_token: true, has_callback_aes_key: true }, etag: 'v2' })
  api.getWeComBindings.mockResolvedValue({ data: [], count: 0, page: 1, page_size: 20 })
  api.getWeComEmployees.mockResolvedValue([{ id: 'employee', employee_code: 'EMP1', display_name: '已有员工', username: 'existing', etag: 'emp-v1' }])
  api.getWeComAudits.mockResolvedValue({ data: [], count: 0, page: 1, page_size: 20 })
})
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()); document.body.innerHTML = '' })

describe('企业微信管理页', () => {
  it('标题局部覆盖外层强制字号，并保留批准的无衬线字重和桌面尺寸', () => {
    expect(viewSource).toMatch(/#erp-main-content \.wecom-page h1\s*\{\s*font:\s*700 36px\/44px var\(--erp-font-body\) !important;\s*\}/)
  })
  it('窄屏标题也能覆盖外层强制字号，保持28px字号和38px行高', () => {
    const mobileStyles = viewSource.split('@media (max-width: 640px)')[1]
    expect(mobileStyles).toMatch(/#erp-main-content \.wecom-page h1\s*\{\s*font-size:\s*28px !important;\s*line-height:\s*38px !important;\s*\}/)
  })
  it('Secret与消息回调凭据分区，保存后清空输入并使用新版本', async () => {
    const wrapper = await render()
    await wrapper.get('#wecom-secret').setValue('new-secret')
    await wrapper.get('#wecom-token').setValue('newtoken')
    await wrapper.get('#wecom-aes').setValue('a'.repeat(43))
    await button('保存配置').trigger('click'); await flushPromises()
    expect(api.saveWeComConfig).toHaveBeenCalledWith(expect.objectContaining({ secret: 'new-secret', callback_token: 'newtoken', callback_aes_key: 'a'.repeat(43) }), 'v1')
    for (const selector of ['#wecom-secret', '#wecom-token', '#wecom-aes']) expect((wrapper.get(selector).element as HTMLInputElement).value).toBe('')
    expect(wrapper.text()).toContain('仅保存凭据，本期不接收消息事件')
    await button('保存配置').trigger('click'); await flushPromises()
    expect(api.saveWeComConfig.mock.calls[1]![1]).toBe('v2')
  })
  it('版本冲突停止继续保存并允许重新读取', async () => {
    api.saveWeComConfig.mockRejectedValueOnce(new AxiosError('conflict', undefined, undefined, undefined, { status: 412 } as never))
    const wrapper = await render()
    await wrapper.get('#wecom-secret').setValue('never-echo-this')
    await button('保存配置').trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('配置已被修改')
    expect(button('保存配置').attributes('disabled')).toBeDefined()
    expect((wrapper.get('#wecom-secret').element as HTMLInputElement).value).toBe('')
    await button('重新加载配置').trigger('click'); await flushPromises()
    expect(button('保存配置').attributes('disabled')).toBeUndefined()
  })
  it('普通员工不能读取管理配置', async () => {
    useAuthStore().user!.is_superuser = false
    const wrapper = await render()
    expect(wrapper.text()).toContain('无企业微信管理权限')
    expect(api.getWeComConfig).not.toHaveBeenCalled()
  })
  it('错误的回调密钥格式不发请求，空白输入允许保留旧值', async () => {
    const wrapper = await render()
    await wrapper.get('#wecom-aes').setValue('short')
    await button('保存配置').trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('43 位')
    expect(api.saveWeComConfig).not.toHaveBeenCalled()
    await wrapper.get('#wecom-aes').setValue(' ')
    await wrapper.get('#wecom-token').setValue(' ')
    await button('保存配置').trigger('click'); await flushPromises()
    expect(api.saveWeComConfig).toHaveBeenCalledTimes(1)
  })
  it('绑定需要选择员工并确认身份，409保留弹窗且不合并', async () => {
    api.bindWeComEmployee.mockRejectedValueOnce(new AxiosError('conflict', undefined, undefined, undefined, { status: 409 } as never))
    await render()
    await button('员工绑定').trigger('click'); await flushPromises()
    await button('绑定已有员工').trigger('click'); await flushPromises()
    expect(button('确认绑定').attributes('disabled')).toBeDefined()
    const body = new DOMWrapper(document.body)
    await body.get('#wecom-user-id').setValue('Member.A')
    await body.get('#wecom-employee').setValue('employee')
    await body.get('#wecom-confirm').setValue(true)
    await button('确认绑定').trigger('click'); await flushPromises()
    expect(api.bindWeComEmployee).toHaveBeenCalledWith('Member.A', expect.objectContaining({ id: 'employee', etag: 'emp-v1' }))
    expect(document.body.textContent).toContain('未覆盖或合并')
    expect(document.body.querySelector('#wecom-user-id')).not.toBeNull()
  })
  it('绑定列表空态和查询失败不冒充记录，审计空态单独展示', async () => {
    const wrapper = await render()
    await button('员工绑定').trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('暂无符合条件的绑定记录')
    api.getWeComBindings.mockRejectedValueOnce(new Error('network'))
    await button('查询').trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('无法读取绑定记录')
    await button('绑定记录').trigger('click'); await flushPromises()
    expect(document.body.textContent).toContain('暂无操作记录')
  })
})
