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
import CustomerEditDialog from './CustomerEditDialog.vue'
import type { CustomerDetail, CustomerOptions } from '@/types/customer'

const route = reactive({ name: 'customer-detail', params: { customerId: 'customer-1' }, fullPath: '/customers/customer-1', hash: '' })
const routerPush = vi.hoisted(() => vi.fn())
vi.mock('vue-router', () => ({ useRoute: vi.fn(), useRouter: () => ({ push: routerPush }) }))
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
    route.hash = ''
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

  it('头部和概览编辑入口在当前详情开窗，保存后刷新客户资料', async () => {
    const wrapper = mount()
    await flushPromises()
    const vm = wrapper.vm as unknown as { openCustomerEdit: () => void }
    vm.openCustomerEdit()
    await flushPromises()
    const dialog = wrapper.getComponent(CustomerEditDialog)
    expect(dialog.props()).toMatchObject({ modelValue: true, customerId: 'customer-1' })
    expect(routerPush).not.toHaveBeenCalled()
    dialog.vm.$emit('update:modelValue', false)
    await flushPromises()
    wrapper.findComponent({ name: 'CustomerOverviewV2' }).vm.$emit('editCustomer')
    await flushPromises()
    expect(dialog.props('modelValue')).toBe(true)
    vi.mocked(customers.fetchCustomer).mockClear()
    dialog.vm.$emit('saved', 'customer-1', false)
    await flushPromises()
    expect(customers.fetchCustomer).toHaveBeenCalledExactlyOnceWith('customer-1')
    expect(dialog.props('modelValue')).toBe(true)
    expect(routerPush).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('编辑完成时等待旧刷新结束，再读取保存后的客户资料', async () => {
    const wrapper = mount()
    await flushPromises()
    const vm = wrapper.vm as unknown as {
      loadCustomerBase: (force: boolean) => Promise<void>
      handleCustomerEdited: (id: string) => Promise<void>
      customer: CustomerDetail
    }
    let finish!: (value: never) => void
    vi.mocked(customers.fetchCustomerSummary).mockReturnValueOnce(new Promise(resolve => { finish = resolve }))
    vi.mocked(customers.fetchCustomer).mockClear()
    vi.mocked(customers.fetchCustomer)
      .mockResolvedValueOnce({ data: { ...customer, account_name: '保存前名称' }, etag: 'v1' })
      .mockResolvedValueOnce({ data: { ...customer, account_name: '保存后名称' }, etag: 'v2' })
    const earlier = vm.loadCustomerBase(true)
    await flushPromises()
    const refreshed = vm.handleCustomerEdited('customer-1')
    await flushPromises()
    expect(customers.fetchCustomer).toHaveBeenCalledTimes(1)
    finish({ counts: {} } as never)
    await Promise.all([earlier, refreshed])
    expect(customers.fetchCustomer).toHaveBeenCalledTimes(2)
    expect(vm.customer.account_name).toBe('保存后名称')
    wrapper.unmount()
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
    route.name = 'customer-inquiries'; route.fullPath += '/inquiries'
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

  it('联系人请求失败会明确提示，重试成功才恢复联系人内容', async () => {
    vi.mocked(fetchCustomerContacts).mockRejectedValueOnce(new Error('联系人服务暂不可用'))
    const wrapper = mount()
    await flushPromises()
    const overview = wrapper.findComponent({ name: 'CustomerOverviewV2' })
    expect(overview.props('contactsError')).toBeTruthy()
    expect(overview.props('contactsLoading')).toBe(false)
    vi.mocked(fetchCustomerContacts).mockResolvedValueOnce({ data: [{ id: 'contact-1' }] } as never)
    overview.vm.$emit('retryContacts')
    await flushPromises()
    expect(overview.props('contactsError')).toBe('')
    expect(overview.props('contacts')).toEqual([{ id: 'contact-1' }])
    wrapper.unmount()
  })

  it('概览加载全部联系人分页，避免移除联系人页签后丢失后续联系人', async () => {
    vi.mocked(fetchCustomerContacts)
      .mockResolvedValueOnce({ data: [{ id: 'contact-1' }], meta: { total_pages: 2 } } as never)
      .mockResolvedValueOnce({ data: [{ id: 'contact-2' }], meta: { total_pages: 2 } } as never)
    const wrapper = mount()
    await flushPromises()
    expect(fetchCustomerContacts).toHaveBeenLastCalledWith('customer-1', { page: 2, page_size: 100 })
    expect(wrapper.findComponent({ name: 'CustomerOverviewV2' }).props('contacts')).toHaveLength(2)
    wrapper.unmount()
  })

  it('客户详情导航不再展示独立联系人页签', async () => {
    const wrapper = mount()
    await flushPromises()
    expect(wrapper.find('.customer-overview-tabs').text()).not.toContain('联系人')
    wrapper.unmount()
  })

  it('旧联系人链接等数据加载完成后定位概览联系人区', async () => {
    route.hash = '#customer-contacts'
    let finish!: (value: never) => void
    vi.mocked(fetchCustomerContacts).mockReturnValueOnce(new Promise(resolve => { finish = resolve }))
    const anchor = document.createElement('section')
    anchor.id = 'customer-contacts'
    anchor.scrollIntoView = vi.fn()
    document.body.append(anchor)
    const wrapper = mount()
    try {
      await flushPromises()
      expect(anchor.scrollIntoView).not.toHaveBeenCalled()
      finish({ data: [] } as never)
      await flushPromises()
      expect(anchor.scrollIntoView).toHaveBeenCalledWith({ block: 'nearest' })
    } finally {
      wrapper.unmount()
      anchor.remove()
    }
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
