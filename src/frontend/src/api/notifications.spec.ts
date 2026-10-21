import { AxiosError } from 'axios'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { getNotificationRules, notificationError, previewNotificationRule, saveNotificationRule } from './notifications'
import type { NotificationRuleWrite } from '@/types/notifications'

const client = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), patch: vi.fn() }))
vi.mock('./request', () => ({ apiClient: client }))
const payload: NotificationRuleWrite = { name: '模板', title_template: '标题', body_template: '{{document_no}}', recipient_role_codes: ['TECHNICAL'], recipient_scope: 'ROLE_MEMBERS', enabled: true }
beforeEach(() => vi.resetAllMocks())

describe('通知规则 API 契约', () => {
  it('列表保持服务端版本，保存携带 If-Match 并读取新版本', async () => {
    const data = { data: [{ etag: 'server-v0' }], roles: [] }
    client.get.mockResolvedValueOnce({ data })
    expect(await getNotificationRules()).toEqual(data)
    client.patch.mockResolvedValueOnce({ data: { data: payload }, headers: { etag: 'server-v1' } })
    expect(await saveNotificationRule('EVENT', payload, 'server-v0')).toEqual({ data: payload, etag: 'server-v1' })
    expect(client.patch).toHaveBeenCalledWith('/api/v1/notifications/rules/EVENT/', payload, { timeout: 20000, headers: { 'If-Match': 'server-v0' } })
  })

  it('缺失请求版本不发起保存；缺失响应版本不返回假成功', async () => {
    await expect(saveNotificationRule('EVENT', payload, '')).rejects.toThrow('版本缺失')
    expect(client.patch).not.toHaveBeenCalled()
    client.patch.mockResolvedValueOnce({ data: { data: payload }, headers: {} })
    await expect(saveNotificationRule('EVENT', payload, 'v1')).rejects.toThrow('核实保存结果')
  })

  it('预览提交当前表单和示例变量，不调用保存接口', async () => {
    const preview = { title: '示例', will_send: false }
    client.post.mockResolvedValueOnce({ data: { data: preview } })
    const data = { ...payload, variables: { document_no: '示例单号' } }
    expect(await previewNotificationRule('EVENT', data)).toEqual(preview)
    expect(client.post).toHaveBeenCalledWith('/api/v1/notifications/rules/EVENT/preview/', data, { timeout: 20000 })
    expect(client.patch).not.toHaveBeenCalled()
  })

  it('显示结构化字段错误，不暴露未知服务端异常内容', () => {
    const error = new AxiosError('validation', undefined, undefined, undefined, { status: 400, data: { error: { code: 'VALIDATION_ERROR', message: '参数校验失败', field_errors: { recipient_role_codes: ['该角色已停用'], internal: ['内部数据'] } } } } as never)
    expect(notificationError(error, '失败')).toBe('参数校验失败；接收角色：该角色已停用')
    const serverError = new AxiosError('server', undefined, undefined, undefined, { status: 500, data: { error: { code: 'VALIDATION_ERROR', message: '内部堆栈' } } } as never)
    expect(notificationError(serverError, '服务暂不可用')).toBe('服务暂不可用')
  })
})
