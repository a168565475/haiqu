import { AxiosError } from 'axios'

export function complaintRequestMessage(error: unknown): string {
  if (!(error instanceof AxiosError)) return error instanceof Error && error.message ? error.message : '请求失败，请稍后重试。'
  if (!error.response) return '网络连接异常，请检查后端服务。'
  if (error.response.status === 412) return '记录已被其他人更新，请刷新后重试。'
  if (error.response.status === 428) return '缺少版本信息，请刷新后重试。'
  if (error.response.status === 409) return '当前状态不允许该操作。'
  if (error.response.status === 403) return '当前账号没有访问或执行此客诉操作的权限。'
  const body = error.response.data as { detail?: string; errors?: Record<string, string[]>; error?: { message?: string; field_errors?: Record<string, string[]> } }
  return body.detail
    || body.error?.message
    || Object.values(body.errors || body.error?.field_errors || {}).flat()[0]
    || '请求失败，请检查填写内容。'
}

export function complaintDate(value?: string | null): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleString('zh-CN', { hour12: false }).replaceAll('/', '-')
}

export function validateComplaintImages(files: File[]): string | null {
  const allowed = ['image/jpeg', 'image/png', 'image/webp']
  if (files.some(file => !allowed.includes(file.type))) return '图片仅支持 JPG、PNG、WebP 格式。'
  if (files.some(file => file.size > 5 * 1024 * 1024)) return '单张图片不能超过 5MB。'
  return null
}
