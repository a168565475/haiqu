import { describe, expect, it } from 'vitest'

import type { AuthUser } from '@/types/auth'
import type { WorkbenchTask } from '@/types/workbench'
import {
  formatWorkbenchDate,
  isTaskDueToday,
  isUnauthorizedWorkbenchError,
  mergeWorkbenchTasks,
  resolveWorkbenchMode,
  workbenchErrorMessage,
} from './workbench'

function user(permissions: string[], isSuperuser = false): AuthUser {
  return {
    id: 1,
    username: 'tester',
    display_name: '测试用户',
    is_superuser: isSuperuser,
    employee: null,
    permissions,
    data_scope: 'SELF',
  }
}

function task(id: string, dueAt: string, updatedAt = '2026-08-20T08:00:00+08:00'): WorkbenchTask {
  return {
    id,
    title: id,
    status: 'PENDING',
    status_display: '待处理',
    priority: 'NORMAL',
    priority_display: '普通',
    due_at: dueAt,
    completed_at: null,
    assignee: null,
    source: null,
    created_at: updatedAt,
    updated_at: updatedAt,
  }
}

describe('工作台工具', () => {
  it('按超级用户、全量客户权限和普通客户权限选择视图', () => {
    expect(resolveWorkbenchMode(user([], true))).toBe('MANAGER')
    expect(resolveWorkbenchMode(user(['customers.view_all_customer']))).toBe('MANAGER')
    expect(resolveWorkbenchMode(user(['customers.view_customeraccount']))).toBe('SALES')
    expect(resolveWorkbenchMode(user([]))).toBeNull()
  })

  it('合并任务时去重并按截止时间排序', () => {
    const old = task('same', '2026-08-22T09:00:00+08:00')
    const latest = task('same', '2026-08-21T09:00:00+08:00', '2026-08-21T08:00:00+08:00')
    const merged = mergeWorkbenchTasks([old, task('later', '2026-08-23T09:00:00+08:00')], [latest])
    expect(merged.map((item) => item.id)).toEqual(['same', 'later'])
    expect(merged[0]?.due_at).toContain('2026-08-21')
  })

  it('正确判断当天截止并输出中文日期', () => {
    const reference = new Date('2026-08-21T12:00:00+08:00')
    expect(isTaskDueToday(task('today', '2026-08-21T18:00:00+08:00'), reference)).toBe(true)
    expect(formatWorkbenchDate(reference)).toContain('2026年8月21日')
  })

  it('区分登录、权限、并发、服务和网络异常', () => {
    const axiosError = (status?: number, data: Record<string, unknown> = {}) => ({
      isAxiosError: true,
      response: status ? { status, data } : undefined,
    })

    expect(isUnauthorizedWorkbenchError(axiosError(401))).toBe(true)
    expect(workbenchErrorMessage(axiosError(400), '保存')).toContain('参数校验失败')
    expect(workbenchErrorMessage(axiosError(403), '保存')).toContain('没有执行此操作的权限')
    expect(workbenchErrorMessage(axiosError(409), '保存')).toContain('业务冲突')
    expect(workbenchErrorMessage(axiosError(412), '保存')).toContain('其他用户修改')
    expect(workbenchErrorMessage(axiosError(428), '保存')).toContain('缺少数据版本')
    expect(workbenchErrorMessage(axiosError(500), '保存')).toContain('后端服务异常')
    expect(workbenchErrorMessage(axiosError(), '保存', true)).toContain('网络连接异常')
  })
})
