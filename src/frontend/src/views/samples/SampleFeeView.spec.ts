import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElMessage, ElMessageBox } from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import SampleFeeView from './SampleFeeView.vue'
import { fetchSampleOptions } from '@/api/samples'
import { fetchAllMasterDataRecords } from '@/api/referenceData'

const state = vi.hoisted(() => ({ fetch: vi.fn(), save: vi.fn(), upload: vi.fn(), approve: vi.fn(), permission: true, actor: 'approver-1', leave: null as null | (() => Promise<boolean>) }))
vi.mock('@/api/samples', () => ({ fetchSample: state.fetch, createSampleFeeRecord: state.save, uploadSampleFeeEvidence: state.upload, decideSampleFeeWaiver: state.approve,
  fetchSampleOptions: vi.fn().mockResolvedValue({ fee_decisions: [{ value: 'PAID', label: '付费样' }, { value: 'FREE', label: '免费样' }, { value: 'WAIVED', label: '费用豁免' }], freight_bearers: [{ value: 'CUSTOMER', label: '客户承担' }], fee_approvers: [{ id: 'approver-1', display_name: '主管' }] }),
}))
vi.mock('@/api/referenceData', () => ({ fetchAllMasterDataRecords: vi.fn().mockResolvedValue([{ code: 'USD', chinese_name: '美元' }]) }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: () => state.permission, moduleCan: () => state.permission, user: { employee: { id: state.actor } } }) }))
vi.mock('vue-router', () => ({ useRoute: () => ({ params: { sampleId: 'sample-1' } }), useRouter: () => ({ push: vi.fn() }), onBeforeRouteLeave: (callback: () => Promise<boolean>) => { state.leave = callback }, onBeforeRouteUpdate: vi.fn() }))
function result() {
  return { etag: '"v1"', data: { id: 'sample-1', etag: '"v1"', request_number: 'SAM-001', status: 'PREPARING', customer_name: '测试客户', sample_type_display: '产前样', item_summary: { text: '折叠椅 × 2' }, owner: { id: 'owner', display_name: '业务员' },
    fee_records: [{ id: 'fee-1', fee_decision: 'PAID', requested_decision: 'PAID', fee_decision_display: '付费样', currency_code: 'USD', sample_fee_amount: '45.0000', shipping_fee_amount: '36.0000', discount_amount: '0.0000', payable_amount: '81.0000', payment_terms: '', freight_bearer: 'CUSTOMER', payment_due_at: null, verification_status: 'MANUALLY_CONFIRMED', verification_status_display: '已人工确认', decision_reason: '', superseded_at: null, created_at: '2026-09-01T00:00:00Z' }],
    fee_approvals: [] as Record<string, unknown>[], files: [] as Record<string, unknown>[],
  } }
}
const wrappers: ReturnType<typeof mount>[] = []
async function render() { const wrapper = mount(SampleFeeView, { global: { plugins: [ElementPlus] } }); wrappers.push(wrapper); await flushPromises(); return wrapper }
function submit(wrapper: ReturnType<typeof mount>) { return wrapper.find('.top-actions .el-button--primary') }
beforeEach(() => {
  vi.clearAllMocks(); state.permission = true; state.actor = 'approver-1'
  vi.mocked(fetchSampleOptions).mockResolvedValue({ fee_decisions: [{ value: 'PAID', label: '付费样' }, { value: 'FREE', label: '免费样' }, { value: 'WAIVED', label: '费用豁免' }], freight_bearers: [{ value: 'CUSTOMER', label: '客户承担' }], fee_approvers: [{ id: 'approver-1', display_name: '主管' }] } as Awaited<ReturnType<typeof fetchSampleOptions>>)
  vi.mocked(fetchAllMasterDataRecords).mockResolvedValue([{ code: 'USD', chinese_name: '美元' }] as never)
  state.fetch.mockResolvedValue(result()); state.save.mockResolvedValue({ etag: '"v2"' }); state.upload.mockResolvedValue({ etag: '"v2"' }); state.approve.mockResolvedValue({ etag: '"v2"' })
  for (const method of ['success', 'error', 'warning'] as const) vi.spyOn(ElMessage, method).mockImplementation(() => ({ close: vi.fn() }))
})
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()); vi.restoreAllMocks() })

describe('样品费用按原型登记与审批', () => {
  it('重新打开豁免记录回填审批人，修改原因即可提交', async () => {
    const data = result()
    Object.assign(data.data.fee_records[0]!, { requested_decision: 'WAIVED', fee_decision: 'PENDING', approval_status: 'PENDING', decision_reason: '原豁免原因' })
    data.data.fee_approvals.push({ id: 'link', approval_id: 'approval-current', status: 'PENDING', approver: { id: 'approver-1', display_name: '主管' }, created_at: '2026-09-11' })
    state.fetch.mockResolvedValue(data)
    const wrapper = await render()
    await wrapper.get('textarea[aria-label="业务理由与备注"]').setValue('修改后的豁免原因')
    await submit(wrapper).trigger('click'); await flushPromises()
    expect(state.save).toHaveBeenCalledWith('sample-1', expect.objectContaining({ fee_decision: 'WAIVED', approver_employee_id: 'approver-1', decision_reason: '修改后的豁免原因' }), '"v1"')
  })
  it('已寄送记录允许补传凭证，但不开放费用修改', async () => {
    const data = result(); data.data.status = 'SHIPPED'; state.fetch.mockResolvedValue(data)
    const wrapper = await render()
    expect(submit(wrapper).attributes('disabled')).toBeDefined()
    expect(wrapper.find('.el-upload button').attributes('disabled')).toBeUndefined()
    const input = wrapper.get('input[type=file]'); const file = new File(['proof'], '付款.png')
    Object.defineProperty(input.element, 'files', { value: [file], configurable: true }); await input.trigger('change'); await flushPromises()
    expect(state.upload).toHaveBeenCalledWith('sample-1', file, '"v1"')
  })
  it('收费决定覆盖旧豁免申请后，不将历史审批当作当前审批', async () => {
    const data = result(); data.data.fee_approvals.push({ id: 'old', approval_id: 'old', status: 'PENDING', status_display: '待审批', approver: { id: 'approver-1' }, created_at: '2026-08-01' }); state.fetch.mockResolvedValue(data)
    const wrapper = await render(); expect(wrapper.find('.approval-actions').exists()).toBe(false)
    expect(wrapper.findAll('.approval-step')[1]!.text()).toContain('无需审批')
  })
  it('保留费用选择、四列字段结构和真实财务状态', async () => {
    const wrapper = await render()
    expect(wrapper.attributes('data-visual-reference')).toBe('258:5218')
    expect(wrapper.findAll('.decision-choice')).toHaveLength(3)
    expect(wrapper.findAll('.fee-form-grid .el-form-item')).toHaveLength(10)
    expect(wrapper.find('.title-line').text()).toContain('已人工确认')
    expect(wrapper.find('.title-line').text()).not.toContain('待财务确认')
    expect(wrapper.find('.top-actions button:nth-child(2)').attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('支持 PDF、JPG、PNG，单个文件不超过 10MB。')
  })
  it('使用数据版本保存，提交期间禁止重复提交和修改', async () => {
    let resolve!: (value: { etag: string }) => void
    state.save.mockReturnValue(new Promise(done => { resolve = done }))
    const wrapper = await render(); await wrapper.get('input[aria-label="样品费"]').setValue('52.125'); await submit(wrapper).trigger('click')
    expect(state.save).toHaveBeenCalledWith('sample-1', expect.objectContaining({ sample_fee_amount: '52.125', currency_code: 'USD', freight_bearer: 'CUSTOMER', verification_status: 'PENDING' }), '"v1"')
    expect(submit(wrapper).attributes('disabled')).toBeDefined()
    expect(wrapper.get('input[aria-label="样品费"]').attributes('disabled')).toBeDefined()
    await submit(wrapper).trigger('click'); expect(state.save).toHaveBeenCalledTimes(1)
    resolve({ etag: '"v2"' }); await flushPromises()
  })
  it('上传凭证刷新版本，保留未保存金额和离开提醒', async () => {
    const wrapper = await render(); await wrapper.get('input[aria-label="样品费"]').setValue('68.25')
    const next = result(); next.etag = '"v2"'; next.data.files.push({ id: 'evidence', original_name: '付款.pdf', file_role: 'FEE_EVIDENCE', scan_status: 'CLEAN' }); state.fetch.mockResolvedValue(next)
    const fileInput = wrapper.get('input[type=file]'); const file = new File(['proof'], '付款.pdf', { type: 'application/pdf' })
    Object.defineProperty(fileInput.element, 'files', { value: [file], configurable: true }); await fileInput.trigger('change'); await flushPromises()
    expect(state.upload).toHaveBeenCalledWith('sample-1', file, '"v1"')
    expect((wrapper.get('input[aria-label="样品费"]').element as HTMLInputElement).value).toBe('68.25')
    expect(wrapper.find('.evidence-file').text()).toContain('付款.pdf')
    vi.spyOn(ElMessageBox, 'confirm').mockRejectedValue('cancel'); expect(await state.leave?.()).toBe(false)
    await submit(wrapper).trigger('click'); await flushPromises()
    expect(state.save).toHaveBeenCalledWith('sample-1', expect.objectContaining({ sample_fee_amount: '68.25', verification_status: 'EVIDENCE_UPLOADED' }), '"v2"')
  })
  it('无权限和终态禁用输入、提交和上传', async () => {
    state.permission = false; const denied = await render(); expect(denied.get('input[aria-label="样品费"]').attributes('disabled')).toBeDefined(); expect(submit(denied).attributes('disabled')).toBeDefined()
    state.permission = true; const finished = result(); finished.data.status = 'FINISHED'; state.fetch.mockResolvedValue(finished)
    const wrapper = await render(); expect(submit(wrapper).attributes('disabled')).toBeDefined(); expect(wrapper.find('.el-upload button').attributes('disabled')).toBeDefined()
  })
  it('仅指定审批人能使用真实审批编号和版本审批', async () => {
    const data = result(); Object.assign(data.data.fee_records[0]!, { requested_decision: 'WAIVED', approval_status: 'PENDING' }); data.data.fee_approvals.push({ id: 'link', approval_id: 'approval-123', status: 'PENDING', status_display: '待审批', approver: { id: 'approver-1', display_name: '主管' }, created_at: '2026-09-01', request_reason: '长期合作' }); state.fetch.mockResolvedValue(data)
    state.actor = 'other'; expect((await render()).find('.approval-actions').exists()).toBe(false)
    state.actor = 'approver-1'; const wrapper = await render(); await wrapper.get('.approval-actions .el-button--primary').trigger('click'); await flushPromises()
    expect(state.approve).toHaveBeenCalledWith('sample-1', 'approval-123', true, '"v1"')
  })
  it('非法金额、免费确认人和数据版本缺失时不提交', async () => {
    const wrapper = await render(); await wrapper.get('input[aria-label="样品费"]').setValue('12abc'); await submit(wrapper).trigger('click')
    expect(state.save).not.toHaveBeenCalled(); expect(ElMessage.warning).toHaveBeenCalled()
    await wrapper.findAll('.decision-choice')[1]!.trigger('click'); await submit(wrapper).trigger('click'); expect(state.save).not.toHaveBeenCalled()
    const noVersion = result(); noVersion.etag = ''; noVersion.data.etag = ''; state.fetch.mockResolvedValue(noVersion)
    const stale = await render(); await submit(stale).trigger('click'); expect(state.save).not.toHaveBeenCalled()
  })
  it('凭证刷新失败时显示错误并阻止提交，重试保留输入', async () => {
    const wrapper = await render(); await wrapper.get('input[aria-label="样品费"]').setValue('99'); state.fetch.mockRejectedValueOnce(new Error('offline'))
    const input = wrapper.get('input[type=file]'); Object.defineProperty(input.element, 'files', { value: [new File(['proof'], '付款.png')], configurable: true }); await input.trigger('change'); await flushPromises()
    expect(wrapper.find('[role=alert]').exists()).toBe(true); expect(submit(wrapper).attributes('disabled')).toBeDefined()
    await wrapper.get('.fee-error button').trigger('click'); await flushPromises()
    expect(wrapper.find('.fee-error').exists()).toBe(false); expect((wrapper.get('input[aria-label="样品费"]').element as HTMLInputElement).value).toBe('99')
  })
  it('无效或空凭证不发送上传请求', async () => {
    const wrapper = await render(); const input = wrapper.get('input[type=file]')
    for (const file of [new File(['invalid'], '附件.exe'), new File([], '空.pdf')]) { Object.defineProperty(input.element, 'files', { value: [file], configurable: true }); await input.trigger('change'); await flushPromises() }
    expect(state.upload).not.toHaveBeenCalled()
  })
})

