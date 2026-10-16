import { flushPromises, shallowMount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ElementPlus from 'element-plus'
import * as api from '@/api/inquiries'
import InquiryDetailView from './InquiryDetailView.vue'

vi.mock('vue-router', () => ({ useRoute: () => ({ params: { inquiryId: 'one' }, query: {} }), useRouter: () => ({ push: vi.fn() }), onBeforeRouteLeave: vi.fn(), onBeforeRouteUpdate: vi.fn() }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: () => true, canFor: () => true, user: { employee: { id: 'employee' } } }) }))
vi.mock('@/api/inquiries', async original => ({ ...await original<typeof import('@/api/inquiries')>(), fetchInquiry: vi.fn(), fetchInquiryTimeline: vi.fn(), fetchInquiryTasks: vi.fn(), fetchInquiryOptions: vi.fn() }))
vi.mock('@/components/InquiryWangEditor.vue', () => ({ default: { template: '<div />' } }))
const detail = { id: 'one', inquiry_number: 'INQ-ONE', status: 'DRAFT', status_display: '草稿', customer: { id: 'customer', name: '客户' }, source: {}, allowed_actions: { assign: true }, items: [], files: [], linked_quotations: [], linked_samples: [], linked_sales_orders: [], sla_history: [], assignment_history: [], owner: null }
const wrappers: ReturnType<typeof shallowMount>[] = []

afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()) })

describe('询盘分区加载', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(api.fetchInquiry).mockResolvedValue({ data: detail, etag: 'v1' } as never)
    vi.mocked(api.fetchInquiryTimeline).mockResolvedValue({ data: [], meta: { total: 0 } } as never)
    vi.mocked(api.fetchInquiryTasks).mockResolvedValue([])
    vi.mocked(api.fetchInquiryOptions).mockResolvedValue({ owners: [], invalid_reason_codes: [] } as never)
  })
  it('操作选项未返回也显示正文，相关操作保持禁用', async () => {
    let resolve!: (value: never) => void
    vi.mocked(api.fetchInquiryOptions).mockImplementationOnce(() => new Promise(done => { resolve = done }))
    const wrapper = shallowMount(InquiryDetailView, { global: { plugins: [ElementPlus] } })
    wrappers.push(wrapper)
    await flushPromises()
    expect(wrapper.attributes('aria-busy')).toBe('false')
    expect(wrapper.text()).toContain('INQ-ONE')
    const transfer = wrapper.find('.header-actions').findComponent({ name: 'ElButton' })
    expect(transfer.props('disabled')).toBe(true)
    resolve({ owners: [], invalid_reason_codes: [] } as never)
    await flushPromises()
  })
  it('刷新可以替换在飞的任务和时间轴请求，旧响应不覆盖新记录', async () => {
    const wrapper = shallowMount(InquiryDetailView, { global: { plugins: [ElementPlus] } })
    wrappers.push(wrapper)
    await flushPromises()
    const vm = wrapper.vm as unknown as { loadTasks: () => Promise<void>; loadTimeline: () => Promise<void>; tasks: Array<{id: string}>; timeline: Array<{id: string}> }
    let oldTasks!: (value: never) => void
    vi.mocked(api.fetchInquiryTasks).mockImplementationOnce(() => new Promise(done => { oldTasks = done }))
      .mockResolvedValueOnce([{ id: 'new', status: 'PENDING' }] as never)
    const tasks = vm.loadTasks(); await vm.loadTasks()
    oldTasks([{ id: 'old' }] as never); await tasks
    expect(vm.tasks[0]?.id).toBe('new')
    let oldTimeline!: (value: never) => void
    vi.mocked(api.fetchInquiryTimeline).mockImplementationOnce(() => new Promise(done => { oldTimeline = done }))
      .mockResolvedValueOnce({ data: [{ id: 'new', event_data: {} }], meta: { total: 1 } } as never)
    const timeline = vm.loadTimeline(); await vm.loadTimeline()
    oldTimeline({ data: [{ id: 'old', event_data: {} }], meta: { total: 1 } } as never); await timeline
    expect(vm.timeline[0]?.id).toBe('new')
  })
  it.each([
    { status: 'SKIPPED', label: '内部上传，未扫描', disabled: false },
    { status: 'CLEAN', label: '已上传', disabled: false },
    { status: 'PENDING', label: '暂不可下载', disabled: true },
    { status: 'FAILED', label: '暂不可下载', disabled: true },
    { status: 'INFECTED', label: '暂不可下载', disabled: true },
  ])('$status 附件下载入口与扫描状态文案一致', async ({ status, label, disabled }) => {
    vi.mocked(api.fetchInquiry).mockResolvedValue({
      data: { ...detail, files: [{ id: 'link', file_id: 'file', original_name: '产品.png', size_bytes: 1024, scan_status: status }] },
      etag: 'v1',
    } as never)
    const wrapper = shallowMount(InquiryDetailView, { global: { plugins: [ElementPlus] } })
    wrappers.push(wrapper)
    await flushPromises()

    const attachment = wrapper.find<HTMLButtonElement>('button.attachment')
    expect(attachment.element.disabled).toBe(disabled)
    expect(attachment.attributes('title')).toBe(disabled ? '附件尚未通过安全扫描' : '下载 产品.png')
    expect(attachment.find('small').text()).toBe(disabled ? label : `${label} · 1.0 KB`)
  })
})
