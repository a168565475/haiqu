import { isAxiosError, isCancel } from 'axios'

export function errorMessage(error: unknown, fallback = '操作未完成，请重试'): string {
  if (isCancel(error)) return '当前身份或页面已变化，请重新打开'
  if (!isAxiosError(error)) return error instanceof Error ? error.message : fallback
  const body: unknown = error.response?.data
  if (body && typeof body === 'object') {
    const data = body as Record<string, unknown>
    if (data.error && typeof data.error === 'object') {
      const nested = data.error as Record<string, unknown>
      if (typeof nested.message === 'string' && nested.message) return nested.message
      const fields = nested.field_errors
      if (fields && typeof fields === 'object') {
        const values = Object.values(fields).flatMap(value => Array.isArray(value) ? value.filter(item => typeof item === 'string') : [])
        if (values.length) return values.join('；')
      }
    }
    if (typeof data.detail === 'string') return data.detail
    if (typeof data.message === 'string') return data.message
    const messages = Object.entries(data).flatMap(([key, value]) => {
      if (key === 'meta' || key === 'code') return []
      if (Array.isArray(value)) return value.filter((item): item is string => typeof item === 'string')
      return typeof value === 'string' ? [value] : []
    })
    if (messages.length) return messages.join('；')
  }
  if (!error.response) return '网络连接中断或请求超时，请先核对提交结果'
  if (error.response.status === 401) return '登录已失效，请重新登录'
  if (error.response.status === 403) return '没有此项操作权限，或登录校验已失效'
  if (error.response.status === 404) return '记录不存在或不在可访问范围内'
  if (error.response.status === 409 || error.response.status === 412) return '记录已更新，请刷新后核对'
  return fallback
}
