import { flushPromises, mount } from '@vue/test-utils'
import { reactive } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import IssuePage from './issue.vue'
import { DatePicker, TimePicker, PickerGroup, Picker } from 'vant'
import * as api from '@/api/materialIssues'
import type { MaterialRequirement } from '@/types/materialIssue'

const mocks = vi.hoisted(() => ({
  route: { query: {} as Record<string, string>, fullPath: '/issue' }, replace: vi.fn(), push: vi.fn(),
  guards: {} as Record<string, (to: { path: string; query: Record<string, string> }) => Promise<boolean>>,
}))
vi.mock('vue-router', () => ({
  useRoute: () => mocks.route, useRouter: () => ({ replace: mocks.replace, push: mocks.push }),
  onBeforeRouteLeave: (guard: typeof mocks.guards[string]) => { mocks.guards.leave = guard },
  onBeforeRouteUpdate: (guard: typeof mocks.guards[string]) => { mocks.guards.update = guard },
}))
vi.mock('vant', async importOriginal => ({ ...await importOriginal<typeof import('vant')>(), showDialog: vi.fn().mockResolvedValue('confirm') }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: () => true }) }))
vi.mock('@/utils/requestId', () => ({ createRequestId: () => 'request-one' }))
vi.mock('@/components/WorkPage.vue', () => ({ default: { template: '<div><slot /><slot name="footer" /></div>' } }))
vi.mock('@/api/materialIssues', () => ({
  createMaterialIssue: vi.fn(), fetchMaterialIssue: vi.fn(), fetchMaterialIssueOptions: vi.fn(), fetchMaterialIssueProducts: vi.fn(),
  fetchMaterialRequirements: vi.fn(), submitMaterialIssue: vi.fn(), updateMaterialIssue: vi.fn(),
}))

const ids = {
  production_task_id: '11111111-1111-4111-8111-111111111111', product_line_id: '22222222-2222-4222-8222-222222222222',
  workshop_id: '33333333-3333-4333-8333-333333333333', schedule_product_id: '44444444-4444-4444-8444-444444444444', plan_category: 'METAL',
}
const product = { id: ids.product_line_id, product_number: 'PRODUCT-TEST', product_name: '测试产品', specification: '测试规格', color: '' }
const requirement: MaterialRequirement = {
  requirement_id: 'requirement', stock_item_id: 'stock', stock_mode: 'PUBLIC_V2', line_type: 'RAW', section_code: 'HARDWARE', material_number: 'M-TEST',
  material_name: '测试材料', specification: '测试规格', color: '', unit: '件', required_quantity: '10', internal_issued_quantity: '0',
  outsourcing_issued_quantity: '0', pending_issue_quantity: '0', order_remaining: '10', available_stock: '20', max_issue_quantity: '20', validation_errors: [],
}
const draft = {
  id: '55555555-5555-4555-8555-555555555555', issue_number: 'TEST-ISSUE', status: 'DRAFT' as const, status_display: '草稿', version: 1,
  production_task: { id: ids.production_task_id, task_number: 'TEST-TASK', order_number: '' }, product,
  workshop: { id: ids.workshop_id, name: '金工车间' }, recipient: { id: 'person', name: '测试员工' }, created_by: { id: 'person', name: '测试员工' },
  issue_at: null, remark: '', line_count: 1, lines: [], submitted_at: null, issued_at: null, created_at: '', updated_at: '', audit_events: [],
}
beforeEach(() => {
  vi.resetAllMocks()
  mocks.route = reactive({ query: { ...ids }, fullPath: '/issue' })
  mocks.replace.mockImplementation(async ({ query }) => {
    if (await mocks.guards.update!({ path: '/issue', query })) { mocks.route.query = query; mocks.route.fullPath = `/issue?issue_id=${query.issue_id}` }
  })
  vi.mocked(api.fetchMaterialIssueOptions).mockResolvedValue({
    production_tasks: [{ id: ids.production_task_id, task_number: 'TEST-TASK', order_number: '' }],
    workshops: [{ id: ids.workshop_id, name: '金工车间' }], recipients: [{ id: 'person', name: '测试员工', workshop_id: ids.workshop_id }],
  })
  vi.mocked(api.fetchMaterialIssueProducts).mockResolvedValue([product])
  vi.mocked(api.fetchMaterialRequirements).mockResolvedValue({ source_revision_hash: '', blockers: [], items: [{ ...requirement }] })
  vi.mocked(api.createMaterialIssue).mockResolvedValue({ data: draft, etag: '"v1"' })
  vi.mocked(api.submitMaterialIssue).mockResolvedValue({ data: { ...draft, status: 'PENDING_REVIEW' }, etag: '"v2"' })
})

async function preparedPage() {
  const wrapper = mount(IssuePage)
  await flushPromises()
  await wrapper.get('input[inputmode="decimal"]').setValue('2')
  return wrapper
}
function submitButton(wrapper: ReturnType<typeof mount>) {
  return wrapper.findAll('button').find(button => /提交领料申请|继续提交此申请|核对并继续提交/.test(button.text()))!
}
describe('领料申请两步保存恢复', () => {
  it('非法数量输入和整段粘贴保持原值，不把科学计数法改成另一数量', async () => {
    const wrapper = await preparedPage()
    const input = wrapper.get<HTMLInputElement>('.request-field input')
    for (const value of ['2a', '中文', '-2', '+2', '1e3', '1E3', '1.2.3', '１', '2 3']) {
      await input.setValue(value)
      expect(input.element.value).toBe('2')
    }
    input.element.value = '1e3'
    await input.trigger('input', { inputType: 'insertFromPaste', data: '1e3' })
    expect(input.element.value).toBe('2')
    await submitButton(wrapper).trigger('click'); await flushPromises()
    expect(api.createMaterialIssue).toHaveBeenCalledWith(expect.objectContaining({ lines: [{ requirement_id: 'requirement', requested_quantity: '2' }] }))
    wrapper.unmount()
  })
  it('领料数量可清空，首位小数点补零，合法四位小数按原值提交', async () => {
    const wrapper = await preparedPage()
    const input = wrapper.get<HTMLInputElement>('.request-field input')
    await input.setValue('')
    expect(input.element.value).toBe('')
    await input.setValue('1e3')
    expect(input.element.value).toBe('')
    await input.setValue('.')
    expect(input.element.value).toBe('0.')
    await input.setValue('.5')
    expect(input.element.value).toBe('0.5')
    await input.setValue('1.2345')
    expect(input.element.value).toBe('1.2345')
    expect(wrapper.find('.request-field .van-field__error-message').exists()).toBe(false)
    await submitButton(wrapper).trigger('click'); await flushPromises()
    expect(api.createMaterialIssue).toHaveBeenCalledWith(expect.objectContaining({ lines: [{ requirement_id: 'requirement', requested_quantity: '1.2345' }] }))
    wrapper.unmount()
  })
  it.each<{ name: string; overrides: Partial<MaterialRequirement>; value: string; error: string }>([
    { name: '四位小数精度', overrides: {}, value: '1.23456', error: '最多四位小数' },
    { name: '管材整根倍数', overrides: { unit: '支', conversion_snapshot: { kind: 'PIPE', pieces_per_bar: 2, raw_bar_length_m: '6.00' } }, value: '3', error: '2 的正整数倍' },
    { name: '半成品整数', overrides: { line_type: 'SEMI', unit: '套' }, value: '1.5', error: '半成品支数和套数必须为正整数' },
  ])('数字输入仍保留 $name 校验，不截断数值或创建申请', async ({ overrides, value, error }) => {
    vi.mocked(api.fetchMaterialRequirements).mockResolvedValue({ source_revision_hash: '', blockers: [], items: [{ ...requirement, ...overrides }] })
    const wrapper = await preparedPage()
    const input = wrapper.get<HTMLInputElement>('.request-field input')
    await input.setValue(value)
    expect(input.element.value).toBe(value)
    expect(wrapper.get('.request-field .van-field__error-message').text()).toContain(error)
    await submitButton(wrapper).trigger('click'); await flushPromises()
    expect(api.createMaterialIssue).not.toHaveBeenCalled()
    wrapper.unmount()
  })
  it('只有半成品标签使用独立类别样式，原材料类别保持不变', async () => {
    vi.mocked(api.fetchMaterialRequirements).mockResolvedValue({ source_revision_hash: '', blockers: [], items: [
      { ...requirement },
      { ...requirement, requirement_id: 'semi', stock_item_id: 'semi-stock', line_type: 'SEMI', material_name: '测试半成品', unit: '套' },
    ] })
    const wrapper = await preparedPage()
    const tags = wrapper.findAll('.material-kind')
    expect(tags.map(tag => tag.text())).toEqual(['原材料', '半成品'])
    expect(tags[0]!.classes()).not.toContain('material-kind--semi')
    expect(tags[1]!.classes()).toContain('material-kind--semi')
    wrapper.unmount()
  })
  it('领料人使用同车间手机选择面板，取消不写回，确认后沿用原保存字段', async () => {
    vi.mocked(api.fetchMaterialIssueOptions).mockResolvedValue({
      production_tasks: [{ id: ids.production_task_id, task_number: 'TEST-TASK', order_number: '' }],
      workshops: [{ id: ids.workshop_id, name: '金工车间' }],
      recipients: [
        { id: 'person', name: '测试员工', workshop_id: ids.workshop_id },
        { id: 'person-two', name: '另一位员工', workshop_id: ids.workshop_id },
        { id: 'other-workshop', name: '其他车间员工', workshop_id: 'other' },
      ],
    })
    const wrapper = await preparedPage()
    expect(wrapper.find('select').exists()).toBe(false)
    await wrapper.get('.recipient-trigger').trigger('click'); await flushPromises()
    const picker = wrapper.getComponent(Picker)
    expect(picker.props('columns')).toEqual([{ text: '测试员工', value: 'person' }, { text: '另一位员工', value: 'person-two' }])
    expect(picker.props('visibleOptionNum')).toBe(2)
    picker.vm.$emit('update:modelValue', ['person-two']); await flushPromises()
    await picker.get('.van-picker__cancel').trigger('click'); await flushPromises()
    expect(wrapper.get('.recipient-trigger').text()).toContain('请选择领料人')
    await wrapper.get('.recipient-trigger').trigger('click'); await flushPromises()
    picker.vm.$emit('update:modelValue', ['person-two']); await flushPromises()
    await picker.get('.van-picker__confirm').trigger('click'); await flushPromises()
    expect(wrapper.get('.recipient-trigger').text()).toContain('另一位员工')
    await submitButton(wrapper).trigger('click'); await flushPromises()
    expect(api.createMaterialIssue).toHaveBeenCalledWith(expect.objectContaining({ recipient_workshop_employee_id: 'person-two' }))
    wrapper.unmount()
  })
  it('单个领料人不撑出多余选择行，空名单禁用入口并保留配置提示', async () => {
    const wrapper = await preparedPage()
    await wrapper.get('.recipient-trigger').trigger('click'); await flushPromises()
    expect(wrapper.getComponent(Picker).props('visibleOptionNum')).toBe(1)
    wrapper.unmount()
    vi.mocked(api.fetchMaterialIssueOptions).mockResolvedValue({
      production_tasks: [{ id: ids.production_task_id, task_number: 'TEST-TASK', order_number: '' }],
      workshops: [{ id: ids.workshop_id, name: '金工车间' }], recipients: [],
    })
    const empty = await preparedPage()
    expect(empty.get('.recipient-trigger').attributes('disabled')).toBeDefined()
    expect(empty.text()).toContain('当前车间没有可用领料人')
    empty.unmount()
  })
  it('数量与单位保留在 Vant 输入体中，超库存仍明确报错且不能创建', async () => {
    const wrapper = await preparedPage()
    const field = wrapper.get('.request-field')
    expect(field.get('.van-field__body input').attributes('inputmode')).toBe('decimal')
    expect(field.get('.van-field__body .request-unit').text()).toBe('件')
    await field.get('input').setValue('21'); await flushPromises()
    expect(field.get('.van-field__error-message').text()).not.toBe('')
    await submitButton(wrapper).trigger('click'); await flushPromises()
    expect(api.createMaterialIssue).not.toHaveBeenCalled()
    wrapper.unmount()
  })
  it('产品信息默认折叠且保留全部内容，使用手机时间入口', async () => {
    const wrapper = await preparedPage()
    expect(wrapper.get('details.product-card').attributes('open')).toBeUndefined()
    expect(wrapper.get('.product-summary').text()).toContain('测试产品')
    expect(wrapper.get('.product-details').text()).toContain('PRODUCT-TEST')
    expect(wrapper.find('input[type="datetime-local"]').exists()).toBe(false)
    expect(wrapper.get('.time-trigger').attributes('aria-haspopup')).toBe('dialog')
    wrapper.unmount()
  })
  it('日期跨月自动修正闰日，确认后保存北京时间且不改变请求编号', async () => {
    const wrapper = await preparedPage()
    await wrapper.get('.time-trigger').trigger('click'); await flushPromises()
    const date = wrapper.getComponent(DatePicker)
    date.vm.$emit('update:modelValue', ['2028', '01', '31']); await flushPromises()
    date.vm.$emit('update:modelValue', ['2028', '02', '31']); await flushPromises()
    expect(date.props('modelValue')).toEqual(['2028', '02', '29'])
    wrapper.getComponent(TimePicker).vm.$emit('update:modelValue', ['08', '05']); await flushPromises()
    const group = wrapper.getComponent(PickerGroup)
    await group.get('.van-picker__confirm').trigger('click'); await flushPromises()
    await group.get('.van-picker__confirm').trigger('click'); await flushPromises()
    expect(wrapper.get('.time-trigger').text()).toContain('2028-02-29 08:05')
    await submitButton(wrapper).trigger('click'); await flushPromises()
    expect(api.createMaterialIssue).toHaveBeenCalledWith(expect.objectContaining({ issue_at: '2028-02-29T08:05:00+08:00', client_request_id: 'request-one' }))
    wrapper.unmount()
  })
  it('取消日期编辑不改变领料时间，重新打开恢复已确认值', async () => {
    const wrapper = await preparedPage()
    const original = wrapper.get('.time-trigger').text()
    await wrapper.get('.time-trigger').trigger('click'); await flushPromises()
    const initialDate = [...wrapper.getComponent(DatePicker).props('modelValue')!]
    wrapper.getComponent(DatePicker).vm.$emit('update:modelValue', ['2027', '01', '31']); await flushPromises()
    wrapper.getComponent(TimePicker).vm.$emit('update:modelValue', ['12', '34']); await flushPromises()
    await wrapper.getComponent(PickerGroup).get('.van-picker__cancel').trigger('click'); await flushPromises()
    expect(wrapper.get('.time-trigger').text()).toBe(original)
    await wrapper.get('.time-trigger').trigger('click'); await flushPromises()
    expect(wrapper.getComponent(DatePicker).props('modelValue')).toEqual(initialDate)
    wrapper.unmount()
  })
  it('历史单据按北京时间回显跨日时分，超出十年窗口也不截断年份', async () => {
    mocks.route.query = { ...ids, issue_id: draft.id }
    vi.mocked(api.fetchMaterialIssue).mockResolvedValue({ data: { ...draft, issue_at: '2000-12-31T20:17:00Z' }, etag: '"v1"' })
    const wrapper = await preparedPage()
    expect(wrapper.get('.time-trigger').text()).toContain('2001-01-01 04:17')
    await wrapper.get('.time-trigger').trigger('click'); await flushPromises()
    const date = wrapper.getComponent(DatePicker)
    expect(date.props('modelValue')).toEqual(['2001', '01', '01'])
    expect(date.props('minDate')!.getFullYear()).toBeLessThanOrEqual(2001)
    expect(wrapper.getComponent(TimePicker).props('modelValue')).toEqual(['04', '17'])
    wrapper.unmount()
  })
  it('创建成功提交失败，重试只提交原单，不新建或无故修改', async () => {
    vi.mocked(api.submitMaterialIssue).mockRejectedValueOnce(new Error('仓库校验未通过'))
    const wrapper = await preparedPage()
    await submitButton(wrapper).trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('仓库校验未通过')
    expect(mocks.route.query.issue_id).toBe(draft.id)
    await submitButton(wrapper).trigger('click'); await flushPromises()
    expect(api.createMaterialIssue).toHaveBeenCalledTimes(1)
    expect(api.updateMaterialIssue).not.toHaveBeenCalled()
    expect(api.submitMaterialIssue).toHaveBeenCalledTimes(2)
    expect(wrapper.text()).toContain('申请已提交，等待仓库发料')
    wrapper.unmount()
  })
  it('创建结果不明时锁定原内容，沿用相同请求编号和内容恢复', async () => {
    vi.mocked(api.createMaterialIssue).mockRejectedValueOnce(new Error('网络中断'))
    const wrapper = await preparedPage()
    await submitButton(wrapper).trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('保存结果尚未确认')
    expect(wrapper.get('input[inputmode="decimal"]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('.time-trigger').attributes('disabled')).toBeDefined()
    expect(wrapper.get('.recipient-trigger').attributes('disabled')).toBeDefined()
    await submitButton(wrapper).trigger('click'); await flushPromises()
    const calls = vi.mocked(api.createMaterialIssue).mock.calls
    expect(calls).toHaveLength(2)
    expect(calls[1]![0]).toEqual(calls[0]![0])
    expect(calls[0]![0].client_request_id).toBe('request-one')
    expect(api.submitMaterialIssue).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })
  it('缺失作业计划上下文时显式阻断，不请求材料或保存', async () => {
    mocks.route.query = {}
    const wrapper = mount(IssuePage)
    await flushPromises()
    expect(wrapper.text()).toContain('领料入口信息不完整')
    expect(api.fetchMaterialRequirements).not.toHaveBeenCalled()
    expect(api.createMaterialIssue).not.toHaveBeenCalled()
    wrapper.unmount()
  })
  it('核对发现草稿版本变化时要求重读，不能直接提交未核对的新内容', async () => {
    vi.mocked(api.submitMaterialIssue).mockImplementationOnce(async (_id, _etag, onReconciled) => {
      onReconciled?.({ data: { ...draft, version: 2 }, etag: '"other-version"' })
      throw new Error('记录版本已变化')
    })
    const wrapper = await preparedPage()
    await submitButton(wrapper).trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('重新读取并核对数量')
    expect(submitButton(wrapper).attributes('disabled')).toBeDefined()
    expect(api.submitMaterialIssue).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })
  it('创建结果未知时阻止返回、换计划和刷新，允许身份失效后登录', async () => {
    vi.mocked(api.createMaterialIssue).mockRejectedValueOnce(new Error('网络中断'))
    const wrapper = await preparedPage()
    await submitButton(wrapper).trigger('click'); await flushPromises()
    expect(await mocks.guards.leave!({ path: '/', query: {} })).toBe(false)
    expect(await mocks.guards.update!({ path: '/issue', query: { ...ids, schedule_product_id: 'other' } })).toBe(false)
    expect(await mocks.guards.leave!({ path: '/login', query: {} })).toBe(true)
    const blocked = new Event('beforeunload', { cancelable: true })
    window.dispatchEvent(blocked)
    expect(blocked.defaultPrevented).toBe(true)
    wrapper.unmount()
    const afterUnmount = new Event('beforeunload', { cancelable: true })
    window.dispatchEvent(afterUnmount)
    expect(afterUnmount.defaultPrevented).toBe(false)
  })
  it('保存未返回时阻止离开，成功补入原单号并提交后解除保护', async () => {
    let resolveCreate!: (value: { data: typeof draft; etag: string }) => void
    vi.mocked(api.createMaterialIssue).mockReturnValueOnce(new Promise(resolve => { resolveCreate = resolve }))
    const wrapper = await preparedPage()
    await submitButton(wrapper).trigger('click'); await flushPromises()
    expect(await mocks.guards.leave!({ path: '/', query: {} })).toBe(false)
    resolveCreate({ data: draft, etag: '"v1"' }); await flushPromises()
    expect(mocks.route.query.issue_id).toBe(draft.id)
    expect(api.submitMaterialIssue).toHaveBeenCalledTimes(1)
    expect(await mocks.guards.leave!({ path: '/', query: {} })).toBe(true)
    wrapper.unmount()
  })
})
