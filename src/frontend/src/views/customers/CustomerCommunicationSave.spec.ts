import { flushPromises, shallowMount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ElementPlus, { ElMessage, ElMessageBox } from 'element-plus'
import { AxiosError } from 'axios'
import { reactive } from 'vue'
import * as customers from '@/api/customers'
import { createCommunication } from '@/api/crm'
import { createTask } from '@/api/tasks'
import CustomerDetailView from './CustomerDetailView.vue'
import type { CustomerDetail } from '@/types/customer'
import type { TaskDetail } from '@/types/task'

const route = reactive({ name: 'customer-timeline', params: { customerId: 'customer-1' }, fullPath: '/customers/customer-1/timeline', hash: '' })
const access = reactive({ task: true, communicate: true, employeeId: 'employee-1' })
vi.mock('vue-router', () => ({ useRoute: () => route, useRouter: () => ({ push: vi.fn() }) }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({
  get user() { return { employee: access.employeeId ? { id: access.employeeId } : null } },
  hasPermission: (code: string) => code === 'workflow.add_businesstask' ? access.task : true,
  canFor: () => access.communicate,
}) }))
vi.mock('@/api/customers', async original => ({
  ...await original<typeof import('@/api/customers')>(),
  fetchCustomer: vi.fn(), fetchCustomerSummary: vi.fn(), fetchCustomerEntities: vi.fn(), fetchCustomerTimeline: vi.fn(),
}))
vi.mock('@/api/crm', () => ({ createCommunication: vi.fn() }))
vi.mock('@/api/tasks', async original => ({
  ...await original<typeof import('@/api/tasks')>(),
  createTask: vi.fn(),
}))
vi.mock('@/api/contacts', () => ({ fetchCustomerContacts: vi.fn().mockResolvedValue({ data: [] }) }))
vi.mock('@/api/referenceData', async original => ({
  ...await original<typeof import('@/api/referenceData')>(),
  fetchPublishedOptions: vi.fn().mockResolvedValue({ data: [], meta: { config_version: 1 } }),
}))

const customer = {
  id: 'customer-1', account_name: '沟通测试客户', account_code: 'CUS-TEST', short_name: '', english_name: '',
  customer_types: [], customer_tags: [], current_assignments: [], interested_products: [], primary_website_url: '',
  primary_owner: { id: 'owner-1', display_name: '客户负责人' },
} as unknown as CustomerDetail
type Page = {
  saveCommunication: () => Promise<void>
  clearCommunicationForm: () => Promise<void>
  communicationSaving: boolean
  communicationForm: { subject: string; content: string; createTask: boolean; taskTitle: string }
  communicationResult: { type: string; message: string; uncertain: boolean } | null
}
let wrapper: ReturnType<typeof shallowMount> | undefined
async function render() {
  wrapper = shallowMount(CustomerDetailView, { global: { plugins: [ElementPlus] } })
  await flushPromises()
  const page = wrapper.vm as unknown as Page
  Object.assign(page.communicationForm, { subject: '确认产品交期', content: '约定下周反馈', taskTitle: '核对交期' })
  return page
}
function rejected(status?: number) {
  return new AxiosError('request failed', status ? undefined : 'ECONNABORTED', undefined, undefined,
    status ? { status, data: { error: { message: '服务拒绝请求' } }, headers: {}, config: {} as never, statusText: '' } : undefined)
}
beforeEach(() => {
  vi.clearAllMocks()
  setActivePinia(createPinia())
  route.params.customerId = 'customer-1'
  Object.assign(access, { task: true, communicate: true, employeeId: 'employee-1' })
  vi.mocked(customers.fetchCustomer).mockResolvedValue({ data: customer, etag: 'v1' })
  vi.mocked(customers.fetchCustomerSummary).mockResolvedValue({ counts: {} } as never)
  vi.mocked(customers.fetchCustomerEntities).mockResolvedValue([])
  vi.mocked(customers.fetchCustomerTimeline).mockResolvedValue({ data: [], meta: { next: null } } as never)
  vi.mocked(createCommunication).mockResolvedValue({ id: 'communication-1' } as never)
  vi.mocked(createTask).mockResolvedValue({ id: 'task-1' } as TaskDetail)
  vi.spyOn(ElMessage, 'success').mockImplementation(() => ({} as never))
  vi.spyOn(ElMessage, 'warning').mockImplementation(() => ({} as never))
  vi.spyOn(ElMessage, 'error').mockImplementation(() => ({} as never))
  vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue('confirm' as Awaited<ReturnType<typeof ElMessageBox.confirm>>)
})
afterEach(() => { wrapper?.unmount(); wrapper = undefined; vi.restoreAllMocks() })

describe('客户沟通与后续任务分阶段保存（隔离 API）', () => {
  it('任务明确拒绝后保留已保存沟通，禁止再次提交整份表单', async () => {
    const page = await render()
    vi.mocked(createTask).mockRejectedValueOnce(rejected(400))
    await page.saveCommunication()
    expect(page.communicationResult?.message).toContain('沟通记录已保存')
    expect(page.communicationResult?.message).toContain('后续任务未创建')
    expect(page.communicationForm.subject).toBe('确认产品交期')
    expect(ElMessage.success).not.toHaveBeenCalled()
    const composer = wrapper!.get('.customer-timeline-v2__composer')
    expect(composer.findComponent({ name: 'ElAlert' }).props('title')).toContain('后续任务未创建')
    expect(composer.findComponent({ name: 'ElForm' }).props('disabled')).toBe(true)
    expect(composer.findAllComponents({ name: 'ElButton' }).at(-1)?.props('disabled')).toBe(true)
    await page.saveCommunication()
    expect(createCommunication).toHaveBeenCalledTimes(1)
    expect(createTask).toHaveBeenCalledTimes(1)
  })

  it.each([undefined, 500])('任务请求 %s 结果未知时没有自动或再次提交重试', async status => {
    const page = await render()
    vi.mocked(createTask).mockRejectedValueOnce(rejected(status))
    await page.saveCommunication()
    expect(page.communicationResult).toMatchObject({ type: 'warning', uncertain: true })
    expect(page.communicationResult?.message).toContain('任务创建结果尚未确认')
    await page.saveCommunication()
    expect(createCommunication).toHaveBeenCalledTimes(1)
    expect(createTask).toHaveBeenCalledTimes(1)
    vi.mocked(ElMessageBox.confirm).mockRejectedValueOnce('cancel')
    await page.clearCommunicationForm()
    expect(page.communicationResult?.uncertain).toBe(true)
    expect(page.communicationForm.subject).toBe('确认产品交期')
    await page.clearCommunicationForm()
    expect(ElMessageBox.confirm).toHaveBeenCalled()
    expect(page.communicationResult).toBeNull()
  })

  it.each([undefined, 503])('沟通请求 %s 结果未知时保留内容并阻止直接重试', async status => {
    const page = await render()
    vi.mocked(createCommunication).mockRejectedValueOnce(rejected(status))
    await page.saveCommunication()
    expect(page.communicationResult?.message).toContain('沟通记录保存结果尚未确认')
    expect(page.communicationResult?.uncertain).toBe(true)
    expect(page.communicationForm.content).toBe('约定下周反馈')
    await page.saveCommunication()
    expect(createCommunication).toHaveBeenCalledTimes(1)
    expect(createTask).not.toHaveBeenCalled()
  })

  it('沟通被明确拒绝时保留草稿，允许修改后再次保存', async () => {
    const page = await render()
    vi.mocked(createCommunication).mockRejectedValueOnce(rejected(400))
    await page.saveCommunication()
    expect(page.communicationResult).toBeNull()
    expect(page.communicationForm.subject).toBe('确认产品交期')
    expect(createTask).not.toHaveBeenCalled()
    await page.saveCommunication()
    expect(createCommunication).toHaveBeenCalledTimes(2)
  })

  it('缺少客户负责人和当前员工时在任何写入前提示', async () => {
    access.employeeId = ''
    vi.mocked(customers.fetchCustomer).mockResolvedValue({ data: { ...customer, primary_owner: null }, etag: 'v1' })
    const page = await render()
    await page.saveCommunication()
    expect(createCommunication).not.toHaveBeenCalled()
    expect(createTask).not.toHaveBeenCalled()
    expect(ElMessage.warning).toHaveBeenCalledWith(expect.stringContaining('负责人'))
  })

  it('没有任务权限时默认仅保存沟通，不能提示任务成功', async () => {
    access.task = false
    const page = await render()
    expect(page.communicationForm.createTask).toBe(false)
    await page.saveCommunication()
    expect(createTask).not.toHaveBeenCalled()
    expect(ElMessage.success).toHaveBeenCalledWith('沟通记录已保存。')
  })

  it('提交时仍检查任务权限和沟通权限', async () => {
    access.task = false
    const page = await render()
    page.communicationForm.createTask = true
    await page.saveCommunication()
    expect(createCommunication).not.toHaveBeenCalled()
    page.communicationForm.createTask = false
    access.communicate = false
    await page.saveCommunication()
    expect(createCommunication).not.toHaveBeenCalled()
  })

  it.each(['base', 'timeline'])('%s 刷新失败不能冒充写入失败，已保存表单保持锁定', async target => {
    const page = await render()
    if (target === 'base') vi.mocked(customers.fetchCustomer).mockRejectedValueOnce(rejected(503))
    else vi.mocked(customers.fetchCustomerTimeline).mockRejectedValueOnce(rejected(503))
    await page.saveCommunication()
    expect(page.communicationResult?.message).toContain('沟通记录和后续任务已保存')
    expect(page.communicationResult?.message).toContain('刷新失败')
    expect(ElMessage.error).not.toHaveBeenCalledWith(expect.stringContaining('沟通记录保存失败'))
    await page.saveCommunication()
    expect(createCommunication).toHaveBeenCalledTimes(1)
  })

  it('请求期间双击和清空不会重复写入或丢失草稿', async () => {
    const page = await render()
    let resolve!: (value: never) => void
    vi.mocked(createCommunication).mockReturnValueOnce(new Promise(done => { resolve = done }))
    const first = page.saveCommunication()
    await page.saveCommunication()
    await page.clearCommunicationForm()
    expect(page.communicationForm.subject).toBe('确认产品交期')
    expect(createCommunication).toHaveBeenCalledTimes(1)
    resolve({ id: 'communication-1' } as never)
    await first
    expect(createTask).toHaveBeenCalledTimes(1)
    expect(page.communicationSaving).toBe(false)
  })

  it('沟通请求期间切换客户，不给新客户写任务或覆盖其表单结果', async () => {
    const page = await render()
    let resolve!: (value: never) => void
    vi.mocked(createCommunication).mockReturnValueOnce(new Promise(done => { resolve = done }))
    const saving = page.saveCommunication()
    route.params.customerId = 'customer-2'
    resolve({ id: 'communication-1' } as never)
    await saving
    expect(createCommunication).toHaveBeenCalledWith(expect.objectContaining({ customer_account_id: 'customer-1' }))
    expect(createTask).not.toHaveBeenCalled()
    expect(page.communicationResult).toBeNull()
  })

  it('沟通保存期间任务权限撤销时准确报告部分成功', async () => {
    const page = await render()
    let resolve!: (value: never) => void
    vi.mocked(createCommunication).mockReturnValueOnce(new Promise(done => { resolve = done }))
    const saving = page.saveCommunication()
    access.task = false
    resolve({ id: 'communication-1' } as never)
    await saving
    expect(createTask).not.toHaveBeenCalled()
    expect(page.communicationResult?.message).toContain('后续任务未创建')
    expect(ElMessage.success).not.toHaveBeenCalled()
  })

  it('全部保存成功后必须明确开始新沟通才解除本次提交锁', async () => {
    const page = await render()
    await page.saveCommunication()
    expect(page.communicationResult?.message).toBe('沟通记录和后续任务已保存。')
    expect(createTask).toHaveBeenCalledWith(expect.objectContaining({ source_type: 'COMMUNICATION', source_id: 'communication-1', assignee_employee_id: 'owner-1' }))
    await page.clearCommunicationForm()
    expect(page.communicationResult).toBeNull()
    expect(page.communicationForm.subject).toBe('')
  })
})
