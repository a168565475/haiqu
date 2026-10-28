import { apiClient } from './request'
import { isAxiosError } from 'axios'
import type { NotificationInboxResponse, NotificationItem, NotificationTarget, NotificationPreview, NotificationRule, NotificationRuleResponse, NotificationRuleWrite, NotificationRulesResponse } from '@/types/notifications'
import type { NotificationPreviewRecipients, NotificationPreviewSend, NotificationPreviewAttempt } from '@/types/notifications'
import type { NotificationSendRecord, NotificationSendRecordQuery, NotificationSendRecordsResponse } from '@/types/notifications'

const root = '/api/v1/notifications/'
const ruleRoot = `${root}rules/`
const options = (etag?: string) => ({ timeout: 20000, ...(etag ? { headers: { 'If-Match': etag } } : {}) })

export async function getNotificationRules(): Promise<NotificationRulesResponse> {
  return (await apiClient.get<NotificationRulesResponse>(ruleRoot, options())).data
}

export async function saveNotificationRule(eventCode: string, data: NotificationRuleWrite, etag: string): Promise<NotificationRuleResponse> {
  if (!etag) throw new Error('通知规则版本缺失，请重新加载。')
  const response = await apiClient.patch<{ data: NotificationRule }>(`${ruleRoot}${encodeURIComponent(eventCode)}/`, data, options(etag))
  const next = response.headers.etag
  if (typeof next !== 'string' || !next) throw new Error('服务器未返回规则版本，请重新加载核实保存结果。')
  return { data: response.data.data, etag: next }
}

export async function previewNotificationRule(eventCode: string, data: NotificationRuleWrite & { variables: Record<string, string> }, etag?: string): Promise<NotificationPreview> {
  return (await apiClient.post<{ data: NotificationPreview }>(`${ruleRoot}${encodeURIComponent(eventCode)}/preview/`, data, options(etag))).data.data
}

export async function getNotificationPreviewRecipients(search = '', page = 1): Promise<NotificationPreviewRecipients> {
  return (await apiClient.get<NotificationPreviewRecipients>(`${root}preview-recipients/`, { ...options(), params: { search, page } })).data
}

export async function sendNotificationPreview(eventCode: string, data: NotificationPreviewSend): Promise<NotificationPreviewAttempt> {
  return (await apiClient.post<{ data: NotificationPreviewAttempt }>(`${ruleRoot}${encodeURIComponent(eventCode)}/preview-send/`, data, options())).data.data
}

export async function getNotificationPreviewAttempt(previewId: string): Promise<NotificationPreviewAttempt> {
  return (await apiClient.get<{ data: NotificationPreviewAttempt }>(`${root}preview-attempts/${encodeURIComponent(previewId)}/`, options())).data.data
}

export function notificationPreviewError(error: unknown, fallback: string): string {
  if (isAxiosError(error) && error.response?.status === 403) return '试发需要通知规则和企业微信两项管理权限。'
  if (isAxiosError(error) && error.response?.status === 412) return '规则或企业微信配置已变化，请刷新后重新预览。'
  return notificationError(error, fallback)
}

const fieldLabels: Record<string, string> = {
  name: '模板名称', title_template: '标题', body_template: '正文', recipient_role_codes: '接收角色',
  recipient_scope: '接收范围', enabled: '启用状态', variables: '示例变量', non_field_errors: '提交内容',
  preview_token: '预览凭证', binding_id: '接收员工', config_etag: '应用配置版本', draft: '当前草稿',
}
const knownErrorCodes = new Set(['VALIDATION_ERROR', 'AUTHENTICATION_REQUIRED', 'PERMISSION_DENIED', 'NOT_FOUND', 'CONFLICT', 'PRECONDITION_FAILED', 'PRECONDITION_REQUIRED', 'WECOM_UNAVAILABLE'])

export function notificationError(error: unknown, fallback: string): string {
  if (!isAxiosError(error)) return fallback
  if (error.response?.status === 412) return '通知规则已被其他管理员修改，请关闭弹窗并刷新后核对。'
  if (error.response?.status === 403) return '当前账号无通知规则管理权限。'
  if (error.response?.status === 401) return '登录状态已失效，请重新登录。'
  const detail = error.response?.data?.error
  // 只展示项目约定的业务错误，避免显示代理错误页或内部异常信息。
  if (!error.response || error.response.status >= 500 || !knownErrorCodes.has(detail?.code) || typeof detail?.message !== 'string') return fallback
  const messages = [detail.message]
  if (detail.field_errors && typeof detail.field_errors === 'object') {
    for (const [field, value] of Object.entries(detail.field_errors)) {
      if (!Object.hasOwn(fieldLabels, field)) continue
      const values = (Array.isArray(value) ? value : [value]).filter((item): item is string => typeof item === 'string')
      if (values.length) messages.push(`${fieldLabels[field]}：${values.join('；')}`)
    }
  }
  return messages.join('；') || fallback
}

export async function getNotificationInbox(page = 1, signal?: AbortSignal): Promise<NotificationInboxResponse> {
  if (!Number.isSafeInteger(page) || page < 1) throw new Error('消息页码无效')
  const { data } = await apiClient.get<NotificationInboxResponse>(`${root}inbox/`, { ...options(), params: { page, page_size: 10 }, signal })
  if (!data || !Array.isArray(data.data) || !Number.isSafeInteger(data.count) || data.count < 0
    || !Number.isSafeInteger(data.page) || data.page < 1 || !Number.isSafeInteger(data.page_size) || data.page_size < 1 || data.page_size > 50) {
    throw new Error('消息列表响应无效')
  }
  return data
}

export async function getNotificationUnreadCount(signal?: AbortSignal): Promise<number> {
  const response = await apiClient.get<{ unread_count: number }>(`${root}inbox/unread-count/`, { ...options(), signal })
  if (!Number.isSafeInteger(response.data.unread_count) || response.data.unread_count < 0) throw new Error('未读数响应无效')
  return response.data.unread_count
}

export async function markNotificationRead(recipientId: string, signal?: AbortSignal): Promise<NotificationItem> {
  return (await apiClient.post<{ data: NotificationItem }>(`${root}inbox/${encodeURIComponent(recipientId)}/read/`, undefined, { ...options(), signal })).data.data
}

export async function getNotificationTarget(recipientId: string, signal?: AbortSignal): Promise<NotificationTarget> {
  return (await apiClient.get<{ data: { target: NotificationTarget } }>(`${root}inbox/${encodeURIComponent(recipientId)}/target/`, { ...options(), signal })).data.data.target
}

export async function getNotificationDetail(recipientId: string, signal?: AbortSignal): Promise<NotificationItem> {
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(recipientId)) throw new Error('消息编号无效')
  return (await apiClient.get<{ data: NotificationItem }>(`${root}inbox/${encodeURIComponent(recipientId)}/`, { ...options(), signal })).data.data
}

export function notificationInboxError(error: unknown, fallback: string): string {
  if (!isAxiosError(error)) return fallback
  if (error.response?.status === 401) return '登录状态已失效，请重新登录后查看消息。'
  if (error.response?.status === 403) return '当前身份无法访问消息，请检查员工状态或重新登录。'
  if (error.response?.status === 404) return '该消息或业务对象已删除，或当前已无访问权限。'
  return fallback
}

const recordSources = new Set(['BUSINESS', 'RULE_PREVIEW', 'MESSAGE_TEST'])
const recordStatuses = new Set(['PENDING', 'PROCESSING', 'ACCEPTED', 'FAILED', 'UNCERTAIN', 'SKIPPED'])

export async function getNotificationSendRecords(params: NotificationSendRecordQuery, signal?: AbortSignal): Promise<NotificationSendRecordsResponse> {
  if (!recordSources.has(params.source) || !Number.isSafeInteger(params.page) || params.page < 1
    || !Number.isSafeInteger(params.page_size) || params.page_size < 1 || params.page_size > 50
    || (params.status !== undefined && (!recordStatuses.has(params.status)
      || (params.source !== 'BUSINESS' && ['PENDING', 'SKIPPED'].includes(params.status))))) throw new Error('发送记录查询条件无效')
  const { data } = await apiClient.get<NotificationSendRecordsResponse>(`${root}send-records/`, { ...options(), params, signal })
  if (!data || !Array.isArray(data.data) || !Number.isSafeInteger(data.count) || data.count < 0
    || !Number.isSafeInteger(data.page) || data.page < 1 || !Number.isSafeInteger(data.page_size) || data.page_size < 1 || data.page_size > 50
    || !data.data.every((row: NotificationSendRecord) => row && row.source === params.source && recordStatuses.has(row.status)
      && ['id', 'recipient_name', 'event_code', 'event_name', 'title', 'body', 'error_code', 'created_at'].every(key => typeof row[key as keyof NotificationSendRecord] === 'string')
      && Number.isSafeInteger(row.attempt_count) && row.attempt_count >= 0
      && (row.sent_at === null || typeof row.sent_at === 'string') && (row.finished_at === null || typeof row.finished_at === 'string'))) {
    throw new Error('发送记录响应无效')
  }
  return data
}

export function notificationSendRecordsError(error: unknown): string {
  if (isAxiosError(error) && error.response?.status === 401) return '登录状态已失效，请重新登录后查看发送记录。'
  if (isAxiosError(error) && error.response?.status === 403) return '当前账号无权查看该来源的发送记录。'
  return '发送记录加载失败，请稍后重试。'
}
