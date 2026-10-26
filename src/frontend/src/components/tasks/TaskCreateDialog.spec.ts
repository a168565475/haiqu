import { flushPromises, shallowMount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ElementPlus, { ElMessage } from 'element-plus'

import { createTask, fetchTaskOptions } from '@/api/tasks'
import type { TaskDetail, TaskOptions } from '@/types/task'
import TaskCreateDialog from './TaskCreateDialog.vue'

vi.mock('@/api/tasks', () => ({ createTask: vi.fn(), fetchTaskOptions: vi.fn() }))

const options: TaskOptions = { scopes: [], task_types: [], statuses: [], priorities: [], assignees: [] }
const task = { id: 'task-1' } as TaskDetail
let wrapper: ReturnType<typeof shallowMount> | undefined

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(createTask).mockResolvedValue(task)
  vi.mocked(fetchTaskOptions).mockResolvedValue(options)
  vi.spyOn(ElMessage, 'success').mockImplementation(() => ({} as never))
})
afterEach(() => { wrapper?.unmount(); wrapper = undefined; vi.restoreAllMocks() })

describe('新建任务窗口的共享 API 输入', () => {
  it.each([
    { name: '手工任务', props: {}, source: {} },
    { name: '客户任务', props: { fixedCustomerId: 'customer-1' }, source: { source_type: 'CUSTOMER', source_id: 'customer-1' } },
    { name: '询盘优先于客户来源', props: { fixedCustomerId: 'customer-1', fixedInquiryId: 'inquiry-1' }, source: { source_type: 'INQUIRY', source_id: 'inquiry-1' } },
  ])('$name 保留原来源与可空截止时间', async ({ props, source }) => {
    wrapper = shallowMount(TaskCreateDialog, { props: { modelValue: true, options, ...props }, global: { plugins: [ElementPlus] } })
    await flushPromises()
    const page = wrapper.vm as unknown as { form: Record<string, unknown>; submit: () => Promise<void> }
    Object.assign(page.form, { title: ' 跟进事项 ', description: ' 联系客户 ', assignee_employee_id: 'owner-1' })

    await page.submit()

    expect(createTask).toHaveBeenCalledTimes(1)
    expect(createTask).toHaveBeenCalledWith({
      title: '跟进事项', description: '联系客户', assignee_employee_id: 'owner-1',
      task_type: 'OTHER', priority: 'NORMAL', due_at: null, ...source,
    })
    expect(wrapper.emitted('created')).toEqual([[task]])
    expect(wrapper.emitted('update:modelValue')).toEqual([[false]])
  })
})
