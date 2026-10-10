import { isAxiosError } from 'axios'

import type { AuthUser } from '@/types/auth'
import type { WorkbenchMode, WorkbenchTask } from '@/types/workbench'

export function isUnauthorizedWorkbenchError(error: unknown): boolean {
  return isAxiosError(error) && error.response?.status === 401
}

export function workbenchErrorMessage(
  error: unknown,
  action: string,
  preserveInput = false,
): string {
  const retryHint = preserveInput ? '，已保留当前输入内容，请稍后重试。' : '，请稍后重试。'
  if (!isAxiosError(error)) return `${action}失败${retryHint}`
  if (!error.response) return `网络连接异常${retryHint}`

  const status = error.response.status
  const payload = error.response.data as Record<string, unknown> | undefined
  const detail = typeof payload?.detail === 'string' ? payload.detail : ''
  const apiError = payload?.error as Record<string, unknown> | undefined
  const message = detail || (typeof apiError?.message === 'string' ? apiError.message : '')
  if (message) return message

  if (status === 400) return `${action}参数校验失败，请检查填写内容后重试。`
  if (status === 401) return '登录状态已失效，正在返回登录页。'
  if (status === 403) return '当前账号没有执行此操作的权限。'
  if (status === 409) return '数据存在业务冲突，请刷新后重试。'
  if (status === 412) return '数据已被其他用户修改，请刷新最新数据后重试。'
  if (status === 428) return '缺少数据版本，请重新打开后再提交。'
  if (status >= 500) return `后端服务异常${retryHint}`
  return `${action}失败${retryHint}`
}

export function resolveWorkbenchMode(user: AuthUser | null): WorkbenchMode | null {
  if (!user) return null
  if (user.is_superuser || user.permissions.includes('customers.view_all_customer')) {
    return 'MANAGER'
  }
  if (user.permissions.includes('customers.view_customeraccount')) {
    return 'SALES'
  }
  return null
}

export function mergeWorkbenchTasks(
  pending: WorkbenchTask[],
  inProgress: WorkbenchTask[],
): WorkbenchTask[] {
  const taskMap = new Map<string, WorkbenchTask>()
  for (const task of [...pending, ...inProgress]) {
    const current = taskMap.get(task.id)
    if (!current || new Date(task.updated_at).getTime() > new Date(current.updated_at).getTime()) {
      taskMap.set(task.id, task)
    }
  }
  return [...taskMap.values()].sort((left, right) => {
    const leftTime = new Date(left.due_at).getTime()
    const rightTime = new Date(right.due_at).getTime()
    if (leftTime !== rightTime) return leftTime - rightTime
    return left.id.localeCompare(right.id)
  })
}

export function isTaskDueToday(task: WorkbenchTask, reference = new Date()): boolean {
  const due = new Date(task.due_at)
  return (
    due.getFullYear() === reference.getFullYear() &&
    due.getMonth() === reference.getMonth() &&
    due.getDate() === reference.getDate()
  )
}

export function isTaskOverdue(task: WorkbenchTask, reference = new Date()): boolean {
  return new Date(task.due_at).getTime() < reference.getTime()
}

export function formatWorkbenchDate(value: Date): string {
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
    weekday: 'long',
  }).format(value)
}
