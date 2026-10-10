import { AxiosError } from 'axios'

export function taskRequestMessage(error: unknown): string {
  if (!(error instanceof AxiosError)) return '请求失败，请稍后重试。'
  if (!error.response) return '网络连接异常，请检查服务后重试。'
  const status = error.response.status
  if (status === 403) return '当前账号没有执行此操作的权限。'
  if (status === 404) return '任务不存在或当前账号无权访问。'
  if (status === 409) return '任务状态已变化，当前操作不能继续。'
  if (status === 412) return '任务已被其他人修改，请刷新数据后重试；当前填写内容已保留。'
  if (status === 428) return '缺少版本信息，请刷新数据后重试；当前填写内容已保留。'
  const body = error.response.data as {
    detail?: string
    error?: { message?: string; field_errors?: Record<string, string[]> }
  }
  const fieldError = body.error?.field_errors ? Object.values(body.error.field_errors).flat()[0] : undefined
  return fieldError || body.error?.message || body.detail || '请求失败，请检查填写内容。'
}

export function formatTaskDate(value: string | null | undefined): string {
  if (!value) return '未设置'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleString('zh-CN', { hour12: false }).replaceAll('/', '-')
}
