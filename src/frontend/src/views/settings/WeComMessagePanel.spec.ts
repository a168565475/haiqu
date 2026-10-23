import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { AxiosError } from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import WeComSettingsView from './WeComSettingsView.vue'
import { useAuthStore } from '@/stores/auth'

const api = vi.hoisted(() => ({ getWeComConfig: vi.fn(), getWeComBindings: vi.fn(), getWeComMessageTemplate: vi.fn(), saveWeComMessageTemplate: vi.fn(), sendWeComMessageTest: vi.fn(), getWeComMessageAttempts: vi.fn() }))
vi.mock('@/api/wecom', async original => ({ ...await original<object>(), ...api }))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }), onBeforeRouteLeave: vi.fn() }))
const template = { name: '通用通知', body: '{{接收人}}：{{消息内容}}\n{{发送时间}}\n{{系统地址}}', is_saved: false, updated_at: null }
const binding = { id: 'binding-a', user_id: 'Member.A', member_name: '员工甲', employee_id: 'employee-a', employee_code: 'EMP-A', employee_name: '员工甲', username: 'member_a', role_status: 'active', source: 'AUTO', created_at: '2026-10-19T00:00:00Z' }
const accepted = { id: 'attempt-a', idempotency_key: '00000000-0000-4000-8000-000000000001', template_name: '通用通知', recipient_name: '员工甲', user_id: 'Member.A', status: 'ACCEPTED', message: '企业微信已受理。', created_at: '2026-10-19T08:00:00Z', finished_at: '2026-10-19T08:00:01Z' }
const wrappers: ReturnType<typeof mount>[] = []
function page(items: unknown[] = []) { return { data: items, count: items.length, page: 1, page_size: 20 } }
function button(wrapper: ReturnType<typeof mount>, text: string) { return wrapper.findAll('button').find(item => item.text().trim() === text)! }
async function renderMessages() {
  const wrapper = mount(WeComSettingsView); wrappers.push(wrapper); await flushPromises()
  await button(wrapper, '消息模板').trigger('click'); await flushPromises(); return wrapper
}
beforeEach(() => {
  vi.resetAllMocks(); setActivePinia(createPinia())
  vi.spyOn(ElMessage, 'warning').mockImplementation(() => ({ close: vi.fn() }))
  vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue('confirm' as never)
  useAuthStore().applyAuthResponse({ authenticated: true, user: { id: 1, username: 'admin', display_name: '管理员', is_superuser: true, employee: { id: 'admin', employee_code: 'ADMIN', display_name: '管理员', status: 'ACTIVE' }, permissions: [], data_scope: 'ALL' } })
  api.getWeComConfig.mockResolvedValue({ data: { corp_id: 'corp', agent_id: '1', erp_origin: 'https://erp.test', enabled: true, secret: '', callback_token: '', callback_aes_key: '', credential_read_errors: [], has_secret: true, has_callback_token: false, has_callback_aes_key: false, encryption_ready: true, configuration_complete: true, last_check_status: 'SUCCESS', last_check_message: '', last_checked_at: null, login_url: '', callback_url: '', trusted_domain: 'erp.test' }, etag: 'config-v1' })
  api.getWeComMessageTemplate.mockResolvedValue({ data: { ...template }, etag: 'template-v0' })
  api.saveWeComMessageTemplate.mockImplementation(async data => ({ data: { ...data, is_saved: true, updated_at: '2026-10-19T08:00:00Z' }, etag: 'template-v1' }))
  api.getWeComBindings.mockResolvedValue(page([{ ...binding }]))
  api.getWeComMessageAttempts.mockResolvedValue(page())
  api.sendWeComMessageTest.mockResolvedValue({ ...accepted })
})
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()); vi.restoreAllMocks() })

describe('企业微信消息模板', () => {
  it('未编辑的默认模板可关闭，隐藏页签中的修改仍通过父级确认', async () => {
    const wrapper = await renderMessages()
    const view = wrapper.getComponent(WeComSettingsView).vm
    expect(await view.canClose()).toBe(true)
    expect(ElMessageBox.confirm).not.toHaveBeenCalled()
    await wrapper.get('#wecom-message-body').setValue('保留我的模板修改')
    await button(wrapper, '接入配置').trigger('click')
    vi.mocked(ElMessageBox.confirm).mockRejectedValueOnce('cancel')
    expect(await view.canClose()).toBe(false)
    expect((wrapper.get('#wecom-message-body').element as HTMLTextAreaElement).value).toBe('保留我的模板修改')
    expect(await view.canClose()).toBe(true)
    expect(api.saveWeComMessageTemplate).not.toHaveBeenCalled()
  })
  it('仅打开页签才加载，默认模板未保存不能发送，唯一可用绑定自动选择', async () => {
    const wrapper = mount(WeComSettingsView); wrappers.push(wrapper); await flushPromises()
    expect(api.getWeComMessageTemplate).not.toHaveBeenCalled()
    await button(wrapper, '消息模板').trigger('click'); await flushPromises()
    expect((wrapper.get('#wecom-message-recipient').element as HTMLSelectElement).value).toBe('binding-a')
    expect(button(wrapper, '发送测试').attributes('disabled')).toBeDefined()
    expect(wrapper.get('.message-bubble').text()).toContain('员工甲')
    expect(wrapper.text()).toContain('暂无发送记录')
    expect(wrapper.text()).not.toContain('陈方煜')
  })
  it('保存携带模板版本并回填新版本，编辑后重新禁止发送', async () => {
    const wrapper = await renderMessages()
    await button(wrapper, '保存模板').trigger('click'); await flushPromises()
    expect(api.saveWeComMessageTemplate).toHaveBeenCalledWith({ name: template.name, body: template.body }, 'template-v0')
    expect(button(wrapper, '发送测试').attributes('disabled')).toBeUndefined()
    await wrapper.get('#wecom-message-body').setValue('新正文：{{消息内容}}')
    expect(button(wrapper, '发送测试').attributes('disabled')).toBeDefined()
    await button(wrapper, '保存模板').trigger('click'); await flushPromises()
    expect(api.saveWeComMessageTemplate.mock.calls[1]![1]).toBe('template-v1')
  })
  it('多个有效绑定不猜测收件人，并排除已停用员工', async () => {
    api.getWeComBindings.mockResolvedValueOnce(page([{ ...binding }, { ...binding, id: 'b', employee_name: '员工乙', role_status: 'waiting' }, { ...binding, id: 'c', employee_name: '停用员工', role_status: 'inactive' }]))
    const wrapper = await renderMessages()
    const select = wrapper.get('#wecom-message-recipient')
    expect((select.element as HTMLSelectElement).value).toBe('')
    expect(select.text()).toContain('员工乙')
    expect(select.text()).not.toContain('停用员工')
  })
  it('发送只携带绑定ID、内容、UUID及保存版本，并发点击不重复提交', async () => {
    let finish!: (value: typeof accepted) => void
    api.sendWeComMessageTest.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    const wrapper = await renderMessages()
    await button(wrapper, '保存模板').trigger('click'); await flushPromises()
    await wrapper.get('#wecom-message-content').setValue('仅通知测试')
    await button(wrapper, '发送测试').trigger('click')
    expect(await wrapper.getComponent(WeComSettingsView).vm.canClose()).toBe(false)
    expect(ElMessage.warning).toHaveBeenLastCalledWith('消息模板正在保存、发送或查询结果，请稍候再关闭。')
    expect(button(wrapper, '正在发送…').attributes('disabled')).toBeDefined()
    await button(wrapper, '正在发送…').trigger('click')
    expect(api.sendWeComMessageTest).toHaveBeenCalledTimes(1)
    expect(api.sendWeComMessageTest.mock.calls[0]).toEqual([{ binding_id: 'binding-a', message_content: '仅通知测试', idempotency_key: expect.stringMatching(/^[0-9a-f-]{36}$/i) }, 'template-v1'])
    finish(accepted); await flushPromises()
    expect(await wrapper.getComponent(WeComSettingsView).vm.canClose()).toBe(true)
    expect(wrapper.text()).toContain('企业微信已受理')
    expect(wrapper.text()).toContain('不等于送达')
  })
  it('网络未确认后按原UUID查询结果，不自动重发，未找到也不冒充失败', async () => {
    api.sendWeComMessageTest.mockRejectedValueOnce(new AxiosError('network'))
    const wrapper = await renderMessages()
    await button(wrapper, '保存模板').trigger('click'); await flushPromises()
    await button(wrapper, '发送测试').trigger('click'); await flushPromises()
    const key = api.sendWeComMessageTest.mock.calls[0]![0].idempotency_key
    expect(api.getWeComMessageAttempts).toHaveBeenLastCalledWith(expect.objectContaining({ idempotency_key: key }))
    expect(wrapper.text()).toContain('结果未确认')
    vi.mocked(ElMessageBox.confirm).mockRejectedValueOnce('cancel')
    expect(await wrapper.getComponent(WeComSettingsView).vm.canClose()).toBe(false)
    expect(button(wrapper, '发送测试').attributes('disabled')).toBeDefined()
    api.getWeComMessageAttempts.mockResolvedValueOnce(page([{ ...accepted, idempotency_key: key }]))
    await button(wrapper, '查询发送结果').trigger('click'); await flushPromises()
    expect(api.sendWeComMessageTest).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('企业微信已受理')
  })
  it('代理408仍按未知结果核对，同一待确认请求切换页签后保留', async () => {
    api.sendWeComMessageTest.mockRejectedValueOnce(new AxiosError('timeout', undefined, undefined, undefined, { status: 408 } as never))
    const wrapper = await renderMessages()
    await button(wrapper, '保存模板').trigger('click'); await flushPromises()
    await button(wrapper, '发送测试').trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('结果未确认')
    const key = api.sendWeComMessageTest.mock.calls[0]![0].idempotency_key
    await button(wrapper, '接入配置').trigger('click')
    await button(wrapper, '消息模板').trigger('click'); await flushPromises()
    expect(button(wrapper, '发送测试').attributes('disabled')).toBeDefined()
    await button(wrapper, '查询发送结果').trigger('click'); await flushPromises()
    expect(api.getWeComMessageAttempts).toHaveBeenLastCalledWith(expect.objectContaining({ idempotency_key: key }))
    expect(api.sendWeComMessageTest).toHaveBeenCalledTimes(1)
  })
  it('遍历绑定分页后才判断唯一收件人，不能只自动选第一页第一人', async () => {
    api.getWeComBindings.mockResolvedValueOnce({ data: [binding], count: 2, page: 1, page_size: 1 }).mockResolvedValueOnce({ data: [{ ...binding, id: 'binding-b', employee_name: '第二页员工' }], count: 2, page: 2, page_size: 1 })
    const wrapper = await renderMessages()
    expect(api.getWeComBindings).toHaveBeenLastCalledWith({ search: '', status: '', page: 2 })
    expect((wrapper.get('#wecom-message-recipient').element as HTMLSelectElement).value).toBe('')
    expect(wrapper.get('#wecom-message-recipient').text()).toContain('第二页员工')
  })
  it('上游结果未确认仍禁止新请求，记录不显示为成功', async () => {
    const uncertain = { ...accepted, status: 'UNCERTAIN', message: '上游响应丢失。' }
    api.sendWeComMessageTest.mockResolvedValueOnce(uncertain)
    const wrapper = await renderMessages()
    await button(wrapper, '保存模板').trigger('click'); await flushPromises()
    api.getWeComMessageAttempts.mockResolvedValueOnce(page([uncertain]))
    await button(wrapper, '发送测试').trigger('click'); await flushPromises()
    expect(wrapper.get('.attempt-status').text()).toBe('结果未确认')
    expect(button(wrapper, '发送测试').attributes('disabled')).toBeDefined()
    expect(wrapper.text()).not.toContain('企业微信已受理，不等于送达')
  })
  it('发送后重新读取服务端第一页与总数，不把新记录混入第二页', async () => {
    api.getWeComMessageAttempts.mockResolvedValueOnce({ data: [accepted], count: 21, page: 1, page_size: 20 })
    const wrapper = await renderMessages()
    api.getWeComMessageAttempts.mockResolvedValueOnce({ data: [{ ...accepted, id: 'old', recipient_name: '历史员工' }], count: 21, page: 2, page_size: 20 })
    await button(wrapper, '下一页').trigger('click'); await flushPromises()
    await button(wrapper, '保存模板').trigger('click'); await flushPromises()
    api.getWeComMessageAttempts.mockResolvedValueOnce({ data: [accepted], count: 22, page: 1, page_size: 20 })
    await button(wrapper, '发送测试').trigger('click'); await flushPromises()
    expect(api.getWeComMessageAttempts).toHaveBeenLastCalledWith({ page: 1, page_size: 20 })
    expect(wrapper.get('.record-pagination').text()).toContain('共 22 条')
    expect(wrapper.get('.record-pagination').text()).toContain('1 / 2')
    expect(wrapper.get('.message-records').text()).not.toContain('历史员工')
  })
  it('不支持安全UUID的浏览器明确提示，不向后端发送不可靠编号', async () => {
    const wrapper = await renderMessages()
    await button(wrapper, '保存模板').trigger('click'); await flushPromises()
    vi.stubGlobal('crypto', {})
    try {
      await button(wrapper, '发送测试').trigger('click'); await flushPromises()
      expect(api.sendWeComMessageTest).not.toHaveBeenCalled()
      expect(wrapper.text()).toContain('HTTPS')
    } finally { vi.unstubAllGlobals() }
  })
  it('卸载后迟到绑定分页不能继续查询或回填员工', async () => {
    let finish!: (value: ReturnType<typeof page>) => void
    api.getWeComBindings.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    const wrapper = await renderMessages()
    wrapper.unmount(); wrappers.splice(wrappers.indexOf(wrapper), 1)
    finish({ data: [binding], count: 2, page: 1, page_size: 1 }); await flushPromises()
    expect(api.getWeComBindings).toHaveBeenCalledTimes(1)
  })
  it('版本冲突保留编辑内容，重新加载前不能保存或发送', async () => {
    api.saveWeComMessageTemplate.mockRejectedValueOnce(new AxiosError('stale', undefined, undefined, undefined, { status: 412 } as never))
    const wrapper = await renderMessages()
    await wrapper.get('#wecom-message-body').setValue('保留我的修改')
    await button(wrapper, '保存模板').trigger('click'); await flushPromises()
    expect((wrapper.get('#wecom-message-body').element as HTMLTextAreaElement).value).toBe('保留我的修改')
    expect(button(wrapper, '保存模板').attributes('disabled')).toBeDefined()
    expect(button(wrapper, '发送测试').attributes('disabled')).toBeDefined()
    await button(wrapper, '重新加载模板').trigger('click'); await flushPromises()
    expect((wrapper.get('#wecom-message-body').element as HTMLTextAreaElement).value).toBe(template.body)
  })
  it('按替换后的UTF-8字节限制正文，未知变量不能保存', async () => {
    const wrapper = await renderMessages()
    await wrapper.get('#wecom-message-body').setValue('{{消息内容}}')
    await wrapper.get('#wecom-message-content').setValue('测'.repeat(683))
    expect(wrapper.get('.byte-count').text()).toContain('2049 / 2048')
    expect(button(wrapper, '发送测试').attributes('disabled')).toBeDefined()
    await wrapper.get('#wecom-message-body').setValue('{{未知字段}}')
    expect(button(wrapper, '保存模板').attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('不支持的变量')
  })
  it('记录加载失败不显示空态假象，并允许单独重试', async () => {
    api.getWeComMessageAttempts.mockRejectedValueOnce(new Error('network'))
    const wrapper = await renderMessages()
    expect(wrapper.text()).toContain('无法读取发送记录')
    expect(wrapper.text()).not.toContain('暂无发送记录')
    await button(wrapper, '刷新记录').trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('暂无发送记录')
  })
  it('普通员工不可加载模板及收件人接口', async () => {
    useAuthStore().user!.is_superuser = false
    const wrapper = mount(WeComSettingsView); wrappers.push(wrapper); await flushPromises()
    expect(wrapper.text()).toContain('无企业微信管理权限')
    expect(api.getWeComMessageTemplate).not.toHaveBeenCalled()
    expect(api.getWeComBindings).not.toHaveBeenCalled()
  })
  it('三页签支持左右键和Home/End键，消息API只加载一次', async () => {
    const wrapper = mount(WeComSettingsView); wrappers.push(wrapper); await flushPromises()
    await wrapper.get('.tabs').trigger('keydown', { key: 'End' }); await flushPromises()
    expect(wrapper.get('#wecom-tab-messages').attributes('aria-selected')).toBe('true')
    await wrapper.get('.tabs').trigger('keydown', { key: 'ArrowRight' })
    expect(wrapper.get('#wecom-tab-config').attributes('aria-selected')).toBe('true')
    await wrapper.get('.tabs').trigger('keydown', { key: 'ArrowLeft' }); await flushPromises()
    expect(wrapper.get('#wecom-tab-messages').attributes('aria-selected')).toBe('true')
    expect(api.getWeComMessageTemplate).toHaveBeenCalledTimes(1)
  })
})
