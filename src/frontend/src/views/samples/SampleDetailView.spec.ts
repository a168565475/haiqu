import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElMessage } from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import SampleDetailView from './SampleDetailView.vue'

const api = vi.hoisted(() => ({ fetch: vi.fn(), pmc: vi.fn(), finance: vi.fn(), parameters: vi.fn(), file: vi.fn(), push: vi.fn(), permissions: null as string[] | null }))
vi.mock('vue-router', () => ({ useRoute: () => ({ params: { sampleId: 'sample-1' } }), useRouter: () => ({ push: api.push }) }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: (permission: string) => api.permissions === null || api.permissions.includes(permission), moduleCan: (permission: string, legacy = permission) => api.permissions === null || api.permissions.includes(legacy) }) }))
vi.mock('@/api/samples', () => ({ fetchSample: api.fetch, approveSamplePmc: api.pmc, confirmSampleFinance: api.finance, uploadSampleParameters: api.parameters, fetchSampleBusinessFile: api.file, transitionSample: vi.fn() }))

function response(status = 'PMC_REVIEW') {
  return { etag: '"v3"', data: {
    id: 'sample-1', etag: '"v3"', request_number: 'HTS-123', status,
    status_display: status === 'PMC_REVIEW' ? 'PMC 审核' : status,
    customer_name: '测试客户', sample_type_display: '售前样', created_at: '2026-09-10',
    products: [], items: [], fee_records: [], shipments: [], feedback: [], workflow_records: [],
    edit_capabilities: { mode: 'REPORT_ONLY', can_report_edit: true },
    workflow_actions: { can_pmc_approve: status === 'PMC_REVIEW', can_upload_metalwork: status === 'METALWORK_PENDING' },
  } }
}
const mounted: ReturnType<typeof mount>[] = []
async function render() {
  const wrapper = mount(SampleDetailView, { global: { plugins: [ElementPlus] } })
  mounted.push(wrapper)
  await flushPromises()
  return wrapper
}
beforeEach(() => {
  vi.clearAllMocks()
  api.permissions = null
  api.fetch.mockResolvedValue(response())
  vi.spyOn(ElMessage, 'success').mockImplementation(() => ({ close: vi.fn() }))
  vi.spyOn(ElMessage, 'error').mockImplementation(() => ({ close: vi.fn() }))
})
afterEach(() => { mounted.splice(0).forEach(wrapper => wrapper.unmount()); vi.restoreAllMocks() })

describe('打样详情的真实状态与操作边界', () => {
  it('旧准备状态提供费用与物流入口，新材料状态不开放旧流程', async () => {
    api.fetch.mockResolvedValue(response('PREPARING'))
    const wrapper = await render()
    await wrapper.findAll('button').find(button => button.text() === '费用处理')!.trigger('click')
    expect(api.push).toHaveBeenCalledWith('/samples/sample-1/fees')
    await wrapper.findAll('button').find(button => button.text() === '物流与反馈')!.trigger('click')
    expect(api.push).toHaveBeenCalledWith('/samples/sample-1/fulfillment')
    api.fetch.mockResolvedValue(response('MATERIALS_READY'))
    const material = await render()
    expect(material.findAll('button').some(button => ['费用处理', '物流与反馈'].includes(button.text()))).toBe(false)
  })
  it('费用和物流入口遵循权限，历史物流读取还需寄送查看权限', async () => {
    api.permissions = ['samples.view_samplerequest']
    api.fetch.mockResolvedValue(response('PREPARING'))
    expect((await render()).findAll('button').some(button => ['费用处理', '物流与反馈'].includes(button.text()))).toBe(false)
    api.permissions.push('samples.add_sampleshipment')
    expect((await render()).findAll('button').some(button => button.text() === '物流与反馈')).toBe(false)
    api.permissions = ['samples.view_samplerequest', 'samples.ship_sample']
    expect((await render()).findAll('button').some(button => button.text() === '物流与反馈')).toBe(false)
    const historical = response('FINISHED')
    api.fetch.mockResolvedValue({ ...historical, data: { ...historical.data, fee_records: [{ id: 'fee' }], shipments: [{ id: 'shipment' }] } })
    let wrapper = await render()
    expect(wrapper.findAll('button').some(button => button.text() === '费用处理')).toBe(true)
    expect(wrapper.findAll('button').some(button => button.text() === '物流与反馈')).toBe(false)
    api.permissions.push('samples.view_sampleshipment')
    wrapper = await render()
    expect(wrapper.findAll('button').some(button => button.text() === '物流与反馈')).toBe(true)
  })
  it('分区展示规格、颜色、数量与报工，保留零值和未知值的区别及历史明细', async () => {
    const detail = { id: 'detail-1', color_card: '潘通', color_name: '白色', color_code: '2322C', sample_quantity: 0, tolerance_display: '±0.5cm', notes: '核对靠背', cutting_reported_quantity: 0, metalwork_reported_quantity: 2, cutting_completed: false, metalwork_completed: true }
    const value = response('FINISHED')
    api.fetch.mockResolvedValue({ ...value, data: { ...value.data, products: [{ id: 'product-1', line_number: 1, category_name: '椅子', product_name: '折叠椅', specification: '57×61×83cm', task_sheet_file_name: '任务单.jpg', total_sample_quantity: 2, length_cm: '0', details: [detail, { ...detail, id: 'detail-2', sample_quantity: null }], sampling_details: [{ id: 'history-1', line_number: 1, detail_type: '管材', category_label: '圆管', is_selected: true, description: '保留历史要求' }] }] } })
    const wrapper = await render()
    const rows = wrapper.findAll('.product-detail-grid')
    expect(rows).toHaveLength(2)
    const fields = Object.fromEntries(rows[0]!.findAll('div').map(field => [field.find('dt').text(), field.find('dd').text()]))
    expect(fields).toMatchObject({ 规格: '57×61×83cm', 色卡: '潘通', 颜色: '白色', 色号: '2322C', 打样数量: '0 PCS', 裁剪报工: '0', 金工报工: '2', 完成状态: '裁剪否 / 金工是' })
    expect(rows[1]!.findAll('dd')[6]!.text()).toBe('—')
    expect(wrapper.find('.product-grid').text()).toContain('任务单.jpg')
    expect(wrapper.find('.historical-sampling-details').text()).toContain('保留历史要求')
    expect(wrapper.find('.historical-sampling-details').attributes('open')).toBeUndefined()
  })

  it('参数记录没有文件时保留说明，不提供无效附件操作', async () => {
    const value = response('FINISHED')
    api.fetch.mockResolvedValue({ ...value, data: { ...value.data, workflow_records: [{ id: 'parameter-1', stage: 'METALWORK_PARAMETERS', stage_display: '金工参数', note: '历史参数说明', file_id: null, file_name: '', operated_at: '2026-09-10T10:00:00Z' }] } })
    const wrapper = await render()
    expect(wrapper.find('.parameter-list').text()).toContain('历史参数说明')
    expect(wrapper.find('.parameter-list').text()).toContain('未提供附件')
    expect(wrapper.findAll('.parameter-actions button')).toHaveLength(0)
    expect(api.file).not.toHaveBeenCalled()
  })

  it('完成态合并费用物流反馈，显示真实核验状态并通过附件接口查看凭证', async () => {
    const value = response('FINISHED')
    api.fetch.mockResolvedValue({ ...value, data: { ...value.data,
      current_fee: { fee_decision_display: '收费', currency_code: 'CNY', amount: '680.00', verification_status_display: '待核验' },
      fee_records: [{ id: 'fee-1' }],
      latest_shipment: { tracking_number: 'SF1234', carrier_code: 'SF', status_display: '已签收', shipped_at: '2026-09-09T08:00:00Z', delivered_at: '2026-09-10T08:00:00Z' },
      shipments: [{ id: 'shipment-1' }],
      feedback: [{ id: 'feedback-1', feedback_type_display: '正面反馈', confirmation_result_display: '通过', feedback_content: '结构确认，等待颜色调整', recorded_by: { display_name: '业务员甲' }, occurred_at: '2026-09-10T08:00:00Z' }],
      workflow_records: [{ id: 'finance-1', stage: 'FINANCE_CONFIRMED', stage_display: '财务确认', operator: { display_name: '财务乙' }, file_id: 'file-1', file_name: '凭证.pdf', note: '凭证已登记', operated_at: '2026-09-09T08:00:00Z' }],
    } })
    const wrapper = await render()
    const section = wrapper.find('.auxiliary-card')
    expect(section.text()).toContain('CNY 680.00')
    expect(section.find('.auxiliary-heading small').text()).toBe('待核验')
    expect(section.text()).toContain('财务乙')
    expect(section.text()).toContain('SF1234')
    expect(section.text()).toContain('已签收')
    expect(section.find('.feedback-summary').text()).toContain('结构确认，等待颜色调整')
    expect(wrapper.findAll('.record-grid')).toHaveLength(0)
    api.file.mockRejectedValue(new Error('无权查看附件'))
    await section.find('.record-file').trigger('click')
    await flushPromises()
    expect(api.file).toHaveBeenCalledWith('sample-1', 'file-1')
    expect(ElMessage.error).toHaveBeenCalled()
    expect(section.text()).toContain('凭证.pdf')
  })

  it('只有费用登记时不冒充人工财务确认，并保留真实的零金额', async () => {
    const value = response('PMC_REVIEW')
    api.fetch.mockResolvedValue({ ...value, data: { ...value.data, current_fee: { fee_decision_display: '免费', currency_code: 'CNY', amount: '0.00', verification_status_display: '未核验' } } })
    const wrapper = await render()
    expect(wrapper.find('.record-grid').text()).toContain('费用登记')
    expect(wrapper.find('.record-grid').text()).not.toContain('人工备注确认')
    expect(wrapper.find('.record-grid').text()).toContain('CNY 0.00')
  })

  it('缺少服务端编辑能力时不显示编辑入口', async () => {
    const value = response()
    Reflect.deleteProperty(value.data, 'edit_capabilities')
    api.fetch.mockResolvedValue(value)
    const wrapper = await render()
    expect(wrapper.find('.detail-actions').text()).not.toMatch(/报工|编辑需求/)
    expect(wrapper.findAll('.sample-section').length).toBeGreaterThan(0)
  })

  it('兼容已进入材料待填写但尚未完善需求的新版申请，详情页不再提供独立编辑页入口', async () => {
    api.permissions = ['samples.complete_sample_requirements']
    const value = response('MATERIALS_PENDING')
    api.fetch.mockResolvedValue({ ...value, data: {
      ...value.data,
      application_actions: { is_application: true, can_director_review: false, can_resubmit: false },
      edit_capabilities: { mode: 'COMPLETE', can_full_edit: true, can_report_edit: true, can_complete: true },
    } })
    const wrapper = await render()
    expect(wrapper.find('.request-number').text()).toBe('HTS-123')
    expect(wrapper.find('.detail-actions').text()).not.toContain('编辑需求')
    expect(wrapper.text()).not.toContain('完善并提交')
    expect(api.push).not.toHaveBeenCalled()
  })

  it('PMC 审核只发一次请求并携带原 ETag，成功后显示返回的真实下一状态', async () => {
    let finish: (value: ReturnType<typeof response>) => void = () => {}
    api.pmc.mockImplementation(() => new Promise(resolve => { finish = resolve }))
    const wrapper = await render()
    const action = wrapper.find('.next-action .primary-button')
    await action.trigger('click')
    await action.trigger('click')
    expect(api.pmc).toHaveBeenCalledTimes(1)
    expect(api.pmc).toHaveBeenCalledWith('sample-1', '"v3"')
    finish(response('METALWORK_PENDING'))
    await flushPromises()
    expect(wrapper.find('.title-line').text()).toContain('METALWORK_PENDING')
    expect(wrapper.find('.next-action .primary-button').text()).toBe('上传金工参数')
  })

  it('缺失版本时拒绝审核，不发送写请求', async () => {
    const value = response()
    value.etag = ''; value.data.etag = ''
    api.fetch.mockResolvedValue(value)
    const wrapper = await render()
    await wrapper.find('.next-action .primary-button').trigger('click')
    expect(api.pmc).not.toHaveBeenCalled()
    expect(ElMessage.error).toHaveBeenCalledWith('缺少数据版本，请重新加载后重试。')
  })

  it('刷新失败保留已有内容，同时显示错误并阻止用旧版本继续审核', async () => {
    const wrapper = await render()
    api.fetch.mockRejectedValue(new Error('network'))
    const refresh = wrapper.findAll('.timeline-card button').find(button => button.text().includes('刷新'))!
    await refresh.trigger('click')
    await flushPromises()
    expect(wrapper.find('.refresh-error').text()).toContain('请求失败')
    expect(wrapper.find('.request-number').text()).toBe('HTS-123')
    expect(wrapper.find('.next-action .primary-button').attributes('disabled')).toBeDefined()
    expect(api.pmc).not.toHaveBeenCalled()
  })

  it('取消状态不会错误高亮创建阶段，完成状态不显示下一步写操作', async () => {
    api.fetch.mockResolvedValue(response('CANCELLED'))
    const cancelled = await render()
    expect(cancelled.findAll('.status-step.active')).toHaveLength(0)
    api.fetch.mockResolvedValue(response('FINISHED'))
    const finished = await render()
    expect(finished.find('.next-action .primary-button').exists()).toBe(false)
    expect(finished.find('.next-action').text()).toContain('主流程已完成')
    expect(finished.findAll('.status-step.done')).toHaveLength(7)
    expect(finished.findAll('.status-step.active')).toHaveLength(0)
  })
})
