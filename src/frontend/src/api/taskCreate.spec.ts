import { beforeEach, describe, expect, expectTypeOf, it, vi } from 'vitest'

import { createTask } from '@/api/tasks'
import { apiClient } from '@/api/request'
import type { TaskCreateInput, TaskDetail } from '@/types/task'

vi.mock('@/api/request', () => ({ apiClient: { post: vi.fn() } }))
const post = vi.mocked(apiClient.post)

const inputs: Array<{ name: string; input: TaskCreateInput }> = [
  { name: '沟通后续任务', input: {
    assignee_employee_id: 'owner-1', title: '跟进交期', description: '沟通后续', priority: 'NORMAL',
    due_at: '2026-10-27T10:00:00+08:00', source_type: 'COMMUNICATION', source_id: 'communication-1',
  } },
  { name: '询盘任务', input: {
    assignee_employee_id: 'owner-1', title: '回应询盘', task_type: 'INQUIRY_RESPONSE', priority: 'HIGH',
    due_at: null, source_type: 'INQUIRY', source_id: 'inquiry-1',
  } },
  { name: '客户任务', input: {
    assignee_employee_id: 'owner-1', title: '客户回访', source_type: 'CUSTOMER', source_id: 'customer-1',
  } },
  { name: '手工任务', input: {
    assignee_employee_id: 'owner-1', title: '核对安排', task_type: 'OTHER', due_at: null, contact_id: null,
    checklist: ['核对交期'], reminder_at_list: ['2026-10-27T09:00:00+08:00'],
  } },
]

describe('创建任务 API 的共享契约', () => {
  beforeEach(() => post.mockReset())

  it.each(inputs)('$name 保留输入并返回解包后的任务详情', async ({ input }) => {
    const task = { id: 'task-1', title: input.title } as TaskDetail
    post.mockResolvedValueOnce({ data: { data: task } })

    const result = await createTask(input)

    expect(post).toHaveBeenCalledTimes(1)
    expect(post).toHaveBeenCalledWith('/api/v1/tasks/', input)
    expect(result).toBe(task)
    expectTypeOf(result).toEqualTypeOf<TaskDetail>()
    expectTypeOf(createTask).parameter(0).toEqualTypeOf<TaskCreateInput>()
  })

  it('将失败交给调用方处理，不自动重试或返回假成功', async () => {
    const issue = new Error('request result unknown')
    post.mockRejectedValueOnce(issue)

    await expect(createTask(inputs[0]!.input)).rejects.toBe(issue)
    expect(post).toHaveBeenCalledTimes(1)
  })
})
