import { DOMWrapper, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { AxiosError } from 'axios'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import NotificationRulesView from './NotificationRulesView.vue'
import { useAuthStore } from '@/stores/auth'
import type { NotificationPreview, NotificationRule, NotificationRulesResponse } from '@/types/notifications'

const api = vi.hoisted(() => ({ getNotificationRules: vi.fn(), saveNotificationRule: vi.fn(), previewNotificationRule: vi.fn() }))
vi.mock('@/api/notifications', async original => ({ ...await original<object>(), ...api }))
const rule: NotificationRule = {
  event_code: 'PRODUCTION_TASK_CONFIRMED', display_name: '生产任务确认', name: '任务通知',
  title_template: '生产任务', body_template: '{{document_no}} 已由 {{operator}} 于 {{occurred_at}} 确认。',
  allowed_variables: ['document_no', 'operator', 'occurred_at'], required_variables: ['document_no', 'operator', 'occurred_at'],
  supported_scopes: ['ROLE_MEMBERS'], scope_labels: { ROLE_MEMBERS: '所选角色的合法成员' },
  recipient_role_codes: ['TECHNICAL'], recipient_roles: [{ role_code: 'TECHNICAL', display_name: '技术', archived: false }],
  recipient_scope: 'ROLE_MEMBERS', enabled: true, version: 0, updated_at: null, updated_by: '', etag: 'server-v0', target_key: 'production-task-detail',
}
const sample: NotificationPreview = { event_code: rule.event_code, title: '生产任务示例', body: '示例单号已确认', recipient_scope: 'ROLE_MEMBERS', scope_label: '所选角色的合法成员', recipient_role_codes: ['TECHNICAL'], will_send: false }
const wrappers: ReturnType<typeof mount>[] = []
function result(): NotificationRulesResponse { return { data: [{ ...rule }], roles: [...rule.recipient_roles] } }
function button(label: string) { return new DOMWrapper(Array.from(document.querySelectorAll('button')).find(item => item.textContent?.trim() === label)!) }
function input(selector: string) { return new DOMWrapper(document.querySelector(selector)!) }
async function render() { const wrapper = mount(NotificationRulesView, { attachTo: document.body }); wrappers.push(wrapper); await flushPromises(); return wrapper }
async function edit() { const wrapper = await render(); await button('编辑 / 预览').trigger('click'); await flushPromises(); return wrapper }

beforeEach(() => {
  vi.resetAllMocks(); setActivePinia(createPinia())
  useAuthStore().applyAuthResponse({ authenticated: true, user: { id: 1, username: 'admin', display_name: '管理员', is_superuser: true, employee: { id: 'admin', employee_code: 'ADMIN', display_name: '管理员', status: 'ACTIVE' }, permissions: [], data_scope: 'ALL' } })
  api.getNotificationRules.mockImplementation(async () => result())
  api.previewNotificationRule.mockResolvedValue({ ...sample })
  api.saveNotificationRule.mockImplementation(async (_code, data) => ({ data: { ...rule, ...data, version: 1, etag: 'server-v1' }, etag: 'server-v1' }))
})
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()); document.body.innerHTML = ''; vi.restoreAllMocks() })

describe('通知规则页面', () => {
  it('无管理权限时不读取规则，授权后重新读取', async () => {
    useAuthStore().user!.is_superuser = false
    const wrapper = await render()
    expect(wrapper.text()).toContain('没有通知规则管理权限')
    expect(api.getNotificationRules).not.toHaveBeenCalled()
    useAuthStore().user!.is_superuser = true
    await flushPromises()
    expect(api.getNotificationRules).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('任务通知')
  })

  it('加载失败只显示错误，重试前不显示无规则的假空态', async () => {
    api.getNotificationRules.mockRejectedValueOnce(new Error('network'))
    const wrapper = await render()
    expect(wrapper.text()).toContain('加载失败')
    expect(wrapper.text()).not.toContain('暂无已登记通知规则')
    await button('刷新').trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('任务通知')
  })

  it('首次保存使用服务端默认规则版本，重新编辑采用保存响应的新版本', async () => {
    await edit()
    await input('#notification-name').setValue(' 修改名称 ')
    await button('保存').trigger('click'); await flushPromises()
    expect(api.saveNotificationRule).toHaveBeenCalledWith(rule.event_code, expect.objectContaining({ name: '修改名称', recipient_role_codes: ['TECHNICAL'] }), 'server-v0')
    expect(document.body.textContent).toContain('通知规则已保存')
    await button('编辑 / 预览').trigger('click'); await flushPromises()
    await button('保存').trigger('click'); await flushPromises()
    expect(api.saveNotificationRule.mock.calls[1]![2]).toBe('server-v1')
  })

  it('预览使用当前未保存内容及允许变量，修改后清除旧预览', async () => {
    await edit()
    await input('#notification-title').setValue('新标题')
    await button('生成预览').trigger('click'); await flushPromises()
    expect(api.previewNotificationRule).toHaveBeenCalledWith(rule.event_code, expect.objectContaining({ title_template: '新标题', variables: { document_no: '示例单号', operator: '示例操作人', occurred_at: '示例时间' } }))
    expect(document.querySelector('.preview-message')?.textContent).toContain('示例单号已确认')
    await input('#notification-title').setValue('再次修改')
    expect(document.querySelector('.preview-message')).toBeNull()
    expect(api.saveNotificationRule).not.toHaveBeenCalled()
  })

  it('预览在途时修改表单，迟到响应不能回填旧预览', async () => {
    let finish!: (value: NotificationPreview) => void
    api.previewNotificationRule.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    await edit()
    await button('生成预览').trigger('click')
    await input('#notification-title').setValue('请求后修改')
    finish(sample); await flushPromises()
    expect(document.querySelector('.preview-message')).toBeNull()
  })

  it('缺少必要变量或使用未知变量时不调用预览和保存接口', async () => {
    await edit()
    await input('#notification-body').setValue('{{document_no}}')
    await button('保存').trigger('click')
    expect(document.body.textContent).toContain('模板必须包含')
    expect(api.saveNotificationRule).not.toHaveBeenCalled()
    await input('#notification-body').setValue(rule.body_template + '{{unknown}}')
    await button('生成预览').trigger('click')
    expect(document.body.textContent).toContain('不允许的变量')
    expect(api.previewNotificationRule).not.toHaveBeenCalled()
  })

  it('并发冲突保留编辑内容并禁止再次保存', async () => {
    api.saveNotificationRule.mockRejectedValueOnce(new AxiosError('conflict', undefined, undefined, undefined, { status: 412 } as never))
    await edit()
    await input('#notification-name').setValue('保留我的修改')
    await button('保存').trigger('click'); await flushPromises()
    expect((input('#notification-name').element as HTMLInputElement).value).toBe('保留我的修改')
    expect(document.body.textContent).toContain('关闭弹窗并刷新')
    expect(button('保存').attributes('disabled')).toBeDefined()
    expect(api.saveNotificationRule).toHaveBeenCalledTimes(1)
  })

  it('权限撤销关闭弹窗并清空数据，迟到保存响应不恢复旧内容', async () => {
    let finish!: (value: unknown) => void
    api.saveNotificationRule.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    const wrapper = await edit()
    await button('保存').trigger('click')
    useAuthStore().user!.is_superuser = false
    await flushPromises()
    expect(document.querySelector('#notification-name')).toBeNull()
    expect(wrapper.text()).not.toContain('任务通知')
    finish({ data: { ...rule, name: '迟到内容' }, etag: 'v2' }); await flushPromises()
    expect(document.body.textContent).not.toContain('迟到内容')
    expect(document.body.textContent).not.toContain('通知规则已保存')
  })

  it('撤权后重新授权的新列表不会被旧账号请求覆盖', async () => {
    let finish!: (value: NotificationRulesResponse) => void
    api.getNotificationRules.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    const wrapper = await render()
    useAuthStore().user!.is_superuser = false
    await flushPromises()
    useAuthStore().user!.is_superuser = true
    await flushPromises()
    finish({ data: [{ ...rule, name: '迟到敏感内容' }], roles: [] }); await flushPromises()
    expect(wrapper.text()).toContain('任务通知')
    expect(wrapper.text()).not.toContain('迟到敏感内容')
  })

  it('服务端拒绝权限时立即清空编辑器和规则', async () => {
    api.previewNotificationRule.mockRejectedValueOnce(new AxiosError('forbidden', undefined, undefined, undefined, { status: 403 } as never))
    const wrapper = await edit()
    await button('生成预览').trigger('click'); await flushPromises()
    expect(document.querySelector('#notification-name')).toBeNull()
    expect(wrapper.text()).not.toContain('任务通知')
    expect(wrapper.text()).toContain('没有通知规则管理权限')
  })
})
