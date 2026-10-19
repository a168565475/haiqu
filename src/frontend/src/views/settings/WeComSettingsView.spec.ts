import { DOMWrapper, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { AxiosError } from 'axios'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import WeComSettingsView from './WeComSettingsView.vue'
import viewSource from './WeComSettingsView.vue?raw'
import { useAuthStore } from '@/stores/auth'
import type { WeComConfig, WeComConfigWrite } from '@/types/wecom'

const api = vi.hoisted(() => ({ getWeComConfig: vi.fn(), saveWeComConfig: vi.fn(), checkWeComConnection: vi.fn(), getWeComBindings: vi.fn(), getWeComEmployees: vi.fn(), bindWeComEmployee: vi.fn(), getWeComAudits: vi.fn() }))
vi.mock('@/api/wecom', async importOriginal => ({ ...await importOriginal<object>(), ...api }))
const push = vi.hoisted(() => vi.fn())
vi.mock('vue-router', () => ({ useRouter: () => ({ push }), onBeforeRouteLeave: vi.fn() }))
const savedCredentials = { secret: 'fixture-secret', callback_token: 'fixturetoken', callback_aes_key: 'a'.repeat(43) }
const credentialFields = { secret: '#wecom-secret', callback_token: '#wecom-token', callback_aes_key: '#wecom-aes' } as const
const config: WeComConfig = { corp_id: 'corp', agent_id: '1', erp_origin: 'https://erp.test', enabled: false, ...savedCredentials, credential_read_errors: [], has_secret: true, has_callback_token: true, has_callback_aes_key: true, encryption_ready: true, configuration_complete: true, last_check_status: 'NOT_CHECKED', last_check_message: '', last_checked_at: null, login_url: 'https://erp.test/api/auth/wecom/start/', callback_url: 'https://erp.test/api/auth/wecom/callback/', trusted_domain: 'erp.test' }
const wrappers: ReturnType<typeof mount>[] = []
async function render() { const wrapper = mount(WeComSettingsView, { attachTo: document.body }); wrappers.push(wrapper); await flushPromises(); return wrapper }
function button(text: string) { return new DOMWrapper(Array.from(document.querySelectorAll('button')).find(item => item.textContent?.trim() === text)!) }
beforeEach(() => {
  setActivePinia(createPinia()); vi.resetAllMocks()
  useAuthStore().applyAuthResponse({ authenticated: true, user: { id: 1, username: 'admin', display_name: '管理员', is_superuser: true, employee: { id: 'admin', employee_code: 'ADMIN', display_name: '管理员', status: 'ACTIVE' }, permissions: [], data_scope: 'ALL' } })
  api.getWeComConfig.mockResolvedValue({ data: { ...config }, etag: 'v1' })
  api.saveWeComConfig.mockImplementation(async (payload: WeComConfigWrite) => ({ data: { ...config, ...payload }, etag: 'v2' }))
  api.checkWeComConnection.mockResolvedValue({ data: { ...config, last_check_status: 'SUCCESS' }, etag: 'v3' })
  api.getWeComBindings.mockResolvedValue({ data: [], count: 0, page: 1, page_size: 20 })
  api.getWeComEmployees.mockResolvedValue([{ id: 'employee', employee_code: 'EMP1', display_name: '已有员工', username: 'existing', etag: 'emp-v1' }])
  api.getWeComAudits.mockResolvedValue({ data: [], count: 0, page: 1, page_size: 20 })
})
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()); document.body.innerHTML = '' })

describe('企业微信管理页', () => {
  it('工作台应用主页展示并复制ERP根网址，授权回调仍保留专用路径', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    vi.stubGlobal('navigator', { clipboard: { writeText } })
    try {
      const wrapper = await render()
      const row = wrapper.findAll('.address-row').find(item => item.text().includes('工作台应用主页'))!
      expect(row.get('.address-value').text()).toBe(config.erp_origin)
      await row.get('button').trigger('click'); await flushPromises()
      expect(writeText).toHaveBeenCalledWith(config.erp_origin)
      expect(wrapper.text()).toContain(config.callback_url)
    } finally { vi.unstubAllGlobals() }
  })
  it('标题局部覆盖外层强制字号，并保留批准的无衬线字重和桌面尺寸', () => {
    expect(viewSource).toMatch(/#erp-main-content \.wecom-page h1\s*\{\s*font:\s*700 36px\/44px var\(--erp-font-body\) !important;\s*\}/)
  })
  it('窄屏标题也能覆盖外层强制字号，保持28px字号和38px行高', () => {
    const mobileStyles = viewSource.split('@media (max-width: 640px)')[1]
    expect(mobileStyles).toMatch(/#erp-main-content \.wecom-page h1\s*\{\s*font-size:\s*28px !important;\s*line-height:\s*38px !important;\s*\}/)
  })
  it('读取后直接显示三项已保存凭据，未修改时可检查连接', async () => {
    const wrapper = await render()
    for (const [key, selector] of Object.entries(credentialFields)) {
      const input = wrapper.get(selector).element as HTMLInputElement
      expect(input.value).toBe(savedCredentials[key as keyof typeof savedCredentials])
      expect(input.type).toBe('text')
      expect(input.autocomplete).toBe('off')
      expect(input.closest('details')).toBeNull()
    }
    expect(wrapper.text()).not.toContain('有未保存的修改')
    expect(button('检查连接').attributes('disabled')).toBeUndefined()
    await button('检查连接').trigger('click'); await flushPromises()
    expect(api.checkWeComConnection).toHaveBeenCalledWith('v1')
    expect((wrapper.get('#wecom-secret').element as HTMLInputElement).value).toBe(savedCredentials.secret)
    expect(button('检查连接').attributes('disabled')).toBeUndefined()
  })
  it.each([
    ['secret', '应用 Secret'], ['callback_token', '消息回调 Token'], ['callback_aes_key', 'EncodingAESKey'],
  ] as const)('%s读取失败明确提示并保留null快照，其他正常凭据继续回显', async (field, label) => {
    api.getWeComConfig.mockResolvedValueOnce({ data: { ...config, [field]: null, credential_read_errors: [field] }, etag: 'broken-v1' })
    const wrapper = await render()
    const state = (wrapper.vm.$ as unknown as { setupState: { form: WeComConfigWrite; config: WeComConfig } }).setupState
    expect(state.config[field]).toBeNull()
    expect(state.form[field]).toBe('')
    expect(wrapper.get('.credential-read-error').text()).toContain(`${label}读取失败`)
    expect(wrapper.get('.credential-read-error').text()).toContain('重新填写对应字段并保存')
    expect(wrapper.get(credentialFields[field]).element.closest('label')?.textContent).toContain('读取失败')
    expect(wrapper.text()).not.toContain('有未保存的修改')
    for (const [key, selector] of Object.entries(credentialFields)) {
      if (key !== field) expect((wrapper.get(selector).element as HTMLInputElement).value).toBe(savedCredentials[key as keyof typeof savedCredentials])
    }
  })
  it('登录凭据损坏时仍能关闭入口，留空不覆盖，替换成功后恢复回显并清除提示', async () => {
    const damaged = { ...config, enabled: true, secret: null, credential_read_errors: ['secret'], configuration_complete: false, last_check_status: 'SUCCESS' }
    api.getWeComConfig.mockResolvedValueOnce({ data: damaged, etag: 'broken-v1' })
    api.saveWeComConfig.mockResolvedValueOnce({ data: { ...damaged, enabled: false }, etag: 'broken-v2' })
    const wrapper = await render()
    expect(button('检查连接').attributes('disabled')).toBeDefined()
    const toggle = wrapper.get('[role="switch"]')
    expect(toggle.attributes('disabled')).toBeUndefined()
    await toggle.trigger('click')
    await button('保存配置').trigger('click'); await flushPromises()
    expect(api.saveWeComConfig.mock.calls[0]![0]).toMatchObject({ enabled: false })
    expect(api.saveWeComConfig.mock.calls[0]![0]).not.toHaveProperty('secret')
    expect(wrapper.get('.credential-read-error').text()).toContain('应用 Secret读取失败')
    expect(toggle.attributes('aria-checked')).toBe('false')
    await wrapper.get('#wecom-secret').setValue('recovered-secret')
    await button('保存配置').trigger('click'); await flushPromises()
    expect(api.saveWeComConfig.mock.calls[1]![0]).toMatchObject({ enabled: false, secret: 'recovered-secret' })
    expect(api.saveWeComConfig.mock.calls[1]![1]).toBe('broken-v2')
    expect(wrapper.find('.credential-read-error').exists()).toBe(false)
    expect((wrapper.get('#wecom-secret').element as HTMLInputElement).value).toBe('recovered-secret')
    expect(button('检查连接').attributes('disabled')).toBeUndefined()
  })
  it('保存后回填服务器值并使用新版本，再次保存不重复提交未变凭据', async () => {
    const wrapper = await render()
    await wrapper.get('#wecom-secret').setValue('new-secret')
    await wrapper.get('#wecom-token').setValue('newtoken')
    await wrapper.get('#wecom-aes').setValue('b'.repeat(43))
    await button('保存配置').trigger('click'); await flushPromises()
    expect(api.saveWeComConfig).toHaveBeenCalledWith(expect.objectContaining({ secret: 'new-secret', callback_token: 'newtoken', callback_aes_key: 'b'.repeat(43) }), 'v1')
    expect((wrapper.get('#wecom-secret').element as HTMLInputElement).value).toBe('new-secret')
    expect((wrapper.get('#wecom-token').element as HTMLInputElement).value).toBe('newtoken')
    expect((wrapper.get('#wecom-aes').element as HTMLInputElement).value).toBe('b'.repeat(43))
    expect(button('检查连接').attributes('disabled')).toBeUndefined()
    expect(wrapper.text()).toContain('仅保存凭据，本期不接收消息事件')
    await button('保存配置').trigger('click'); await flushPromises()
    expect(api.saveWeComConfig.mock.calls[1]![1]).toBe('v2')
    for (const key of Object.keys(credentialFields)) expect(api.saveWeComConfig.mock.calls[1]![0]).not.toHaveProperty(key)
  })
  it('版本冲突停止继续保存并允许重新读取', async () => {
    api.saveWeComConfig.mockRejectedValueOnce(new AxiosError('conflict', undefined, undefined, undefined, { status: 412 } as never))
    const wrapper = await render()
    await wrapper.get('#wecom-secret').setValue('edited-secret')
    await button('保存配置').trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('配置已被修改')
    expect(button('保存配置').attributes('disabled')).toBeDefined()
    expect((wrapper.get('#wecom-secret').element as HTMLInputElement).value).toBe('edited-secret')
    expect(wrapper.text()).not.toContain('配置已保存。')
    api.getWeComConfig.mockResolvedValueOnce({ data: { ...config, secret: 'server-new-secret' }, etag: 'v4' })
    await button('重新加载配置').trigger('click'); await flushPromises()
    expect(button('保存配置').attributes('disabled')).toBeUndefined()
    expect((wrapper.get('#wecom-secret').element as HTMLInputElement).value).toBe('server-new-secret')
    expect(button('检查连接').attributes('disabled')).toBeUndefined()
    await button('保存配置').trigger('click'); await flushPromises()
    expect(api.saveWeComConfig.mock.calls[1]![1]).toBe('v4')
  })
  it('保存失败保留编辑值且不显示成功，改回保存值后恢复检查连接', async () => {
    api.saveWeComConfig.mockRejectedValueOnce(new Error('network'))
    const wrapper = await render()
    await wrapper.get('#wecom-token').setValue('editedtoken')
    expect(button('检查连接').attributes('disabled')).toBeDefined()
    await button('保存配置').trigger('click'); await flushPromises()
    expect((wrapper.get('#wecom-token').element as HTMLInputElement).value).toBe('editedtoken')
    expect((wrapper.get('#wecom-secret').element as HTMLInputElement).value).toBe(savedCredentials.secret)
    expect(wrapper.text()).not.toContain('配置已保存。')
    expect(api.saveWeComConfig.mock.calls[0]![0]).toMatchObject({ callback_token: 'editedtoken' })
    expect(api.saveWeComConfig.mock.calls[0]![0]).not.toHaveProperty('secret')
    expect(api.saveWeComConfig.mock.calls[0]![0]).not.toHaveProperty('callback_aes_key')
    await wrapper.get('#wecom-token').setValue(savedCredentials.callback_token)
    expect(button('检查连接').attributes('disabled')).toBeUndefined()
  })
  it('清空已保存凭据或填空格均保留原值，仍可检查连接', async () => {
    const wrapper = await render()
    await wrapper.get('#wecom-secret').setValue('')
    await wrapper.get('#wecom-token').setValue('   ')
    await wrapper.get('#wecom-aes').setValue('')
    expect(wrapper.text()).not.toContain('有未保存的修改')
    expect(button('检查连接').attributes('disabled')).toBeUndefined()
    await button('检查连接').trigger('click'); await flushPromises()
    expect(api.checkWeComConnection).toHaveBeenCalledWith('v1')
    expect(api.saveWeComConfig).not.toHaveBeenCalled()
    for (const [key, selector] of Object.entries(credentialFields)) {
      expect((wrapper.get(selector).element as HTMLInputElement).value).toBe(savedCredentials[key as keyof typeof savedCredentials])
    }
  })
  it('重新挂载从API回填凭据，不写入浏览器存储或认证状态', async () => {
    const first = await render()
    first.unmount(); wrappers.splice(wrappers.indexOf(first), 1)
    const wrapper = await render()
    expect(api.getWeComConfig).toHaveBeenCalledTimes(2)
    for (const [key, selector] of Object.entries(credentialFields)) {
      const credential = savedCredentials[key as keyof typeof savedCredentials]
      expect((wrapper.get(selector).element as HTMLInputElement).value).toBe(credential)
      expect(JSON.stringify(localStorage)).not.toContain(credential)
      expect(JSON.stringify(sessionStorage)).not.toContain(credential)
      expect(JSON.stringify(useAuthStore().$state)).not.toContain(credential)
    }
  })
  it('卸载清除编辑值和保存快照，迟到响应不能重新回填明文', async () => {
    let finishCheck!: (value: { data: WeComConfig; etag: string }) => void
    api.checkWeComConnection.mockImplementationOnce(() => new Promise(resolve => { finishCheck = resolve }))
    const wrapper = await render()
    const state = (wrapper.vm.$ as unknown as { setupState: { form: WeComConfigWrite; config?: WeComConfig } }).setupState
    const snapshot = state.config!
    await button('检查连接').trigger('click')
    wrapper.unmount(); wrappers.splice(wrappers.indexOf(wrapper), 1)
    for (const key of Object.keys(credentialFields) as (keyof typeof credentialFields)[]) {
      expect(state.form[key]).toBe('')
      expect(snapshot[key]).toBe('')
    }
    expect(state.config).toBeUndefined()
    finishCheck({ data: { ...config, last_check_status: 'SUCCESS' }, etag: 'v5' }); await flushPromises()
    expect(state.config).toBeUndefined()
    for (const key of Object.keys(credentialFields) as (keyof typeof credentialFields)[]) expect(state.form[key]).toBe('')
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
    await wrapper.get('#wecom-secret').setValue(' ')
    await button('保存配置').trigger('click'); await flushPromises()
    expect(api.saveWeComConfig).toHaveBeenCalledTimes(1)
    for (const [key, selector] of Object.entries(credentialFields)) {
      expect(api.saveWeComConfig.mock.calls[0]![0]).not.toHaveProperty(key)
      expect((wrapper.get(selector).element as HTMLInputElement).value).toBe(savedCredentials[key as keyof typeof savedCredentials])
    }
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
