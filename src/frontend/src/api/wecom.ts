import { isAxiosError } from 'axios'
import { apiClient } from './request'
import type { WeComAudit, WeComBinding, WeComConfig, WeComConfigResponse, WeComConfigWrite, WeComEmployeeOption, WeComPage, WeComMessageTemplate, WeComMessageTemplateResponse, WeComMessageTemplateWrite, WeComMessageTestWrite, WeComMessageAttempt, WeComMessageAttemptQuery } from '@/types/wecom'

const root = '/api/v1/wecom/'
const options = (etag?: string) => ({ timeout: 20000, ...(etag ? { headers: { 'If-Match': etag } } : {}) })
function configResult(response: { data: { data: WeComConfig }; headers: Record<string, unknown> }): WeComConfigResponse {
  const etag = response.headers.etag
  if (typeof etag !== 'string' || !etag) throw new Error('配置版本缺失，无法安全保存。')
  return { data: response.data.data, etag }
}

export async function getWeComConfig(): Promise<WeComConfigResponse> {
  return configResult(await apiClient.get<{ data: WeComConfig }>(root + 'config/', options()))
}

export async function saveWeComConfig(data: WeComConfigWrite, etag: string): Promise<WeComConfigResponse> {
  const payload = { ...data }
  for (const key of ['secret', 'callback_token', 'callback_aes_key'] as const) {
    if (!payload[key]?.trim()) delete payload[key]
  }
  return configResult(await apiClient.patch<{ data: WeComConfig }>(root + 'config/', payload, options(etag)))
}

export async function checkWeComConnection(etag: string): Promise<WeComConfigResponse> {
  return configResult(await apiClient.post<{ data: WeComConfig }>(root + 'config/check/', {}, options(etag)))
}

export async function getWeComBindings(params: { search: string; status: string; page: number }): Promise<WeComPage<WeComBinding>> {
  return (await apiClient.get<WeComPage<WeComBinding>>(root + 'bindings/', { ...options(), params: { ...params, page_size: 20 } })).data
}

export async function getWeComEmployees(search = ''): Promise<WeComEmployeeOption[]> {
  return (await apiClient.get<{ data: WeComEmployeeOption[] }>(root + 'employees/', { ...options(), params: { search } })).data.data
}

export async function bindWeComEmployee(userId: string, employee: WeComEmployeeOption): Promise<WeComBinding> {
  return (await apiClient.post<{ data: WeComBinding }>(root + 'bindings/', { user_id: userId, employee_id: employee.id, confirmed: true }, options(employee.etag))).data.data
}

export async function getWeComAudits(page = 1): Promise<WeComPage<WeComAudit>> {
  return (await apiClient.get<WeComPage<WeComAudit>>(root + 'audits/', { ...options(), params: { page, page_size: 20 } })).data
}

function messageTemplateResult(response: { data: { data: WeComMessageTemplate }; headers: Record<string, unknown> }): WeComMessageTemplateResponse {
  const etag = response.headers.etag
  if (typeof etag !== 'string' || !etag) throw new Error('模板版本缺失，无法安全保存或发送。')
  return { data: response.data.data, etag }
}

export async function getWeComMessageTemplate(): Promise<WeComMessageTemplateResponse> {
  return messageTemplateResult(await apiClient.get<{ data: WeComMessageTemplate }>(root + 'message-template/', options()))
}

export async function saveWeComMessageTemplate(data: WeComMessageTemplateWrite, etag: string): Promise<WeComMessageTemplateResponse> {
  return messageTemplateResult(await apiClient.patch<{ data: WeComMessageTemplate }>(root + 'message-template/', data, options(etag)))
}

export async function sendWeComMessageTest(data: WeComMessageTestWrite, etag: string): Promise<WeComMessageAttempt> {
  return (await apiClient.post<{ data: WeComMessageAttempt }>(root + 'message-tests/', data, options(etag))).data.data
}

export async function getWeComMessageAttempts(params: WeComMessageAttemptQuery): Promise<WeComPage<WeComMessageAttempt>> {
  return (await apiClient.get<WeComPage<WeComMessageAttempt>>(root + 'message-attempts/', { ...options(), params })).data
}

const knownErrorCodes = new Set(['VALIDATION_ERROR', 'AUTHENTICATION_REQUIRED', 'PERMISSION_DENIED', 'NOT_FOUND', 'TOO_MANY_REQUESTS', 'CONFLICT', 'PRECONDITION_FAILED', 'PRECONDITION_REQUIRED', 'REQUEST_FAILED', 'WECOM_UNAVAILABLE', 'WECOM_UPSTREAM_ERROR', 'WECOM_ROLE_REQUIRED'])
const fieldLabels: Record<string, string> = { corp_id: '企业 ID', agent_id: '应用 ID', erp_origin: 'ERP 访问地址', enabled: '启用状态', secret: '应用 Secret', callback_token: '消息回调 Token', callback_aes_key: 'EncodingAESKey', user_id: '企业微信账号', employee_id: 'ERP 员工', confirmed: '身份确认', search: '搜索条件', status: '状态', page: '页码', page_size: '每页条数', non_field_errors: '提交内容', name: '模板名称', body: '消息正文', binding_id: '接收员工', message_content: '测试内容', idempotency_key: '发送请求编号' }

export function wecomError(error: unknown): string {
  if (!isAxiosError(error) || !error.response) return '请求未确认完成，请重新加载核实结果后再操作。'
  const detail = error.response.data?.error
  // 只采用本项目约定的结构化安全错误；不显示HTML错误页或未知异常堆栈。
  if (error.response.status !== 500 && detail && typeof detail === 'object' && knownErrorCodes.has(detail.code) && typeof detail.message === 'string') {
    const messages = [detail.message]
    if (detail.field_errors && typeof detail.field_errors === 'object') {
      for (const [field, value] of Object.entries(detail.field_errors)) {
        if (!Object.hasOwn(fieldLabels, field)) continue
        const errors = (Array.isArray(value) ? value : [value]).filter((item): item is string => typeof item === 'string')
        if (errors.length) messages.push(`${fieldLabels[field]}：${errors.join('；')}`)
      }
    }
    return messages.filter(Boolean).join('；') || '操作未完成，请核对配置后重试。'
  }
  if (error.response.status === 412) return '配置已被修改，请重新加载并核对最新内容。'
  if (error.response.status === 409) return '当前绑定或配置存在冲突，未覆盖或合并，请核对双方身份与配置。'
  if (error.response.status === 403) return '当前账号无权执行此操作，请联系管理员。'
  if (error.response.status === 401) return '登录状态已失效，请重新登录。'
  if (error.response.status === 400) return '提交内容未通过校验，请核对企业、应用、成员账号及凭据格式。'
  return '服务暂时无法完成操作，请稍后重试；必要时联系管理员检查服务器配置。'
}
