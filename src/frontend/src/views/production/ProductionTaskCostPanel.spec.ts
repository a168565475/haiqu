import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElMessageBox, type MessageBoxData } from 'element-plus'
import { AxiosError, type AxiosResponse } from 'axios'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '@/api/productionCosts'
import ProductionTaskCostPanel from './ProductionTaskCostPanel.vue'

const permissions = vi.hoisted(() => ({ view: true, manage: true }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: (code: string) => code.endsWith('view_productiontaskcost') ? permissions.view : permissions.manage }) }))
vi.mock('@/api/productionCosts', () => ({ fetchProductionTaskCostSummary: vi.fn(), fetchProductionTaskExpenses: vi.fn(), createProductionTaskExpense: vi.fn(), updateProductionTaskExpense: vi.fn(), voidProductionTaskExpense: vi.fn() }))
const summary = (task = 'one') => ({ task_id: task, currency: 'CNY', order_amount: '100.00', recorded_cost: '120.00', current_difference: '-20.00', cost_ratio: '120.00', complete: true, missing_count: 0, warnings: [], categories: [{ key: 'other', label: '其他费用', amount: '120.00', count: 1, missing_count: 0, items: [{ id: 'expense-e', source_type: 'EXPENSE', source_id: 'e', number: '', label: '运费', amount: '120.00', currency: 'CNY', amount_cny: '120.00', missing_reason: null, href: null, occurred_on: '2026-10-26' }] }] })
function render() { return mount(ProductionTaskCostPanel, { props: { taskId: 'one' }, global: { plugins: [ElementPlus], stubs: { AppWindowDialog: { template: '<div v-if="modelValue"><slot/><slot name="footer"/></div>', props: ['modelValue'] }, RouterLink: { template: '<a><slot/></a>' } } } }) }
describe('生产任务成本面板', () => {
  beforeEach(() => { vi.clearAllMocks(); permissions.view = true; permissions.manage = true; vi.mocked(api.fetchProductionTaskCostSummary).mockResolvedValue(summary() as never); vi.mocked(api.fetchProductionTaskExpenses).mockResolvedValue([]) })
  it('无查看权限时不读取、不暴露金额或维护动作', async () => { permissions.view = false; const wrapper = render(); await flushPromises(); expect(api.fetchProductionTaskCostSummary).not.toHaveBeenCalled(); expect(api.fetchProductionTaskExpenses).not.toHaveBeenCalled(); expect(wrapper.text()).not.toContain('120.00'); expect(wrapper.find('[data-test="add-expense"]').exists()).toBe(false); wrapper.unmount() })
  it('展示负差额，按需展开费用，来源无地址时不生成链接', async () => { const wrapper = render(); await flushPromises(); expect(wrapper.get('[data-test="difference"]').classes()).toContain('is-negative'); expect(api.fetchProductionTaskExpenses).not.toHaveBeenCalled(); await wrapper.get('[data-test="category-other"]').trigger('click'); await flushPromises(); expect(api.fetchProductionTaskExpenses).toHaveBeenCalledWith('one'); expect(wrapper.text()).toContain('运费'); expect(wrapper.find('a').exists()).toBe(false); wrapper.unmount() })
  it('不完整时仅显示已知成本，差额与比例不推算', async () => { vi.mocked(api.fetchProductionTaskCostSummary).mockResolvedValue({ ...summary(), complete: false, missing_count: 2, current_difference: null, cost_ratio: null } as never); const wrapper = render(); await flushPromises(); expect(wrapper.text()).toContain('已知部分'); expect(wrapper.text()).toContain('2 项'); expect(wrapper.get('[data-test="difference"]').text()).toBe('—'); expect(wrapper.text()).not.toContain('120.00%'); wrapper.unmount() })
  it('失败可重试，任务切换后旧响应不能覆盖当前任务', async () => { let resolveOld!: (value: never) => void; vi.mocked(api.fetchProductionTaskCostSummary).mockReturnValueOnce(new Promise(resolve => { resolveOld = resolve })); const wrapper = render(); await wrapper.setProps({ taskId: 'two' }); await flushPromises(); resolveOld({ ...summary(), recorded_cost: '999.00' } as never); await flushPromises(); expect(wrapper.text()).not.toContain('999.00'); vi.mocked(api.fetchProductionTaskCostSummary).mockRejectedValueOnce(new Error('连接失败')); await wrapper.setProps({ taskId: 'three' }); await flushPromises(); expect(wrapper.text()).toContain('连接失败'); await wrapper.get('[data-test="retry-summary"]').trigger('click'); await flushPromises(); expect(wrapper.find('[data-test="retry-summary"]').exists()).toBe(false); wrapper.unmount() })
  it('登记校验金额并以 UUID 保存，保存后刷新汇总和费用', async () => { vi.mocked(api.createProductionTaskExpense).mockResolvedValue({ id: 'e' } as never); const wrapper = render(); await flushPromises(); await wrapper.get('[data-test="add-expense"]').trigger('click'); await wrapper.get('[data-test="save-expense"]').trigger('click'); expect(api.createProductionTaskExpense).not.toHaveBeenCalled(); await wrapper.get('input[data-test="description"]').setValue('运输费用'); await wrapper.get('input[data-test="amount"]').setValue('12.50'); await wrapper.get('[data-test="save-expense"]').trigger('click'); await flushPromises(); expect(api.createProductionTaskExpense).toHaveBeenCalledWith('one', expect.objectContaining({ description: '运输费用', amount: '12.50', client_request_id: expect.stringMatching(/^[0-9a-f-]{36}$/) })); expect(api.fetchProductionTaskCostSummary).toHaveBeenCalledTimes(2); expect(api.fetchProductionTaskExpenses).toHaveBeenCalled(); wrapper.unmount() })
  it('只有查看权限时允许展开，但隐藏费用维护入口', async () => {
    permissions.manage = false
    const wrapper = render()
    await flushPromises()
    expect(wrapper.find('[data-test="add-expense"]').exists()).toBe(false)
    await wrapper.get('[data-test="category-other"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('.expense-actions').exists()).toBe(false)
    wrapper.unmount()
  })
  it('没有记录时显示空态，订单金额为零不显示比例', async () => {
    vi.mocked(api.fetchProductionTaskCostSummary).mockResolvedValue({ ...summary(), order_amount: '0.00', recorded_cost: '0.00', current_difference: '0.00', cost_ratio: null, categories: [] } as never)
    const wrapper = render()
    await flushPromises()
    expect(wrapper.text()).toContain('暂无成本记录')
    expect(wrapper.text()).not.toContain('Infinity')
    expect(wrapper.text()).not.toContain('NaN')
    wrapper.unmount()
  })
  it('网络失败后同内容重试沿用 UUID', async () => {
    vi.mocked(api.createProductionTaskExpense).mockRejectedValueOnce(new Error('网络中断')).mockResolvedValueOnce({ id: 'e' } as never)
    const wrapper = render()
    await flushPromises()
    await wrapper.get('[data-test="add-expense"]').trigger('click')
    await wrapper.get('input[data-test="description"]').setValue('运输费用')
    await wrapper.get('input[data-test="amount"]').setValue('12.50')
    await wrapper.get('[data-test="save-expense"]').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('网络中断')
    await wrapper.get('[data-test="save-expense"]').trigger('click')
    await flushPromises()
    const calls = vi.mocked(api.createProductionTaskExpense).mock.calls
    expect(calls).toHaveLength(2)
    expect(calls[0]![1].client_request_id).toBe(calls[1]![1].client_request_id)
    wrapper.unmount()
  })
  it('编辑及作废使用当前记录的 ETag，成功后刷新汇总和费用', async () => {
    const expense = { id: 'e', etag: '"e-v1"', expense_type: 'TRANSPORT' as const, description: '运费', amount: '120.00', occurred_on: '2026-10-26', remark: '' }
    vi.mocked(api.fetchProductionTaskExpenses).mockResolvedValue([expense])
    vi.mocked(api.updateProductionTaskExpense).mockResolvedValue({ ...expense, etag: '"e-v2"' })
    vi.mocked(api.voidProductionTaskExpense).mockResolvedValue()
    // 当前 Element Plus 将确认返回值声明成交叉类型；实际确认操作返回 confirm。
    const confirmation = vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue('confirm' as MessageBoxData)
    const wrapper = render()
    await flushPromises()
    await wrapper.get('[data-test="category-other"]').trigger('click')
    await flushPromises()
    await wrapper.get('.expense-actions button').trigger('click')
    await wrapper.get('input[data-test="amount"]').setValue('130.00')
    await wrapper.get('[data-test="save-expense"]').trigger('click')
    await flushPromises()
    expect(api.updateProductionTaskExpense).toHaveBeenCalledWith('one', 'e', expect.objectContaining({ amount: '130.00' }), '"e-v1"')
    expect(api.fetchProductionTaskCostSummary).toHaveBeenCalledTimes(2)
    await wrapper.findAll('.expense-actions button')[1]!.trigger('click')
    await flushPromises()
    expect(api.voidProductionTaskExpense).toHaveBeenCalledWith('one', 'e', '"e-v1"')
    expect(api.fetchProductionTaskCostSummary).toHaveBeenCalledTimes(3)
    expect(api.fetchProductionTaskExpenses).toHaveBeenCalledTimes(3)
    confirmation.mockRestore()
    wrapper.unmount()
  })
  it('费用列表加载失败可刷新，切换任务后旧费用不进入新任务', async () => {
    let resolveOld!: (value: never) => void
    vi.mocked(api.fetchProductionTaskExpenses).mockReturnValueOnce(new Promise(resolve => { resolveOld = resolve }))
    const wrapper = render()
    await flushPromises()
    await wrapper.get('[data-test="category-other"]').trigger('click')
    await wrapper.setProps({ taskId: 'two' })
    await flushPromises()
    resolveOld([{ id: 'old', description: '旧任务费用', expense_type: 'OTHER', etag: 'old-v1' }] as never)
    await flushPromises()
    vi.mocked(api.fetchProductionTaskExpenses).mockRejectedValueOnce(new Error('费用连接失败'))
    await wrapper.get('[data-test="category-other"]').trigger('click')
    await flushPromises()
    expect(wrapper.text()).not.toContain('旧任务费用')
    expect(wrapper.text()).toContain('费用连接失败')
    await wrapper.get('.expense-management button').trigger('click')
    await flushPromises()
    expect(wrapper.text()).not.toContain('费用连接失败')
    wrapper.unmount()
  })
  it('保存期间阻止重复提交，任务切换后旧保存不刷新新任务', async () => {
    let resolveSave!: (value: never) => void
    vi.mocked(api.createProductionTaskExpense).mockReturnValueOnce(new Promise(resolve => { resolveSave = resolve }))
    const wrapper = render()
    await flushPromises()
    await wrapper.get('[data-test="add-expense"]').trigger('click')
    await wrapper.get('input[data-test="description"]').setValue('运输费用')
    await wrapper.get('input[data-test="amount"]').setValue('12.50')
    await wrapper.get('[data-test="save-expense"]').trigger('click')
    await wrapper.get('[data-test="save-expense"]').trigger('click')
    expect(api.createProductionTaskExpense).toHaveBeenCalledTimes(1)
    expect(wrapper.emitted('busy-change')?.at(-1)).toEqual([true])
    await wrapper.setProps({ taskId: 'two' })
    await flushPromises()
    expect(wrapper.emitted('busy-change')?.at(-1)).toEqual([false])
    resolveSave({ id: 'old' } as never)
    await flushPromises()
    expect(api.fetchProductionTaskCostSummary).toHaveBeenCalledTimes(2)
    expect(api.fetchProductionTaskExpenses).not.toHaveBeenCalled()
    wrapper.unmount()
  })
  it.each([
    [{ error: { message: '请求参数无效', field_errors: { amount: ['金额不能超过字段上限。'] } } }, '金额不能超过字段上限。'],
    [{ error: { message: '已归档任务不能登记费用。' } }, '已归档任务不能登记费用。'],
  ])('显示后端字段错误和业务提示，并保留填写内容', async (body, message) => {
    const response = { data: body, status: 400, statusText: 'Bad Request', headers: {}, config: { headers: {} } } as AxiosResponse
    vi.mocked(api.createProductionTaskExpense).mockRejectedValueOnce(new AxiosError('Request failed with status code 400', 'ERR_BAD_REQUEST', undefined, undefined, response))
    const wrapper = render()
    await flushPromises()
    await wrapper.get('[data-test="add-expense"]').trigger('click')
    await wrapper.get('input[data-test="description"]').setValue('运输费用')
    await wrapper.get('input[data-test="amount"]').setValue('12.50')
    await wrapper.get('[data-test="save-expense"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('.expense-form [role="alert"]').text()).toBe(message)
    expect((wrapper.get('input[data-test="description"]').element as HTMLInputElement).value).toBe('运输费用')
    expect((wrapper.get('input[data-test="amount"]').element as HTMLInputElement).value).toBe('12.50')
    expect(wrapper.text()).not.toContain('Request failed with status code 400')
    wrapper.unmount()
  })
})


