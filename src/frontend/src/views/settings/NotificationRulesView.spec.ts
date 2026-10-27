import { ElOption, ElSelect } from 'element-plus'
import { DOMWrapper, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { AxiosError } from 'axios'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import NotificationRulesView from './NotificationRulesView.vue'
import { useAuthStore } from '@/stores/auth'
import type { NotificationPreview, NotificationRule, NotificationRulesResponse } from '@/types/notifications'

const api = vi.hoisted(() => ({ getNotificationRules: vi.fn(), saveNotificationRule: vi.fn(), previewNotificationRule: vi.fn(), getNotificationPreviewRecipients: vi.fn(), sendNotificationPreview: vi.fn(), getNotificationPreviewAttempt: vi.fn() }))
vi.mock('@/api/notifications', async original => ({ ...await original<object>(), ...api }))
const rule: NotificationRule = {
  event_code: 'PRODUCTION_TASK_CONFIRMED', display_name: '生产任务确认', name: '任务通知',
  title_template: '生产任务', body_template: '{{document_no}} 已由 {{operator}} 于 {{occurred_at}} 确认。',
  default_body_template: '任务单号：{{document_no}}\n操作人：{{operator}}\n确认时间：{{occurred_at}}',
  allowed_variables: ['document_no', 'operator', 'occurred_at'], required_variables: ['document_no', 'operator', 'occurred_at'],
  variable_definitions: [{ name: 'document_no', label: '单据编号', example: '示例单号' }, { name: 'operator', label: '操作人', example: '示例操作人' }, { name: 'occurred_at', label: '操作时间', example: '示例时间' }],
  supported_scopes: ['ROLE_MEMBERS'], scope_labels: { ROLE_MEMBERS: '所选角色的合法成员' },
  recipient_role_codes: ['TECHNICAL'], recipient_roles: [{ role_code: 'TECHNICAL', display_name: '技术', archived: false }],
  recipient_scope: 'ROLE_MEMBERS', enabled: true, version: 0, updated_at: null, updated_by: '', etag: 'server-v0', target_key: 'production-task-detail',
}
const sample: NotificationPreview = { event_code: rule.event_code, title: '生产任务示例', body: '示例单号已确认', recipient_scope: 'ROLE_MEMBERS', scope_label: '所选角色的合法成员', recipient_role_codes: ['TECHNICAL'], will_send: false, preview_token: 'signed-preview', preview_id: 'preview-1', expires_at: '2099-01-01T00:00:00Z' }
function cardSample(): NotificationPreview {
  return { ...sample, expires_at: new Date(Date.now() + 600000).toISOString(), message_type: 'template_card', template_card: {
    card_type: 'text_notice', source: { desc: 'HAIQU ERP · 测试' },
    main_title: { title: '【生产任务】确认通知', desc: '预览试发 · 示例内容' },
    sub_title_text: '任务单号：示例单号\n操作人：示例操作人\n确认时间：示例时间',
    jump_list: [{ type: 1, title: '查看详情', url: 'https://erp.example.test/' }],
    card_action: { type: 1, url: 'https://erp.example.test/' },
  } }
}
const wrappers: ReturnType<typeof mount>[] = []
function result(): NotificationRulesResponse { return { data: [{ ...rule }], roles: [...rule.recipient_roles] } }
function button(label: string) { return new DOMWrapper(Array.from(document.querySelectorAll('button')).find(item => item.textContent?.trim() === label)!) }
function input(selector: string) { return new DOMWrapper(document.querySelector(selector)!) }
async function render() { const wrapper = mount(NotificationRulesView, { attachTo: document.body }); wrappers.push(wrapper); await flushPromises(); return wrapper }
async function edit() { const wrapper = await render(); await button('编辑').trigger('click'); await flushPromises(); return wrapper }

beforeEach(() => {
  vi.resetAllMocks(); setActivePinia(createPinia())
  useAuthStore().applyAuthResponse({ authenticated: true, user: { id: 1, username: 'admin', display_name: '管理员', is_superuser: true, employee: { id: 'admin', employee_code: 'ADMIN', display_name: '管理员', status: 'ACTIVE' }, permissions: [], data_scope: 'ALL' } })
  api.getNotificationRules.mockImplementation(async () => result())
  api.previewNotificationRule.mockResolvedValue({ ...sample, expires_at: new Date(Date.now() + 600000).toISOString() })
  api.getNotificationPreviewRecipients.mockResolvedValue({ data: [{ binding_id: 'binding-1', employee_code: 'E1', employee_name: '已绑定员工' }], count: 1, page: 1, page_size: 50, available: true, schema_ready: true, config_etag: 'config-v1', message: '' })
  api.sendNotificationPreview.mockResolvedValue({ id: 'attempt-1', preview_id: 'preview-1', status: 'ACCEPTED', recipient_name: '已绑定员工', message: '企业微信已受理，不代表员工已读。' })
  api.saveNotificationRule.mockImplementation(async (_code, data) => ({ data: { ...rule, ...data, version: 1, etag: 'server-v1' }, etag: 'server-v1' }))
})
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()); document.body.innerHTML = ''; vi.restoreAllMocks() })

describe('通知规则页面', () => {
  it('列表只显示业务环节和模板名称，不显示事件编码与标题模板副本', async () => {
    const hiddenRule = { ...rule, event_code: 'EVENT_CODE_SHOULD_BE_HIDDEN', title_template: '标题模板副本不应显示' }
    api.getNotificationRules.mockResolvedValue({ data: [hiddenRule], roles: rule.recipient_roles })
    const wrapper = await render()
    const table = wrapper.find('.rules-table')
    expect(table.text()).toContain(hiddenRule.display_name)
    expect(table.text()).toContain(hiddenRule.name)
    expect(table.text()).not.toContain(hiddenRule.event_code)
    expect(table.text()).not.toContain(hiddenRule.title_template)
  })

  it('接收角色只显示角色名称，不显示角色描述提示', async () => {
    const warningRule = { ...rule, warnings: ['角色描述不应显示'] }
    api.getNotificationRules.mockResolvedValue({ data: [warningRule], roles: rule.recipient_roles })
    const wrapper = await render()
    const table = wrapper.find('.rules-table')
    expect(table.text()).toContain('技术')
    expect(table.text()).not.toContain('角色描述不应显示')
  })

  it('接收角色选择器只显示角色名称，保留角色编码作为值', async () => {
    const wrapper = await edit()
    const roleSelect = wrapper.findAllComponents(ElSelect).at(0)!
    expect(roleSelect.findAllComponents(ElOption).map(option => [option.props('label'), option.props('value')])).toEqual([
      ['技术', 'TECHNICAL'],
    ])
  })

  it('通知规则按侧边栏菜单顺序分组', async () => {
    const procurementRule = { ...rule, event_code: 'PURCHASE_ORDER_COMPLETED', display_name: '采购手动完结', name: '采购通知', title_template: '采购标题' }
    const warehouseRules = [
      { ...rule, event_code: 'MATERIAL_RECEIPT_RECORDED', display_name: '材料到货登记', name: '仓库到货通知', title_template: '仓库到货标题' },
      { ...rule, event_code: 'MATERIAL_INSPECTION_CONFIRMED', display_name: '材料质检确认', name: '仓库质检通知', title_template: '仓库质检标题' },
      { ...rule, event_code: 'MATERIAL_ISSUE_SUBMITTED', display_name: '生产领料提交', name: '仓库领料通知', title_template: '仓库领料标题' },
    ]
    const sampleRule = { ...rule, event_code: 'SAMPLE_SUBMITTED', display_name: '打样申请提交', name: '样品通知', title_template: '样品标题' }
    api.getNotificationRules.mockResolvedValue({ data: [procurementRule, rule, sampleRule, ...warehouseRules], roles: rule.recipient_roles })
    const wrapper = await render()
    const tabs = wrapper.find('.notification-rule-tabs')
    expect(tabs.exists()).toBe(true)
    expect(tabs.findAll('[role="tab"]').map(tab => tab.text())).toEqual(['样品', '生产', '采购', '仓库'])
    expect(tabs.find('[data-notification-group="sample-management"] .rules-table').text()).toContain(sampleRule.display_name)
    expect(tabs.find('[data-notification-group="production-management"] .rules-table').text()).toContain(rule.display_name)
    expect(tabs.find('[data-notification-group="procurement-management"] .rules-table').text()).toContain(procurementRule.display_name)
    const warehouseTable = tabs.find('[data-notification-group="warehouse-management"] .rules-table').text()
    for (const warehouseRule of warehouseRules) expect(warehouseTable).toContain(warehouseRule.display_name)
    await tabs.findAll('[role="tab"]').find(tab => tab.text() === '采购')!.trigger('click')
    await flushPromises()
    expect(tabs.find('[data-notification-group="procurement-management"] .rules-table').isVisible()).toBe(true)
  })

  it('嵌入配置窗口时保留通知编辑及发送中的窗口，完成并取消后允许关闭', async () => {
    let finish!: (value: unknown) => void
    api.sendNotificationPreview.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    const wrapper = await edit()
    await input('#notification-title').setValue('未保存的通知标题')
    expect(wrapper.vm.canClose()).toBe(false)
    expect((input('#notification-title').element as HTMLInputElement).value).toBe('未保存的通知标题')
    await button('生成预览').trigger('click'); await flushPromises()
    wrapper.findAllComponents(ElSelect).at(-1)!.vm.$emit('update:modelValue', 'binding-1'); await flushPromises()
    await button('发送预览').trigger('click')
    expect(wrapper.vm.canClose()).toBe(false)
    expect(button('取消').attributes('disabled')).toBeDefined()
    expect(button('套用默认卡片正文').attributes('disabled')).toBeDefined()
    finish({ id: 'attempt-1', preview_id: 'preview-1', status: 'ACCEPTED', recipient_name: '已绑定员工', message: '已受理' })
    await flushPromises()
    await button('取消').trigger('click'); await flushPromises()
    expect(wrapper.vm.canClose()).toBe(true)
    expect(api.saveNotificationRule).not.toHaveBeenCalled()
  })

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
    await button('编辑').trigger('click'); await flushPromises()
    await button('保存').trigger('click'); await flushPromises()
    expect(api.saveNotificationRule.mock.calls[1]![2]).toBe('server-v1')
  })

  it('预览使用当前未保存内容及允许变量，修改后清除旧预览', async () => {
    await edit()
    await input('#notification-title').setValue('新标题')
    await button('生成预览').trigger('click'); await flushPromises()
    expect(api.previewNotificationRule).toHaveBeenCalledWith(rule.event_code, expect.objectContaining({ title_template: '新标题', variables: { document_no: '示例单号', operator: '示例操作人', occurred_at: '示例时间' } }), 'server-v0')
    expect(document.querySelector('.preview-message')?.textContent).toContain('示例单号已确认')
    await input('#notification-title').setValue('再次修改')
    expect(document.querySelector('.preview-message')).toBeNull()
    expect(api.saveNotificationRule).not.toHaveBeenCalled()
  })

  it.each(['PRODUCTION_TASK_CONFIRMED', 'BOM_CONFIRMED', 'SAMPLE_SUBMITTED', 'SERVER_REGISTERED_EVENT'])('所有事件均按服务端默认正文套用，保留其他配置：%s', async eventCode => {
    const disabledRule = { ...rule, event_code: eventCode, enabled: false, recipient_role_codes: [], default_body_template: `单据编号：{{document_no}}\n操作人：{{operator}}\n操作时间：{{occurred_at}}\n业务备注：${eventCode}` }
    api.getNotificationRules.mockResolvedValue({ data: [disabledRule], roles: rule.recipient_roles })
    api.previewNotificationRule.mockResolvedValue({ ...cardSample(), event_code: eventCode })
    await edit()
    await button('生成预览').trigger('click'); await flushPromises()
    expect(document.querySelector('.template-card')).not.toBeNull()
    await button('套用默认卡片正文').trigger('click'); await flushPromises()
    expect((input('#notification-name').element as HTMLInputElement).value).toBe(disabledRule.name)
    expect((input('#notification-title').element as HTMLInputElement).value).toBe(disabledRule.title_template)
    expect((input('#notification-body').element as HTMLTextAreaElement).value).toBe(disabledRule.default_body_template)
    expect(document.querySelector('.preview-message')).toBeNull()
    expect(api.saveNotificationRule).not.toHaveBeenCalled()
    expect(api.sendNotificationPreview).not.toHaveBeenCalled()
    await button('生成预览').trigger('click'); await flushPromises()
    expect(api.previewNotificationRule).toHaveBeenLastCalledWith(eventCode, expect.objectContaining({
      name: disabledRule.name, title_template: disabledRule.title_template,
      body_template: disabledRule.default_body_template,
      recipient_role_codes: [], recipient_scope: disabledRule.recipient_scope, enabled: false,
    }), 'server-v0')
  })

  it('卡片使用服务端预览字段展示，页面预览入口不导航且由用户手动试发', async () => {
    const card = cardSample()
    api.previewNotificationRule.mockResolvedValue(card)
    const wrapper = await edit()
    await button('套用默认卡片正文').trigger('click')
    await button('生成预览').trigger('click'); await flushPromises()
    const rendered = document.querySelector('.template-card')!
    expect(rendered.textContent).toContain(card.template_card!.source.desc)
    expect(rendered.textContent).toContain(card.template_card!.main_title.title)
    expect(rendered.textContent).toContain(card.template_card!.main_title.desc)
    expect(rendered.textContent).toContain(card.template_card!.sub_title_text)
    expect(Array.from(rendered.querySelectorAll('p')).at(-1)?.textContent?.split('\n')).toEqual(['任务单号：示例单号', '操作人：示例操作人', '确认时间：示例时间'])
    expect(rendered.querySelector('.template-card-footer')?.textContent).toContain('查看详情')
    expect(rendered.querySelector('a, button')).toBeNull()
    expect(document.body.textContent).toContain('没有真实单据详情')
    expect(document.body.textContent).toContain('“查看详情”进入ERP首页')
    expect(api.sendNotificationPreview).not.toHaveBeenCalled()
    wrapper.findAllComponents(ElSelect).at(-1)!.vm.$emit('update:modelValue', 'binding-1'); await flushPromises()
    expect(button('发送预览').attributes('disabled')).toBeUndefined()
    await button('发送预览').trigger('click'); await flushPromises()
    expect(api.sendNotificationPreview).toHaveBeenCalledOnce()
    expect(api.sendNotificationPreview).toHaveBeenCalledWith(rule.event_code, expect.objectContaining({
      preview_token: 'signed-preview', binding_id: 'binding-1', draft: expect.objectContaining({ name: rule.name, body_template: rule.default_body_template }),
    }))
  })

  it.each([
    ['模板卡片正文超出长度限制，请缩短后重新预览。', true],
    ['企业微信应用未配置，暂不能试发。', false],
  ])('显示发送阻断原因并禁用试发：%s', async (reason, hasCard) => {
    api.previewNotificationRule.mockResolvedValue({ ...cardSample(), template_card: hasCard ? cardSample().template_card : undefined, send_blocked_reason: reason })
    const wrapper = await edit()
    await button('生成预览').trigger('click'); await flushPromises()
    wrapper.findAllComponents(ElSelect).at(-1)!.vm.$emit('update:modelValue', 'binding-1'); await flushPromises()
    expect(document.body.textContent).toContain(reason)
    expect(button('发送预览').attributes('disabled')).toBeDefined()
    await button('发送预览').trigger('click')
    expect(api.sendNotificationPreview).not.toHaveBeenCalled()
    await input('#notification-title').setValue('修改后重新生成')
    expect(document.body.textContent).not.toContain(reason)
    expect(button('发送预览').attributes('disabled')).toBeDefined()
    api.previewNotificationRule.mockResolvedValue(cardSample())
    await button('生成预览').trigger('click'); await flushPromises()
    expect(button('发送预览').attributes('disabled')).toBeUndefined()
  })

  it('同名员工只显示姓名，按绑定标识选择接收人', async () => {
    api.getNotificationPreviewRecipients.mockResolvedValue({ data: [
      { binding_id: 'binding-1', employee_code: 'E1', employee_name: '同名员工' },
      { binding_id: 'binding-2', employee_code: 'E2', employee_name: '同名员工' },
    ], count: 2, page: 1, page_size: 50, available: true, schema_ready: true, config_etag: 'config-v1', message: '' })
    const wrapper = await edit()
    const recipientSelect = wrapper.findAllComponents(ElSelect).at(-1)!
    expect(recipientSelect.props('placeholder')).toBe('选择或搜索员工姓名')
    expect(recipientSelect.findAllComponents(ElOption).map(option => [option.props('label'), option.props('value')])).toEqual([
      ['同名员工', 'binding-1'], ['同名员工', 'binding-2'],
    ])
    await button('生成预览').trigger('click'); await flushPromises()
    recipientSelect.vm.$emit('update:modelValue', 'binding-2'); await flushPromises()
    await button('发送预览').trigger('click'); await flushPromises()
    expect(api.sendNotificationPreview).toHaveBeenCalledWith(rule.event_code, expect.objectContaining({ binding_id: 'binding-2' }))
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
  it('中文名称与变量在右侧分组，生成后消息位于变量下面', async () => {
    await edit()
    const right = document.querySelector('.preview')!
    expect(right.querySelector('[aria-label="必要变量"]')?.textContent).toContain('单据编号')
    expect(right.querySelector('[aria-label="必要变量"]')?.textContent).toContain('{{document_no}}')
    expect(document.querySelector('.editor')?.textContent).not.toContain('可用变量：')
    expect(right.querySelector('.preview-message')).toBeNull()
    await button('生成预览').trigger('click'); await flushPromises()
    expect(right.querySelector('.variable-group')!.compareDocumentPosition(right.querySelector('.preview-message')!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it('手选一个绑定人后只发送当前预览凭证，重复点击不重发', async () => {
    const wrapper = await edit()
    expect(button('发送预览').attributes('disabled')).toBeDefined()
    await button('生成预览').trigger('click'); await flushPromises()
    wrapper.findAllComponents(ElSelect).at(-1)!.vm.$emit('update:modelValue', 'binding-1')
    await flushPromises()
    await button('发送预览').trigger('click'); await flushPromises()
    expect(api.sendNotificationPreview).toHaveBeenCalledWith(rule.event_code, expect.objectContaining({ preview_token: 'signed-preview', binding_id: 'binding-1', config_etag: 'config-v1', draft: expect.objectContaining({ title_template: rule.title_template }) }))
    expect(document.body.textContent).toContain('不代表员工已读')
    await button('发送预览').trigger('click')
    expect(api.sendNotificationPreview).toHaveBeenCalledTimes(1)
  })

  it('试发表未就绪不影响原来的编辑与生成预览', async () => {
    api.getNotificationPreviewRecipients.mockResolvedValue({ data: [], count: 0, page: 1, page_size: 50, available: false, schema_ready: false, config_etag: '', message: '预览试发尚未启用' })
    await edit()
    await button('生成预览').trigger('click'); await flushPromises()
    expect(document.querySelector('.preview-message')).not.toBeNull()
    expect(document.body.textContent).toContain('尚未启用')
    expect(button('发送预览').attributes('disabled')).toBeDefined()
    expect(button('保存').attributes('disabled')).toBeUndefined()
  })

  it('发送超时只查询原尝试，不自动发送或重新生成凭证', async () => {
    api.sendNotificationPreview.mockRejectedValue(new Error('timeout'))
    api.getNotificationPreviewAttempt.mockResolvedValue({ id: 'attempt-1', preview_id: 'preview-1', status: 'UNCERTAIN', recipient_name: '已绑定员工', message: '结果待核对' })
    const wrapper = await edit()
    await button('生成预览').trigger('click'); await flushPromises()
    wrapper.findAllComponents(ElSelect).at(-1)!.vm.$emit('update:modelValue', 'binding-1'); await flushPromises()
    await button('发送预览').trigger('click'); await flushPromises()
    expect(button('生成预览').attributes('disabled')).toBeDefined()
    expect(button('套用默认卡片正文').attributes('disabled')).toBeDefined()
    await button('查询本次结果').trigger('click'); await flushPromises()
    expect(api.getNotificationPreviewAttempt).toHaveBeenCalledWith('preview-1')
    expect(api.sendNotificationPreview).toHaveBeenCalledTimes(1)
  })

  it('只有试发权限被服务端拒绝时保留规则编辑器', async () => {
    api.getNotificationPreviewRecipients.mockRejectedValue(new AxiosError('forbidden', undefined, undefined, undefined, { status: 403 } as never))
    await edit()
    expect(document.querySelector('#notification-name')).not.toBeNull()
    expect(document.body.textContent).toContain('两项管理权限')
    await button('生成预览').trigger('click'); await flushPromises()
    expect(document.querySelector('.preview-message')).not.toBeNull()
  })

  it('预览A的迟到查询不得填入预览B', async () => {
    let finish!: (value: unknown) => void
    api.getNotificationPreviewAttempt.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    const wrapper = await edit()
    await button('生成预览').trigger('click'); await flushPromises()
    wrapper.findAllComponents(ElSelect).at(-1)!.vm.$emit('update:modelValue', 'binding-1'); await flushPromises()
    await button('发送预览').trigger('click'); await flushPromises()
    await button('查询本次结果').trigger('click')
    api.previewNotificationRule.mockResolvedValue({ ...sample, title: '新预览B', preview_id: 'preview-2', preview_token: 'token-2', expires_at: new Date(Date.now() + 600000).toISOString() })
    await button('生成预览').trigger('click'); await flushPromises()
    finish({ id: 'attempt-1', preview_id: 'preview-1', status: 'UNCERTAIN', recipient_name: '旧接收人A', message: '旧结果' })
    await flushPromises()
    expect(document.querySelector('.preview-message')?.textContent).toContain('新预览B')
    expect(document.body.textContent).not.toContain('旧接收人A')
    expect(document.body.textContent).not.toContain('旧结果')
  })

  it('超级管理员身份撤销再恢复仍丢弃旧发送和查询响应', async () => {
    const auth = useAuthStore()
    const grant = { scopes: ['MODULE' as const], sources: [{ type: 'ROLE', scope: 'MODULE' as const }] }
    auth.user!.effective_access = { active: true, is_superuser: false, roles: [], actions: { 'access_control.manage_notifications': grant, 'access_control.manage_wecom': grant }, legacy_sources: [], version: 'test' }
    auth.user!.is_superuser = true
    let finishSend!: (value: unknown) => void
    api.sendNotificationPreview.mockImplementationOnce(() => new Promise(resolve => { finishSend = resolve }))
    const wrapper = await edit()
    await button('生成预览').trigger('click'); await flushPromises()
    wrapper.findAllComponents(ElSelect).at(-1)!.vm.$emit('update:modelValue', 'binding-1'); await flushPromises()
    await button('发送预览').trigger('click')
    auth.user!.is_superuser = false; await flushPromises()
    expect(document.querySelector('#notification-name')).not.toBeNull()
    auth.user!.is_superuser = true; await flushPromises()
    finishSend({ id: 'old', preview_id: 'preview-1', status: 'ACCEPTED', recipient_name: '撤权前接收人', message: '旧发送结果' }); await flushPromises()
    expect(document.body.textContent).not.toContain('撤权前接收人')
    expect(document.body.textContent).not.toContain('旧发送结果')
    await button('生成预览').trigger('click'); await flushPromises()
    wrapper.findAllComponents(ElSelect).at(-1)!.vm.$emit('update:modelValue', 'binding-1'); await flushPromises()
    await button('发送预览').trigger('click'); await flushPromises()
    let finishQuery!: (value: unknown) => void
    api.getNotificationPreviewAttempt.mockImplementationOnce(() => new Promise(resolve => { finishQuery = resolve }))
    await button('查询本次结果').trigger('click')
    auth.user!.is_superuser = false; await flushPromises()
    expect(document.body.textContent).not.toContain('企业微信已受理')
    auth.user!.is_superuser = true; await flushPromises()
    finishQuery({ id: 'old', preview_id: 'preview-1', status: 'UNCERTAIN', recipient_name: '旧查询接收人', message: '旧查询结果' }); await flushPromises()
    expect(document.body.textContent).not.toContain('旧查询接收人')
    expect(document.body.textContent).not.toContain('旧查询结果')
  })

})
