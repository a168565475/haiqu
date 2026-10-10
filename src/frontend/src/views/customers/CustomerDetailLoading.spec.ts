import { flushPromises, shallowMount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ElementPlus from 'element-plus'
import { reactive } from 'vue'
import { useRoute } from 'vue-router'
import * as customers from '@/api/customers'
import { fetchCustomerContacts } from '@/api/contacts'
import { fetchTasks } from '@/api/tasks'
import { fetchPublishedOptions } from '@/api/referenceData'
import CustomerDetailView from './CustomerDetailView.vue'
import type { CustomerDetail, CustomerOptions } from '@/types/customer'

const route = reactive({ name: 'customer-detail', params: { customerId: 'customer-1' }, fullPath: '/customers/customer-1' })
vi.mock('vue-router', () => ({ useRoute: vi.fn(), useRouter: () => ({ push: vi.fn() }) }))
vi.mock('@/api/customers', async original => ({
  ...await original<typeof import('@/api/customers')>(),
  fetchCustomer: vi.fn(), fetchCustomerSummary: vi.fn(), fetchCustomerOptions: vi.fn(),
  fetchCustomerEntities: vi.fn(), fetchCustomerEntity: vi.fn(), fetchEntityAddresses: vi.fn(), fetchEntityAddress: vi.fn(),
  fetchCustomerTimeline: vi.fn(), checkCustomerDuplicates: vi.fn(),
}))
vi.mock('@/api/contacts', () => ({ fetchCustomerContacts: vi.fn() }))
vi.mock('@/api/tasks', async original => ({ ...await original<typeof import('@/api/tasks')>(), fetchTasks: vi.fn() }))
vi.mock('@/api/referenceData', async original => ({ ...await original<typeof import('@/api/referenceData')>(), fetchPublishedOptions: vi.fn() }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: () => true, canFor: () => true }) }))

const customer = {
  id: 'customer-1', account_name: '加载测试客户', account_code: 'CUS-TEST', short_name: '', english_name: '',
  customer_types: [], customer_tags: [], current_assignments: [], interested_products: [], primary_website_url: '',
} as unknown as CustomerDetail
const options = {
  customer_grades: [], customer_types: [], customer_sources: [], country_options: [], customer_tags: [],
  secondary_regions: [], primary_regions: [], industries: [], interested_products: [], owner_options: [],
} as unknown as CustomerOptions
const mount = () => shallowMount(CustomerDetailView, { global: { plugins: [ElementPlus] } })

describe('客户详情加载依赖', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    setActivePinia(createPinia())
    route.name = 'customer-detail'
    route.fullPath = '/customers/customer-1'
    vi.mocked(useRoute).mockReturnValue(route as never)
    vi.mocked(customers.fetchCustomer).mockResolvedValue({ data: customer, etag: 'customer-v1' })
    vi.mocked(customers.fetchCustomerSummary).mockResolvedValue({ counts: {} } as never)
    vi.mocked(customers.fetchCustomerOptions).mockResolvedValue(options)
    vi.mocked(customers.fetchCustomerEntities).mockResolvedValue([{ id: 'entity-1' }] as never)
    vi.mocked(customers.fetchCustomerEntity).mockResolvedValue({ data: { id: 'entity-1' }, etag: 'entity-v1' } as never)
    vi.mocked(customers.fetchEntityAddresses).mockResolvedValue([{ id: 'address-1', address_line1: '测试街道', city: '测试城市' }] as never)
    vi.mocked(customers.fetchEntityAddress).mockResolvedValue({ data: { id: 'address-1' }, etag: 'address-v1' } as never)
    vi.mocked(customers.fetchCustomerTimeline).mockResolvedValue({ data: [], meta: { next: null } } as never)
    vi.mocked(fetchCustomerContacts).mockResolvedValue({ data: [] } as never)
    vi.mocked(fetchTasks).mockResolvedValue({ data: [] } as never)
    vi.mocked(fetchPublishedOptions).mockResolvedValue({ data: [], meta: { config_version: 1 } })
  })

  it('汇总尚未返回时，时间轴、任务、联系人与地址已经开始加载', async () => {
    let finish!: (value: never) => void
    vi.mocked(customers.fetchCustomerSummary).mockReturnValue(new Promise(resolve => { finish = resolve }))
    const wrapper = mount()
    await flushPromises()
    expect(customers.fetchCustomerTimeline).toHaveBeenCalledTimes(1)
    expect(fetchTasks).toHaveBeenCalledTimes(2)
    expect(fetchCustomerContacts).toHaveBeenCalledTimes(1)
    expect(customers.fetchEntityAddresses).toHaveBeenCalledTimes(1)
    finish({ counts: {} } as never)
    await flushPromises()
    wrapper.unmount()
  })

  it('概览保留地址完整度数据，不读取编辑版本、编辑选项或查重', async () => {
    const wrapper = mount()
    await flushPromises()
    expect(customers.fetchEntityAddresses).toHaveBeenCalledTimes(1)
    expect(customers.fetchCustomerEntity).not.toHaveBeenCalled()
    expect(customers.fetchEntityAddress).not.toHaveBeenCalled()
    expect(customers.fetchCustomerOptions).not.toHaveBeenCalled()
    expect(wrapper.find('.profile-completeness-value').text()).toBe('27%')
    await new Promise(resolve => setTimeout(resolve, 450))
    expect(customers.checkCustomerDuplicates).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('同客户切页复用基础资料，但刷新联系人与汇总，概览不继承时间轴筛选', async () => {
    const wrapper = mount()
    await flushPromises()
    route.name = 'customer-contacts'; route.fullPath += '/contacts'
    await flushPromises()
    route.name = 'customer-timeline'; route.fullPath += '/timeline'
    await flushPromises()
    const vm = wrapper.vm as unknown as { timelineFilters: { eventType: string } }
    vm.timelineFilters.eventType = 'TASK_CREATED'
    route.name = 'customer-detail'; route.fullPath = '/customers/customer-1'
    await flushPromises()
    expect(customers.fetchCustomer).toHaveBeenCalledTimes(1)
    expect(customers.fetchCustomerSummary).toHaveBeenCalledTimes(4)
    expect(fetchCustomerContacts).toHaveBeenCalledTimes(3)
    expect(customers.fetchCustomerTimeline).toHaveBeenLastCalledWith('customer-1', expect.objectContaining({ event_type: undefined }))
    wrapper.unmount()
  })

  it('较早的联系人、任务和汇总请求晚到时，不能覆盖新结果', async () => {
    const wrapper = mount()
    await flushPromises()
    const vm = wrapper.vm as unknown as {
      loadCommunicationContacts: (force: boolean) => Promise<void>
      loadCustomerOpenTasks: () => Promise<void>
      refreshCustomerSummary: () => Promise<void>
      contacts: Array<{ id: string }>
      customerTasks: Array<{ id: string }>
      summary: { counts: { contacts: number } }
    }
    let oldContacts!: (value: never) => void
    vi.mocked(fetchCustomerContacts).mockImplementationOnce(() => new Promise(resolve => { oldContacts = resolve }))
      .mockResolvedValueOnce({ data: [{ id: 'new-contact' }] } as never)
    const first = vm.loadCommunicationContacts(true)
    await vm.loadCommunicationContacts(true)
    oldContacts({ data: [{ id: 'old-contact' }] } as never)
    await first
    expect(vm.contacts[0]?.id).toBe('new-contact')
    let oldTask!: (value: never) => void
    vi.mocked(fetchTasks).mockImplementationOnce(() => new Promise(resolve => { oldTask = resolve }))
      .mockResolvedValueOnce({ data: [] } as never)
      .mockResolvedValueOnce({ data: [{ id: 'new-task', due_at: null }] } as never)
      .mockResolvedValueOnce({ data: [] } as never)
    const tasks = vm.loadCustomerOpenTasks()
    await vm.loadCustomerOpenTasks()
    oldTask({ data: [{ id: 'old-task' }] } as never)
    await tasks
    expect(vm.customerTasks[0]?.id).toBe('new-task')
    let oldSummary!: (value: never) => void
    vi.mocked(customers.fetchCustomerSummary).mockImplementationOnce(() => new Promise(resolve => { oldSummary = resolve }))
      .mockResolvedValueOnce({ counts: { contacts: 2 } } as never)
    const summary = vm.refreshCustomerSummary()
    await vm.refreshCustomerSummary()
    oldSummary({ counts: { contacts: 1 } } as never)
    await summary
    expect(vm.summary.counts.contacts).toBe(2)
    wrapper.unmount()
  })

  it('编辑模式仍读取主体和地址版本，保留保存所需的并发校验', async () => {
    route.name = 'customer-edit'
    const wrapper = mount()
    await flushPromises()
    expect(customers.fetchCustomerEntity).toHaveBeenCalledTimes(1)
    expect(customers.fetchEntityAddress).toHaveBeenCalledTimes(1)
    expect(customers.fetchCustomerOptions).toHaveBeenCalledTimes(1)
    expect(customers.fetchCustomerTimeline).not.toHaveBeenCalled()
    wrapper.unmount()
  })
})
