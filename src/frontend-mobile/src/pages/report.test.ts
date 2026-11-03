import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import type { VueWrapper } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { Button, Cell, DatePicker, Empty, Field, Icon, Loading, Popup, Radio, RadioGroup, Search, showConfirmDialog } from 'vant'
import type { ReportingContext, ReportingScheme } from '@/types/reporting'

const api = vi.hoisted(() => ({ context: vi.fn(), scheme: vi.fn(), create: vi.fn() }))
const actor = vi.hoisted(() => ({ id: 1 }))
vi.mock('@/api/reporting', () => ({ fetchReportingContext: api.context, fetchReportingScheme: api.scheme, createWorkReport: api.create }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ user: actor, hasPermission: () => true }) }))
vi.mock('@/utils/requestId', () => ({ createRequestId: () => 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa' }))
vi.mock('vant', async (importOriginal) => ({ ...await importOriginal<typeof import('vant')>(), showConfirmDialog: vi.fn().mockResolvedValue('confirm'), showDialog: vi.fn().mockResolvedValue('confirm') }))
import ReportView from './report.vue'

const query = { schedule_product_id: '11111111-1111-4111-8111-111111111111', workshop_id: '22222222-2222-4222-8222-222222222222', craft_id: '33333333-3333-4333-8333-333333333333', plan_category: 'METAL' }
const memoryKey = (userId = 1) => `haiqu-mobile:report-employees:${JSON.stringify([userId, query.workshop_id, query.craft_id])}`
function clearEmployeeMemory() { for (const id of [1, 2]) localStorage.removeItem(memoryKey(id)) }
const reportContext: ReportingContext = {
  schedule_product: { id: query.schedule_product_id, product_line_id: 'product', production_task_id: 'task', task_number: 'SC-TEST', order_number: 'SO-TEST', product_name: '测试产品', product_number: 'P-TEST', product_specification: '测试规格', product_color: '测试颜色', planned_quantity: '100', order_quantity: '100', unit_name: '件' },
  workshops: [{ id: query.workshop_id, name: '金工车间' }],
  crafts: [{ id: query.craft_id, name: '加工', workshop_id: query.workshop_id, plan_category: 'METAL' }],
  employees: [{ id: 'worker-a', name: '测试员工甲', workshop_id: query.workshop_id }, { id: 'worker-b', name: '测试员工乙', workshop_id: query.workshop_id }],
}
const reportingScheme: ReportingScheme = {
  id: 'scheme', scheme_number: 'WAGE-TEST', status: 'APPROVED', version: 1, revision: 2, product_line_id: 'product', workshop: reportContext.workshops[0], scope_craft: reportContext.crafts[0],
  lines: [{ id: 'line', work_item_id: 'work', display_name: '椅脚', operation_name: '切割', craft_name: '加工', production_description: '按定位线切割', unit_name: '次', required_quantity: '100.0000', cumulative_quantity: '60.0000', declared_price: '1.0000', status: 'ACTIVE' }],
}
const multipleOperations: ReportingScheme = {
  ...reportingScheme,
  lines: [
    { ...reportingScheme.lines[0] },
    { ...reportingScheme.lines[0], id: 'line-two', work_item_id: 'work-two', display_name: '椅背', operation_name: '打孔', cumulative_quantity: '0.0000' },
    { ...reportingScheme.lines[0], id: 'void-line', work_item_id: 'void-work', display_name: '停用工序', status: 'VOID' },
  ],
}
let wrapper: VueWrapper | undefined
async function openPage(params: Record<string, string> = query) {
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/', component: { template: '<div>任务列表</div>' } }, { path: '/report', component: ReportView }, { path: '/report-records', component: { template: '<div>记录</div>' } }] })
  await router.push({ path: '/report', query: params })
  await router.isReady()
  wrapper = mount({ template: '<router-view />' }, { global: { plugins: [router], components: { VanButton: Button, VanCell: Cell, VanDatePicker: DatePicker, VanEmpty: Empty, VanField: Field, VanIcon: Icon, VanLoading: Loading, VanPopup: Popup, VanRadio: Radio, VanRadioGroup: RadioGroup, VanSearch: Search } } })
  await flushPromises()
  return wrapper
}
async function fillEmployee(view: VueWrapper, index: number, name: string) {
  const fields = view.findAllComponents(Field).filter(field => field.props('label') === '员工')
  await fields[index].trigger('click')
  await flushPromises()
  const option = view.findAll('.report-picker-options .van-cell').find(cell => cell.text().includes(name))
  expect(option).toBeTruthy()
  await option!.trigger('click')
  await flushPromises()
}
async function fillQuantity(view: VueWrapper, index: number, value: string) {
  await view.findAllComponents(Field).filter(field => field.props('label') === '本次次数')[index].find('input').setValue(value)
}
async function clickButton(view: VueWrapper, text: string) {
  const button = view.findAllComponents(Button).find(item => item.text() === text)
  expect(button).toBeTruthy()
  await button!.trigger('click')
  await flushPromises()
}
async function openDatePicker(view: VueWrapper, value?: string) {
  await view.get('#report-production-date').trigger('click'); await flushPromises()
  const picker = view.getComponent(DatePicker)
  if (value) {
    picker.vm.$emit('update:modelValue', value.split('-'))
    await flushPromises()
  }
  return picker
}
async function chooseDate(view: VueWrapper, value: string) {
  const picker = await openDatePicker(view, value)
  await picker.get('.van-picker__confirm').trigger('click'); await flushPromises()
}
beforeEach(() => {
  actor.id = 1
  clearEmployeeMemory()
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
  vi.clearAllMocks()
  vi.mocked(showConfirmDialog).mockReset().mockResolvedValue('confirm')
  api.context.mockResolvedValue(structuredClone(reportContext))
  api.scheme.mockResolvedValue(structuredClone(reportingScheme))
  api.create.mockResolvedValue({ id: 'report', report_number: 'WR-TEST', production_date: '2026-10-31', lines: [{}], total_amount: '10.00', completed_plan: false })
})
afterEach(async () => {
  wrapper?.unmount(); wrapper = undefined
  // Vant 导航栏仍有延迟测高任务，在 jsdom 销毁前完成它们。
  try { await vi.runOnlyPendingTimersAsync() }
  finally { vi.useRealTimers(); vi.restoreAllMocks(); clearEmployeeMemory() }
})

describe('手机报工页面', () => {
  it('成功后只合并本次员工，换版按工作项恢复员工且次数仍为空', async () => {
    localStorage.setItem(memoryKey(), JSON.stringify({ 'work-two': 'worker-b', 'old-work': 'worker-a' }))
    api.scheme.mockResolvedValueOnce(structuredClone(multipleOperations))
    const view = await openPage()
    await fillEmployee(view, 0, '测试员工甲')
    await fillQuantity(view, 0, '10')
    await clickButton(view, '提交报工')
    expect(JSON.parse(localStorage.getItem(memoryKey())!)).toEqual({ work: 'worker-a', 'work-two': 'worker-b', 'old-work': 'worker-a' })
    view.unmount(); wrapper = undefined
    const nextVersion = structuredClone(multipleOperations)
    nextVersion.id = 'scheme-next'
    nextVersion.version = 2
    nextVersion.lines[0].id = 'line-next-version'
    api.scheme.mockResolvedValueOnce(nextVersion)
    const reopened = await openPage()
    expect(reopened.findAll<HTMLInputElement>('.report-choice input').map(input => input.element.value)).toEqual(['测试员工甲', '测试员工乙'])
    expect(reopened.findAll<HTMLInputElement>('.report-quantity input').map(input => input.element.value)).toEqual(['', ''])
    expect(reopened.get('.report-submit-count').text()).toContain('0')
  })
  it('仅默认员工不算本次填写或未保存内容，填写次数后只提交对应工序', async () => {
    localStorage.setItem(memoryKey(), JSON.stringify({ work: 'worker-a', 'work-two': 'worker-b' }))
    api.scheme.mockResolvedValue(structuredClone(multipleOperations))
    const view = await openPage()
    const unload = new Event('beforeunload', { cancelable: true })
    window.dispatchEvent(unload)
    expect(unload.defaultPrevented).toBe(false)
    await clickButton(view, '提交报工')
    expect(view.text()).toContain('请至少填写一道工序的报工。')
    expect(api.create).not.toHaveBeenCalled()
    await chooseDate(view, '2027-01-31')
    expect(showConfirmDialog).not.toHaveBeenCalled()
    await fillQuantity(view, 0, '10')
    await clickButton(view, '提交报工')
    expect(api.create).toHaveBeenCalledWith(expect.objectContaining({ lines: [
      { scheme_line_id: 'line', workshop_employee_id: 'worker-a', production_line: null, quantity: '10' },
    ] }))
  })
  it('手动改默认员工仍按半填校验，清空本工序不改写历史记忆', async () => {
    localStorage.setItem(memoryKey(), JSON.stringify({ work: 'worker-a' }))
    const view = await openPage()
    await fillEmployee(view, 0, '测试员工乙')
    const unload = new Event('beforeunload', { cancelable: true })
    window.dispatchEvent(unload)
    expect(unload.defaultPrevented).toBe(true)
    await clickButton(view, '提交报工')
    expect(view.get('.report-quantity .van-field__error-message').text()).toContain('大于 0 的整数次数')
    expect(api.create).not.toHaveBeenCalled()
    await view.get('.report-choice').trigger('click'); await flushPromises()
    const clear = view.findAll('.report-picker-options .van-cell').find(cell => cell.text().includes('清空本工序'))!
    await clear.trigger('click'); await flushPromises()
    expect(view.get<HTMLInputElement>('.report-choice input').element.value).toBe('')
    expect(view.get('.report-submit-count').text()).toContain('0')
    expect(JSON.parse(localStorage.getItem(memoryKey())!)).toEqual({ work: 'worker-a' })
    const clearedUnload = new Event('beforeunload', { cancelable: true })
    window.dispatchEvent(clearedUnload)
    expect(clearedUnload.defaultPrevented).toBe(false)
  })
  it.each(['另一账号', '失效员工', '其他车间员工', '其他工作项'])('不回填%s的员工记忆', async (reason) => {
    localStorage.setItem(memoryKey(), JSON.stringify({ work: reason === '失效员工' ? 'removed-worker' : 'worker-a' }))
    if (reason === '另一账号') actor.id = 2
    if (reason === '其他车间员工') {
      const context = structuredClone(reportContext)
      context.employees[0].workshop_id = 'other-workshop'
      api.context.mockResolvedValueOnce(context)
    }
    if (reason === '其他工作项') {
      const changed = structuredClone(reportingScheme)
      changed.lines[0].work_item_id = 'other-work'
      api.scheme.mockResolvedValueOnce(changed)
    }
    const view = await openPage()
    expect(view.get<HTMLInputElement>('.report-choice input').element.value).toBe('')
    expect(view.get<HTMLInputElement>('.report-quantity input').element.value).toBe('')
  })
  it.each(['取消', '明确失败', '结果未明'])('%s时不覆盖员工记忆，结果未明须重试成功才更新', async (result) => {
    localStorage.setItem(memoryKey(), JSON.stringify({ work: 'worker-a' }))
    if (result === '取消') vi.mocked(showConfirmDialog).mockRejectedValueOnce('cancel')
    else api.create.mockRejectedValueOnce(result === '明确失败'
      ? Object.assign(new Error('数量已变化'), { response: { status: 409 } }) : new Error('timeout'))
    const view = await openPage()
    await fillEmployee(view, 0, '测试员工乙')
    await fillQuantity(view, 0, '10')
    await clickButton(view, '提交报工')
    expect(JSON.parse(localStorage.getItem(memoryKey())!)).toEqual({ work: 'worker-a' })
    if (result === '取消') expect(api.create).not.toHaveBeenCalled()
    if (result === '结果未明') {
      await clickButton(view, '核对并重试本次报工')
      expect(JSON.parse(localStorage.getItem(memoryKey())!)).toEqual({ work: 'worker-b' })
    }
  })
  it('损坏记忆显示提醒，手动成功报工后恢复可用记忆', async () => {
    localStorage.setItem(memoryKey(), '{broken')
    const view = await openPage()
    expect(view.text()).toContain('无法读取上次员工，请手动选择；成功报工后会重新记住。')
    expect(view.get<HTMLInputElement>('.report-choice input').element.value).toBe('')
    await fillEmployee(view, 0, '测试员工甲')
    await fillQuantity(view, 0, '10')
    await clickButton(view, '提交报工')
    expect(view.text()).toContain('报工已提交')
    expect(view.text()).not.toContain('无法读取上次员工')
    expect(JSON.parse(localStorage.getItem(memoryKey())!)).toEqual({ work: 'worker-a' })
  })
  it('保存员工偏好失败仍显示真实报工成功，不提供重复提交入口', async () => {
    const view = await openPage()
    await fillEmployee(view, 0, '测试员工甲')
    await fillQuantity(view, 0, '10')
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('storage blocked') })
    await clickButton(view, '提交报工')
    expect(view.text()).toContain('报工已提交')
    expect(view.text()).toContain('报工已成功，但未能记住员工，下次请重新选择。')
    expect(view.text()).not.toContain('核对并重试本次报工')
    expect(api.create).toHaveBeenCalledTimes(1)
  })
  it('报工拒绝非整数输入和整段粘贴，允许清空并提交合法整数', async () => {
    const view = await openPage()
    await fillEmployee(view, 0, '测试员工甲')
    await fillQuantity(view, 0, '10')
    const field = view.findAllComponents(Field).find(item => item.props('label') === '本次次数')!
    const input = field.get<HTMLInputElement>('input')
    for (const value of ['10a', '中文', '-10', '+10', '1e3', '1E3', '1.5', '1.2.3', '.', '１', '1 0', '00000000000001e3', '123456789012345']) {
      await input.setValue(value)
      expect(input.element.value).toBe('10')
      expect(field.props('modelValue')).toBe('10')
    }
    input.element.value = '00000000000001e3'
    await input.trigger('input', { inputType: 'insertFromPaste', data: '00000000000001e3' })
    expect(input.element.value).toBe('10')
    await input.setValue('')
    expect(input.element.value).toBe('')
    expect(field.props('modelValue')).toBe('')
    await input.setValue('1.5')
    expect(input.element.value).toBe('')
    await input.setValue('12')
    await clickButton(view, '提交报工')
    expect(api.create).toHaveBeenCalledWith(expect.objectContaining({ lines: [
      { scheme_line_id: 'line', workshop_employee_id: 'worker-a', production_line: null, quantity: '12' },
    ] }))
  })
  it('数字输入仍拒绝超过剩余次数和零次数，不创建报工', async () => {
    const view = await openPage()
    await fillEmployee(view, 0, '测试员工甲')
    await fillQuantity(view, 0, '41')
    await clickButton(view, '提交报工')
    expect(view.get('.report-quantity .van-field__error-message').text()).toContain('最多可报 40')
    expect(api.create).not.toHaveBeenCalled()
    await fillQuantity(view, 0, '0')
    await clickButton(view, '提交报工')
    expect(view.get('.report-quantity .van-field__error-message').text()).toContain('大于 0 的整数次数')
    expect(api.create).not.toHaveBeenCalled()
  })
  it('产品默认折叠，展开收起保留原信息和已填明细且不重复请求', async () => {
    const detailContext = structuredClone(reportContext)
    detailContext.schedule_product!.order_quantity = '200'
    api.context.mockResolvedValueOnce(detailContext)
    const view = await openPage()
    const productDetails = view.get<HTMLDetailsElement>('details.report-context')
    expect(productDetails.element.open).toBe(false)
    expect(productDetails.get('summary').text()).toContain('测试产品')
    expect(productDetails.get('summary').text()).toContain('SC-TEST')
    await fillEmployee(view, 0, '测试员工甲')
    await fillQuantity(view, 0, '12')
    const date = view.get('#report-production-date').text()
    const contextCalls = api.context.mock.calls.length
    const schemeCalls = api.scheme.mock.calls.length

    await productDetails.get('summary').trigger('click'); await flushPromises()
    expect(productDetails.element.open).toBe(true)
    const content = productDetails.get('.report-product-details')
    for (const text of ['SC-TEST', 'P-TEST', '测试规格', '测试颜色', '记录人：当前登录员工', '查看报工记录']) {
      expect(content.text()).toContain(text)
    }
    expect(content.findAll('dl > div').map(item => [item.get('dt').text(), item.get('dd').text()])).toEqual([
      ['计划数量', '100 件'], ['订单数量', '200 件'],
    ])
    await productDetails.get('summary').trigger('click'); await flushPromises()
    expect(productDetails.element.open).toBe(false)
    const fields = view.findAllComponents(Field)
    expect(fields.find(field => field.props('label') === '员工')!.props('modelValue')).toBe('测试员工甲')
    expect(view.get('.report-operation-name').text()).toContain('椅脚')
    expect(view.get('.report-operation-name').text()).toContain('切割')
    expect(fields.find(field => field.props('label') === '本次次数')!.get<HTMLInputElement>('input').element.value).toBe('12')
    expect(view.get('#report-production-date').text()).toBe(date)
    expect(view.get('.report-line-details').text()).not.toContain('WAGE-TEST')
    expect(view.get('.report-line-details').text()).not.toContain('第 1 版')
    expect(view.get('.report-line-details').text()).toContain('工价')
    expect(api.context).toHaveBeenCalledTimes(contextCalls)
    expect(api.scheme).toHaveBeenCalledTimes(schemeCalls)
    expect(api.create).not.toHaveBeenCalled()
  })
  it('缺少范围时显示恢复入口，不请求未过滤上下文', async () => {
    const view = await openPage({})
    expect(view.text()).toContain('返回任务列表重新选择')
    expect(api.context).not.toHaveBeenCalled()
    expect(api.create).not.toHaveBeenCalled()
  })
  it('默认列出所有有效工序，每道工序固定一张卡片并分别提交员工与次数', async () => {
    api.scheme.mockResolvedValueOnce(structuredClone(multipleOperations))
    const view = await openPage()
    const cards = view.findAll('.report-entry')
    expect(cards).toHaveLength(2)
    expect(cards[0].get('.report-operation-name').text()).toContain('椅脚')
    expect(cards[0].get('.report-operation-name').text()).toContain('切割')
    expect(cards[1].get('.report-operation-name').text()).toContain('椅背')
    expect(cards[1].get('.report-operation-name').text()).toContain('打孔')
    expect(view.text()).not.toContain('停用工序')
    expect(view.findAll('button').some(button => /添加一条报工|移除/.test(button.text()))).toBe(false)
    expect(view.findAllComponents(Field).some(field => field.props('label') === '工序')).toBe(false)
    await fillEmployee(view, 0, '测试员工甲')
    await fillQuantity(view, 0, '10')
    await fillEmployee(view, 1, '测试员工乙')
    await fillQuantity(view, 1, '12')
    await clickButton(view, '提交报工')
    expect(api.create).toHaveBeenCalledWith(expect.objectContaining({ scheme_revision: 2, lines: [
      { scheme_line_id: 'line', workshop_employee_id: 'worker-a', production_line: null, quantity: '10' },
      { scheme_line_id: 'line-two', workshop_employee_id: 'worker-b', production_line: null, quantity: '12' },
    ] }))
    expect(view.text()).toContain('报工已提交')
  })
  it('未填写工序直接跳过，只核对并提交已填写的工序', async () => {
    api.scheme.mockResolvedValueOnce(structuredClone(multipleOperations))
    const view = await openPage()
    await fillEmployee(view, 1, '测试员工乙')
    await fillQuantity(view, 1, '12')
    await clickButton(view, '提交报工')
    expect(showConfirmDialog).toHaveBeenCalledWith(expect.objectContaining({ message: expect.stringContaining('1 条报工') }))
    expect(api.create).toHaveBeenCalledWith(expect.objectContaining({ lines: [
      { scheme_line_id: 'line-two', workshop_employee_id: 'worker-b', production_line: null, quantity: '12' },
    ] }))
  })
  it.each(['仅员工', '仅数量'])('已有完整工序时仍检查%s的半填卡片，不静默丢弃', async (mode) => {
    api.scheme.mockResolvedValueOnce(structuredClone(multipleOperations))
    const view = await openPage()
    await fillEmployee(view, 0, '测试员工甲')
    await fillQuantity(view, 0, '10')
    if (mode === '仅员工') await fillEmployee(view, 1, '测试员工乙')
    else await fillQuantity(view, 1, '12')
    await clickButton(view, '提交报工')
    const incomplete = view.findAll('.report-entry')[1]
    const field = incomplete.get(mode === '仅员工' ? '.report-quantity' : '.report-choice')
    expect(field.get('.van-field__error-message').text()).toContain(mode === '仅员工' ? '大于 0 的整数次数' : '请选择本车间员工')
    expect(showConfirmDialog).not.toHaveBeenCalled()
    expect(api.create).not.toHaveBeenCalled()
  })
  it('所有工序均未填写时给出明确提示，不发起确认或保存', async () => {
    api.scheme.mockResolvedValueOnce(structuredClone(multipleOperations))
    const view = await openPage()
    await clickButton(view, '提交报工')
    expect(view.text()).toContain('请至少填写一道工序的报工。')
    expect(showConfirmDialog).not.toHaveBeenCalled()
    expect(api.create).not.toHaveBeenCalled()
  })
  it('清空本工序保留固定卡片并跳过提交，不影响其他工序', async () => {
    const assemblyContext = structuredClone(reportContext)
    assemblyContext.workshops[0].name = '装配车间'
    api.context.mockResolvedValueOnce(assemblyContext)
    api.scheme.mockResolvedValueOnce(structuredClone(multipleOperations))
    const view = await openPage()
    await fillEmployee(view, 0, '测试员工甲')
    await fillQuantity(view, 0, '10')
    await fillEmployee(view, 1, '测试员工乙')
    await fillQuantity(view, 1, '12')
    view.findAllComponents(RadioGroup)[0].vm.$emit('update:modelValue', 1)
    view.findAllComponents(RadioGroup)[1].vm.$emit('update:modelValue', 2)
    await flushPromises()
    const employee = view.findAllComponents(Field).filter(field => field.props('label') === '员工')[0]
    await employee.trigger('click'); await flushPromises()
    const clear = view.findAll('.report-picker-options .van-cell').find(cell => cell.text().includes('清空本工序'))
    expect(clear).toBeTruthy()
    await clear!.trigger('click'); await flushPromises()
    const cards = view.findAll('.report-entry')
    expect(cards).toHaveLength(2)
    expect(cards[0].get<HTMLInputElement>('.report-choice input').element.value).toBe('')
    expect(cards[0].get<HTMLInputElement>('.report-quantity input').element.value).toBe('')
    expect(cards[0].getComponent(RadioGroup).props('modelValue')).toBeNull()
    expect(cards[1].get<HTMLInputElement>('.report-choice input').element.value).toBe('测试员工乙')
    expect(cards[1].get<HTMLInputElement>('.report-quantity input').element.value).toBe('12')
    expect(cards[1].getComponent(RadioGroup).props('modelValue')).toBe(2)
    await clickButton(view, '提交报工')
    expect(api.create).toHaveBeenCalledWith(expect.objectContaining({ lines: [
      { scheme_line_id: 'line-two', workshop_employee_id: 'worker-b', production_line: 2, quantity: '12' },
    ] }))
  })
  it('刷新按工序编号保留填写内容，重排和新增不串行，停用已填工序明确提示', async () => {
    api.scheme.mockResolvedValueOnce(structuredClone(multipleOperations))
    api.create.mockRejectedValueOnce(Object.assign(new Error('工价已更新，请刷新'), { response: { status: 409 } }))
    const view = await openPage()
    await fillEmployee(view, 0, '测试员工甲')
    await fillQuantity(view, 0, '10')
    await fillEmployee(view, 1, '测试员工乙')
    await fillQuantity(view, 1, '12')
    await clickButton(view, '提交报工')
    const added = { ...reportingScheme.lines[0], id: 'line-new', work_item_id: 'work-new', display_name: '新增部位', operation_name: '组装' }
    api.scheme.mockResolvedValueOnce({ ...multipleOperations, revision: 3, lines: [multipleOperations.lines[1], added, multipleOperations.lines[0]] })
    await clickButton(view, '刷新工价与进度')
    let cards = view.findAll('.report-entry')
    expect(cards.map(card => card.get<HTMLInputElement>('.report-quantity input').element.value)).toEqual(['12', '', '10'])
    expect(cards.map(card => card.get<HTMLInputElement>('.report-choice input').element.value)).toEqual(['测试员工乙', '', '测试员工甲'])
    expect(cards[0].get('.report-operation-name').text()).toContain('打孔')
    expect(cards[1].get('.report-operation-name').text()).toContain('组装')
    expect(cards[2].get('.report-operation-name').text()).toContain('切割')
    api.scheme.mockResolvedValueOnce({ ...multipleOperations, revision: 4, lines: [added, { ...multipleOperations.lines[0], status: 'VOID' }, multipleOperations.lines[1]] })
    await clickButton(view, '刷新工价与进度')
    cards = view.findAll('.report-entry')
    expect(cards).toHaveLength(2)
    expect(cards.map(card => card.get<HTMLInputElement>('.report-quantity input').element.value)).toEqual(['', '12'])
    expect(cards.map(card => card.get<HTMLInputElement>('.report-choice input').element.value)).toEqual(['', '测试员工乙'])
    expect(view.text()).toContain('部分已填写工序已停用或移除，对应内容已清空，请重新核对后提交。')
    await clickButton(view, '提交报工')
    expect(api.create).toHaveBeenLastCalledWith(expect.objectContaining({ scheme_revision: 4, lines: [
      { scheme_line_id: 'line-two', workshop_employee_id: 'worker-b', production_line: null, quantity: '12' },
    ] }))
  })
  it('工艺当前分类改变后，旧排产仍按原工艺和工价版本报工', async () => {
    const changed = structuredClone(reportContext)
    changed.crafts[0].plan_category = 'CUTTING'
    api.context.mockResolvedValueOnce(changed)
    const view = await openPage()
    expect(api.scheme).toHaveBeenCalledWith(query, 'product', expect.any(String), expect.any(AbortSignal))
    await fillEmployee(view, 0, '测试员工甲')
    await fillQuantity(view, 0, '10')
    await clickButton(view, '提交报工')
    expect(api.create).toHaveBeenCalledWith(expect.objectContaining({ schedule_product_id: query.schedule_product_id, scheme_id: 'scheme', scheme_revision: 2 }))
    expect(view.text()).toContain('报工已提交')
  })
  it.each(['removed', 'other-workshop'])('分类放宽后仍阻止不属于当前排产或车间的工艺：%s', async (change) => {
    const changed = structuredClone(reportContext)
    if (change === 'removed') changed.crafts = []
    else changed.crafts[0].workshop_id = 'other-workshop'
    api.context.mockResolvedValueOnce(changed)
    const view = await openPage()
    expect(view.text()).toContain('当前任务的车间或工艺已经变化')
    expect(api.scheme).not.toHaveBeenCalled()
    expect(api.create).not.toHaveBeenCalled()
  })
  it('网络结果不明时锁定内容，并以原编号和原内容重试', async () => {
    api.create.mockRejectedValueOnce(new Error('timeout'))
    const view = await openPage()
    await fillEmployee(view, 0, '测试员工甲')
    await fillQuantity(view, 0, '10')
    await clickButton(view, '提交报工')
    expect(view.text()).toContain('尚未确认这次报工是否成功')
    expect(view.findAllComponents(Field).filter(field => ['员工', '本次次数'].includes(String(field.props('label')))).every(field => field.props('disabled'))).toBe(true)
    const first = api.create.mock.calls[0][0]
    await clickButton(view, '核对并重试本次报工')
    expect(api.create.mock.calls[1][0]).toEqual(first)
    expect(showConfirmDialog).toHaveBeenCalledTimes(1)
    expect(view.text()).toContain('报工已提交')
  })
  it('达到所有工序次数时明确确认完成计划，取消则不提交', async () => {
    vi.mocked(showConfirmDialog).mockRejectedValueOnce('cancel')
    const view = await openPage()
    await fillEmployee(view, 0, '测试员工甲')
    await fillQuantity(view, 0, '40')
    await clickButton(view, '提交报工')
    expect(showConfirmDialog).toHaveBeenCalledWith(expect.objectContaining({ title: '确认完成生产计划', confirmButtonText: '完成计划并提交' }))
    expect(api.create).not.toHaveBeenCalled()
    await clickButton(view, '提交报工')
    expect(api.create).toHaveBeenCalledWith(expect.objectContaining({ confirm_plan_completion: true }))
  })
  it('今天没有适用工价时仍可改选历史日期并重新取得方案', async () => {
    api.scheme.mockRejectedValueOnce(new Error('当前日期没有适用的已批准工价方案'))
    const view = await openPage()
    expect(view.text()).toContain('当前日期没有适用的已批准工价方案')
    expect(view.find('#report-production-date').exists()).toBe(true)
    expect(view.findAll('.report-entry')).toHaveLength(0)
    await chooseDate(view, '2026-10-01')
    expect(api.scheme).toHaveBeenLastCalledWith(query, 'product', '2026-10-01', expect.any(AbortSignal))
    expect(view.findAll('.report-entry')).toHaveLength(1)
    expect(view.text()).not.toContain('当前日期没有适用的已批准工价方案')
  })
  it('取消日期草稿或确认原日期均不修改明细，不重新请求工价', async () => {
    const view = await openPage()
    await fillEmployee(view, 0, '测试员工甲')
    await fillQuantity(view, 0, '12')
    const original = view.get('#report-production-date').text()
    const picker = await openDatePicker(view)
    const confirmedDate = [...picker.props('modelValue')!]
    picker.vm.$emit('update:modelValue', ['2027', '01', '31']); await flushPromises()
    await picker.get('.van-picker__cancel').trigger('click'); await flushPromises()
    expect(view.get('#report-production-date').text()).toBe(original)
    const reopened = await openDatePicker(view)
    expect(reopened.props('modelValue')).toEqual(confirmedDate)
    await reopened.get('.van-picker__confirm').trigger('click'); await flushPromises()
    expect(view.get('#report-production-date').text()).toBe(original)
    const fields = view.findAllComponents(Field)
    expect(fields.find(field => field.props('label') === '员工')!.props('modelValue')).toBe('测试员工甲')
    expect(fields.find(field => field.props('label') === '本次次数')!.props('modelValue')).toBe('12')
    expect(api.context).toHaveBeenCalledTimes(1)
    expect(api.scheme).toHaveBeenCalledTimes(1)
    expect(showConfirmDialog).not.toHaveBeenCalled()
    expect(api.create).not.toHaveBeenCalled()
  })
  it('真实年月日选择器跨月修正闰日，取价和保存保持纯日期格式', async () => {
    const view = await openPage()
    const picker = await openDatePicker(view, '2028-01-31')
    expect(picker.props('columnsType')).toEqual(['year', 'month', 'day'])
    picker.vm.$emit('update:modelValue', ['2028', '02', '31']); await flushPromises()
    expect(picker.props('modelValue')).toEqual(['2028', '02', '29'])
    await picker.get('.van-picker__confirm').trigger('click'); await flushPromises()
    expect(view.get('#report-production-date').text()).toContain('2028-02-29')
    expect(api.scheme).toHaveBeenLastCalledWith(query, 'product', '2028-02-29', expect.any(AbortSignal))
    await fillEmployee(view, 0, '测试员工甲')
    await fillQuantity(view, 0, '10')
    await clickButton(view, '提交报工')
    expect(api.create).toHaveBeenCalledWith(expect.objectContaining({ production_date: '2028-02-29' }))
  })
  it('已填写明细时取消更换保留原值，确认后才清空并重新匹配工价', async () => {
    const view = await openPage()
    await fillEmployee(view, 0, '测试员工甲')
    await fillQuantity(view, 0, '10')
    const original = view.get('#report-production-date').text()
    vi.mocked(showConfirmDialog).mockRejectedValueOnce('cancel')
    await chooseDate(view, '2027-01-31')
    expect(showConfirmDialog).toHaveBeenLastCalledWith(expect.objectContaining({ title: '更换生产日期', confirmButtonText: '更换日期' }))
    expect(view.get('#report-production-date').text()).toBe(original)
    expect(view.findAllComponents(Field).find(field => field.props('label') === '员工')!.props('modelValue')).toBe('测试员工甲')
    expect(view.findAllComponents(Field).find(field => field.props('label') === '本次次数')!.props('modelValue')).toBe('10')
    expect(api.scheme).toHaveBeenCalledTimes(1)
    await chooseDate(view, '2027-01-31')
    expect(view.get('#report-production-date').text()).toContain('2027-01-31')
    expect(api.context).toHaveBeenCalledTimes(2)
    expect(api.scheme).toHaveBeenLastCalledWith(query, 'product', '2027-01-31', expect.any(AbortSignal))
    expect(view.findAllComponents(Field).find(field => field.props('label') === '员工')!.props('modelValue')).toBe('')
    expect(view.findAllComponents(Field).find(field => field.props('label') === '本次次数')!.props('modelValue')).toBe('')
    expect(api.create).not.toHaveBeenCalled()
  })
  it('保存中和结果未明时关闭日期面板，延迟确认事件也不能写回', async () => {
    let rejectCreate!: (error: Error) => void
    api.create.mockImplementationOnce(() => new Promise((_resolve, reject) => { rejectCreate = reject }))
    const view = await openPage()
    await fillEmployee(view, 0, '测试员工甲')
    await fillQuantity(view, 0, '10')
    const original = view.get('#report-production-date').text()
    const picker = await openDatePicker(view, '2027-01-31')
    await clickButton(view, '提交报工')
    expect(view.get('#report-production-date').attributes('disabled')).toBeDefined()
    expect(view.findAllComponents(Popup).find(popup => popup.props('teleport') === 'body')!.props('show')).toBe(false)
    picker.vm.$emit('confirm', { selectedValues: ['2027', '01', '31'] }); await flushPromises()
    expect(view.get('#report-production-date').text()).toBe(original)
    rejectCreate(new Error('timeout')); await flushPromises()
    expect(view.get('#report-production-date').attributes('disabled')).toBeDefined()
    picker.vm.$emit('confirm', { selectedValues: ['2027', '01', '31'] }); await flushPromises()
    expect(view.get('#report-production-date').text()).toBe(original)
    expect(api.context).toHaveBeenCalledTimes(1)
    expect(api.scheme).toHaveBeenCalledTimes(1)
  })
  it('等待更换确认时忽略重复确认，页面卸载后旧结果不再加载工价', async () => {
    let confirmDate!: (action: 'confirm') => void
    vi.mocked(showConfirmDialog).mockImplementationOnce(() => new Promise(resolve => { confirmDate = resolve }))
    const view = await openPage()
    await fillEmployee(view, 0, '测试员工甲')
    await fillQuantity(view, 0, '10')
    const picker = await openDatePicker(view, '2027-01-31')
    await picker.get('.van-picker__confirm').trigger('click'); await flushPromises()
    expect(view.get('#report-production-date').attributes('disabled')).toBeDefined()
    picker.vm.$emit('confirm', { selectedValues: ['2028', '02', '29'] }); await flushPromises()
    expect(showConfirmDialog).toHaveBeenCalledTimes(1)
    expect(api.context).toHaveBeenCalledTimes(1)
    view.unmount(); wrapper = undefined
    confirmDate('confirm'); await flushPromises()
    expect(api.context).toHaveBeenCalledTimes(1)
    expect(api.scheme).toHaveBeenCalledTimes(1)
    expect(api.create).not.toHaveBeenCalled()
  })
})
