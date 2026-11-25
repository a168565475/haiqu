import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElMessage } from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fetchSample, createSampleFeedback } from '@/api/samples'

import SampleFulfillmentView from './SampleFulfillmentView.vue'
import SampleFeedbackRequotationDialog from '@/components/samples/SampleFeedbackRequotationDialog.vue'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
const access = vi.hoisted(() => ({ allowed: true, denied: '' }))
const routerPush = vi.hoisted(() => vi.fn())
enableAutoUnmount(afterEach)

const fixtures = vi.hoisted(() => {
const shipment = {
  id: 'shipment-1', status: 'DELIVERED', status_display: '已签收', carrier_code: 'DHL', tracking_number: 'SAM-QA-001',
  recipient_summary: { recipient_name: '张**', location: '深圳' }, shipped_by: null,
  shipped_at: '2026-08-24T01:00:00Z', delivered_at: '2026-08-24T03:00:00Z', fee_warning_acknowledged: false,
  notes: '', items: [{ id: 'shipment-item-1', sample_item_id: 'item-1', product_description: '折叠椅样品', shipped_quantity: '1.0000' }], created_at: '2026-08-24T01:00:00Z', updated_at: '2026-08-24T03:00:00Z',
  events: [{
    id: 'event-1', event_type: 'DELIVERED' as const, event_type_display: '已签收', source: 'MANUAL' as const, source_display: '人工录入',
    event_identifier: 'MANUAL:1', source_object_version: 2, occurred_at: '2026-08-24T03:00:00Z', synchronized_at: '2026-08-24T03:00:00Z',
    payload_snapshot: { note: '人工签收' }, recorded_by: null, created_at: '2026-08-24T03:00:00Z',
  }],
}

const detail = {
  id: 'sample-1', request_number: 'SAM-QA-001', customer_account: 'customer-1', customer_name: 'SAM-QA 客户', owner: null,
  status: 'FEEDBACK_PENDING' as const, status_display: '待反馈', sample_type: 'PRE_PRODUCTION', sample_type_display: '产前样', etag: '"sample-v1"',
  item_summary: { text: '样品', count: 1 }, current_fee: null, latest_shipment: { status: 'DELIVERED', status_display: '已签收', carrier_code: 'DHL', tracking_number: 'SAM-QA-001', shipped_at: shipment.shipped_at, delivered_at: shipment.delivered_at },
  requested_at: '2026-08-23T01:00:00Z', requested_due_at: null, created_at: '2026-08-23T01:00:00Z', updated_at: '2026-08-24T03:00:00Z',
  transaction_entity: null, transaction_entity_name: '', customer_contact: null, customer_contact_name: '', source_inquiry: null, source_inquiry_number: '', source_quotation_version: null, source_quotation_id: null, source_quotation_number: '', purpose: '', notes: '', expected_shipped_at: null, expected_received_at: null, collaborators: [], items: [{ id: 'item-1', line_number: 1, source_inquiry_item: null, source_quotation_line: null, product_description_snapshot: '折叠椅样品', specification_snapshot: '', requested_quantity: '1.0000', unit_code: 'PCS', notes: '' }], fee_records: [], fee_approvals: [], shipments: [shipment], feedback: [], files: [], sla: [],
}
return { shipment, detail }
})

vi.mock('@/api/samples', () => ({
  fetchSample: vi.fn().mockResolvedValue({ data: fixtures.detail, etag: '"sample-v1"' }),
  createSampleFeedback: vi.fn(), transitionSample: vi.fn(),
  fetchSampleFeedbackRequotationOptions: vi.fn(), createSampleFeedbackRequotation: vi.fn(),
}))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: (permission: string) => access.allowed && permission !== access.denied, moduleCan: (permission: string, legacy = permission) => access.allowed && legacy !== access.denied }) }))
vi.mock('vue-router', () => ({ useRoute: () => ({ params: { sampleId: 'sample-1' } }), useRouter: () => ({ push: routerPush }) }))

describe('SampleFulfillmentView', () => {
  beforeEach(() => {
    vi.clearAllMocks(); access.allowed = true; access.denied = ''
    vi.mocked(fetchSample).mockResolvedValue({ data: structuredClone(fixtures.detail), etag: '"sample-v1"' })
  })
  const feedback = {
    id: 'feedback-1', feedback_content: '客户要求调整靠背', confirmation_result: 'REJECTED',
    confirmation_result_display: '确认未通过', feedback_type_display: '负向', occurred_at: '2026-09-11T00:00:00Z',
    confirmation_source_display: '客户确认', source_object_version: 1,
    resulting_quotation_id: null, resulting_quotation_version: null, resulting_quotation_label: '',
  }
  it.each(['samples.view_samplefeedback', 'quotations.view_quotation', 'quotations.view_quotationversion'])(
    '缺少 %s 时不提供无法完成读取与跳转的再报价创建入口', async permission => {
      access.denied = permission
      vi.mocked(fetchSample).mockResolvedValueOnce({ data: { ...fixtures.detail, feedback: [feedback] }, etag: '"v1"' } as never)
      const wrapper = mount(SampleFulfillmentView, { global: { plugins: [ElementPlus] } }); await flushPromises()
      expect(wrapper.find('.requote-button').exists()).toBe(false)
    },
  )
  it.each(['quotations.view_quotation', 'quotations.view_quotationversion'])(
    '缺少 %s 时不提供已有再报价的查看入口', async permission => {
      access.denied = permission
      vi.mocked(fetchSample).mockResolvedValueOnce({ data: { ...fixtures.detail, feedback: [{ ...feedback, resulting_quotation_id: 'quote-1', resulting_quotation_version: 'version-2', resulting_quotation_label: 'QUO-001 V2' }] }, etag: '"v1"' } as never)
      const wrapper = mount(SampleFulfillmentView, { global: { plugins: [ElementPlus] } }); await flushPromises()
      expect(wrapper.find('.requote-button').exists()).toBe(false)
    },
  )
  it('查看反馈生成的报价固定到保存的V2，不能随报价当前版本变化', async () => {
    access.denied = 'quotations.add_quotationversion'
    vi.mocked(fetchSample).mockResolvedValueOnce({ data: { ...fixtures.detail, feedback: [{ ...feedback, resulting_quotation_id: 'quote-1', resulting_quotation_version: 'version-2', resulting_quotation_label: 'QUO-001 V2' }] }, etag: '"v1"' } as never)
    const wrapper = mount(SampleFulfillmentView, { global: { plugins: [ElementPlus] } }); await flushPromises()
    await wrapper.get('.requote-button').trigger('click')
    expect(routerPush).toHaveBeenCalledWith({ name: 'quotation-preview', params: { quotationId: 'quote-1' }, query: { version: 'version-2' } })
  })
  it('刚创建的再报价跳转携带结果版本', async () => {
    const wrapper = mount(SampleFulfillmentView, { global: { plugins: [ElementPlus] } }); await flushPromises()
    wrapper.findComponent(SampleFeedbackRequotationDialog).vm.$emit('created', 'quote-1', '"v2"', 'version-2')
    await flushPromises()
    expect(routerPush).toHaveBeenCalledWith({ name: 'quotation-preview', params: { quotationId: 'quote-1' }, query: { version: 'version-2' } })
  })
  it('非产前样检查显示不适用，不误报产前样已确认', async () => {
    vi.mocked(fetchSample).mockResolvedValueOnce({ data: { ...fixtures.detail, sample_type: 'PRE_SALES' }, etag: '"v1"' } as never)
    const wrapper = mount(SampleFulfillmentView, { global: { plugins: [ElementPlus] } }); await flushPromises()
    expect(wrapper.findAll('.check-list > div').find(row => row.text().includes('产前样已确认'))!.text()).toContain('不适用')
  })
  it('闭环进度遵循原型，缺少订单状态时不显示已解除或阻塞中', async () => {
    const wrapper = mount(SampleFulfillmentView, { global: { plugins: [ElementPlus] } }); await flushPromises()
    expect(wrapper.findAll('.flow-step').map(item => item.text())).toEqual(['✓已寄出', '✓已签收', '3待反馈', '4客户确认', '5订单解除阻塞'])
    expect(wrapper.find('.order-panel').text()).toContain('待订单核验')
    expect(wrapper.find('.order-panel').text()).not.toContain('阻塞中')
  })
  it('样品加载失败提供重试，恢复后可记录反馈', async () => {
    vi.mocked(fetchSample).mockRejectedValueOnce(new Error('offline'))
    const wrapper = mount(SampleFulfillmentView, { global: { plugins: [ElementPlus] } }); await flushPromises()
    expect(wrapper.text()).toContain('样品物流页面加载失败')
    await wrapper.findAll('button').find(button => button.text() === '重新加载')!.trigger('click'); await flushPromises()
    expect(wrapper.text()).not.toContain('样品物流页面加载失败')
    expect(wrapper.findAll('button').find(button => button.text() === '记录反馈')!.attributes('disabled')).toBeUndefined()
  })
  it('非反馈阶段禁用记录入口，无权限时也不能操作', async () => {
    vi.mocked(fetchSample).mockResolvedValueOnce({ data: { ...fixtures.detail, status: 'PREPARING' }, etag: '"v1"' })
    const first = mount(SampleFulfillmentView, { global: { plugins: [ElementPlus] } }); await flushPromises()
    expect(first.findAll('button').find(button => button.text() === '记录反馈')!.attributes('disabled')).toBeDefined()
    access.allowed = false
    const second = mount(SampleFulfillmentView, { global: { plugins: [ElementPlus] } }); await flushPromises()
    expect(second.findAll('button').find(button => button.text() === '记录反馈')!.attributes('disabled')).toBeDefined()
  })
  it('保存反馈携带版本，期间阻止重复提交，失败保留弹窗与输入', async () => {
    const error = vi.spyOn(ElMessage, 'error').mockImplementation(() => ({ close: vi.fn() }))
    let reject!: (reason: Error) => void
    vi.mocked(createSampleFeedback).mockReturnValue(new Promise((_, fail) => { reject = fail }))
    const wrapper = mount(SampleFulfillmentView, { global: { plugins: [ElementPlus] } }); await flushPromises()
    await wrapper.findAll('button').find(button => button.text() === '记录反馈')!.trigger('click'); await flushPromises()
    const feedbackDialog = wrapper.findAllComponents(AppWindowDialog).find(dialog => dialog.props('title') === '记录客户反馈')!
    expect(feedbackDialog).toBeDefined()
    expect(feedbackDialog.props('closeOnClickModal')).toBe(false)
    feedbackDialog.findAllComponents({ name: 'ElInput' }).find(input => input.props('maxlength') === '2000')!.vm.$emit('update:modelValue', '客户确认颜色一致')
    await flushPromises()
    const save = feedbackDialog.findAllComponents({ name: 'ElButton' }).find(button => button.text() === '保存反馈')!
    await save.trigger('click'); await flushPromises()
    expect(createSampleFeedback).toHaveBeenCalledWith('sample-1', expect.objectContaining({ feedback_content: '客户确认颜色一致', confirmation_result: 'PASSED', source_object_version: 1 }), '"sample-v1"')
    expect(save.props('disabled')).toBe(true); await save.trigger('click'); expect(createSampleFeedback).toHaveBeenCalledTimes(1)
    reject(new Error('offline')); await flushPromises()
    expect(feedbackDialog.props('modelValue')).toBe(true)
    expect(error).toHaveBeenCalled(); error.mockRestore()
  })
  it('只读展示历史寄送记录、真实反馈待办和订单模块待接入提示', async () => {
    const wrapper = mount(SampleFulfillmentView, { global: { plugins: [ElementPlus] } })
    await flushPromises()
    await flushPromises()

    expect(wrapper.text()).toContain('人工录入')
    expect(wrapper.text()).toContain('客户已签收，尚未记录客户反馈')
    expect(wrapper.text()).toContain('订单模块待接入')
    expect(wrapper.text()).toContain('实际寄出')
    expect(wrapper.text()).toContain('收货地区')
    expect(wrapper.text()).toContain('实际签收')
    expect(wrapper.text()).toContain('本次寄送物料')
    expect(wrapper.text()).toContain('折叠椅样品 × 1.0000 PCS')
    expect(wrapper.text()).not.toContain('预计送达')
    expect(wrapper.text()).not.toContain('预计签收')
    expect(wrapper.text()).not.toContain('有效时效')
    for (const label of ['创建寄送记录', '确认已寄出', '更新最新进度', '手工签收', '记录异常']) {
      expect(wrapper.findAll('button').some(button => button.text() === label)).toBe(false)
    }
  })

  it('没有历史寄送记录时只显示空状态，不提供寄送入口', async () => {
    vi.mocked(fetchSample).mockResolvedValueOnce({
      data: {
        ...fixtures.detail,
        status: 'FINISHED',
        status_display: '流程已结束',
        current_fee: null,
        latest_shipment: null,
        shipments: [],
        items: [{ id: 'item-1', line_number: 1, source_inquiry_item: null, source_quotation_line: null, product_description_snapshot: '折叠椅样品', specification_snapshot: '', requested_quantity: '1.0000', unit_code: 'PCS', notes: '' }],
      },
      etag: '"sample-finished"',
    })
    const wrapper = mount(SampleFulfillmentView, { global: { plugins: [ElementPlus] } })
    await flushPromises()
    await flushPromises()

    expect(wrapper.text()).not.toContain('创建寄送记录')
    expect(wrapper.text()).toContain('暂无历史寄送记录。')
    expect(wrapper.find('.summary-grid').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('暂未维护')
    expect(wrapper.text()).not.toContain('等待运输事实')
  })

  it('历史物料进度按时间只读显示', async () => {
    const currentShipment = {
      ...fixtures.shipment,
      status: 'SHIPPED', status_display: '已寄出', delivered_at: null,
      events: [{
        id: 'event-progress-1', event_type: 'PROGRESS' as const, event_type_display: '物料进度更新', source: 'MANUAL' as const, source_display: '人工录入',
        event_identifier: 'MANUAL:progress:1', source_object_version: 2, occurred_at: '2026-08-24T02:00:00Z', synchronized_at: '2026-08-24T02:00:00Z',
        payload_snapshot: { material_status: '物料已到达转运中心' }, recorded_by: null, created_at: '2026-08-24T02:00:00Z',
      }, {
        id: 'event-progress-2', event_type: 'PROGRESS' as const, event_type_display: '物料进度更新', source: 'MANUAL' as const, source_display: '人工录入',
        event_identifier: 'MANUAL:progress:2', source_object_version: 3, occurred_at: '2026-08-24T03:00:00Z', synchronized_at: '2026-08-24T03:00:00Z',
        payload_snapshot: { material_status: '物料已完成装车' }, recorded_by: null, created_at: '2026-08-24T03:00:00Z',
      }],
    }
    vi.mocked(fetchSample).mockResolvedValueOnce({
      data: {
        ...fixtures.detail, status: 'SHIPPED', status_display: '运输中', shipments: [currentShipment],
        latest_shipment: { ...fixtures.detail.latest_shipment, status: 'SHIPPED', status_display: '已寄出', delivered_at: null },
      },
      etag: '"sample-shipped"',
    })
    const wrapper = mount(SampleFulfillmentView, { global: { plugins: [ElementPlus] } })
    await flushPromises()
    await flushPromises()

    expect(wrapper.text()).not.toContain('更新最新进度')
    expect(wrapper.text()).toContain('物料进度')
    expect(wrapper.text()).toContain('物料已到达转运中心')
    expect(wrapper.text()).toContain('物料已完成装车')
    expect(wrapper.findAll('.material-progress-timeline article')).toHaveLength(2)
    expect(wrapper.findAll('.material-progress-timeline article > span')).toHaveLength(2)
  })
})
