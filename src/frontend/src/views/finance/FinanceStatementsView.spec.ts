import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElDropdown, ElMessageBox } from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { AxiosError } from 'axios'
import FinanceStatementsView from './FinanceStatementsView.vue'
import FinanceTaskSelect from './FinanceTaskSelect.vue'
import { createFinanceStatement, fetchFinanceSourceProducts, fetchFinanceStatement, fetchFinanceStatements, updateFinanceStatement } from '@/api/financeStatements'
import type { FinanceSourcePage, FinanceSourceProduct, FinanceSourceTask, FinanceStatement, FinanceStatementPage } from '@/types/financeStatements'
import { displayCents, previewLineAmount } from './statementAmounts'

const state = vi.hoisted(() => ({ allowed: true }))
vi.mock('vue-router', () => ({ onBeforeRouteLeave: vi.fn() }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ user: { is_superuser: false, username: 'current-user', display_name: '当前账号', employee: { display_name: '当前制单人' } }, hasPermission: () => state.allowed }) }))
vi.mock('@/api/financeStatements', () => ({ createFinanceStatement: vi.fn(), fetchFinanceStatements: vi.fn(), fetchFinanceStatement: vi.fn(), fetchFinanceSourceProducts: vi.fn(), fetchFinanceSourceTasks: vi.fn(), updateFinanceStatement: vi.fn(), voidFinanceStatement: vi.fn(), deleteFinanceStatement: vi.fn() }))
const task: FinanceSourceTask = { id: 'task1', task_number: 'U03-TASK', source_order_date: '2026-10-20', task_order_date: '2026-10-21', task_delivery_date: '2026-11-15', status: 'READY', salesperson: { id: 'sales', code: 'SALES', name: '合成业务员' } }
const product: FinanceSourceProduct = { id: 'line1', item_number_snapshot: 'ITEM', product_number_snapshot: '', product_code_snapshot: '', product_name_snapshot: '合成产品', specification_snapshot: '规格', quantity: '3', unit_code: 'PCS', unit_name: '件', reference_unit_price_cny: '0.3350', selectable: true, reason: null, error_code: null, occupied_statement_number: null }
const source: FinanceSourcePage = { data: [product], meta: { page: 1, page_size: 20, total: 1, total_pages: 1 }, task, source_revision: 'a'.repeat(64), salesperson_changes: [] }
const statement: FinanceStatement = { id: 'statement', number: 'YSDZD261023001', production_task_id: task.id, task_number: task.task_number, source_order_date: task.source_order_date, task_order_date: task.task_order_date, task_delivery_date: task.task_delivery_date, salesperson: task.salesperson, operator: { id: 'operator', code: 'FIN', name: '合成财务' }, created_at: '', updated_at: '', source_revision: source.source_revision, statement_revision: 1, status: 'ACTIVE', amount: '1.01', settled_amount: '0.00', discount_amount: '0.00', outstanding_amount: '1.01', available_deposit_amount: '0.00', bank_received_amount: '0.00', settlement_status: 'UNSETTLED', can_edit: true, can_void: true, can_delete: false, delete_block_reason: '有效单据不可删除', blocked_reason: null, etag: '"v1"', lines: [], quantity_totals: [], void_reason: '', voided_at: null }
const result = (data = [statement]): FinanceStatementPage => ({ data, meta: { page: 1, page_size: 20, total: data.length, total_pages: 1 } })
const setup = () => mount(FinanceStatementsView, { global: { plugins: [ElementPlus], stubs: {
  AppWindowDialog: { props: ['modelValue'], template: '<div v-if="modelValue" class="dialog-test"><slot/><slot name="footer"/></div>' },
  FinanceTaskSelect: true,
  FinanceStatementReceipts: true,
} } })
const button = (wrapper: ReturnType<typeof setup>, text: string) => wrapper.findAll('button').find(item => item.text() === text)!
async function fill(wrapper: ReturnType<typeof setup>) {
  await flushPromises(); await button(wrapper, '新增对账单').trigger('click'); await flushPromises()
  wrapper.findComponent(FinanceTaskSelect).vm.$emit('task', task); await flushPromises()
  await wrapper.get('[aria-label="选择产品合成产品"] input').setValue(true); await flushPromises()
}
const checkbox = (wrapper: ReturnType<typeof setup>, name = product.product_name_snapshot) => wrapper.get(`[aria-label="选择产品${name}"] input`)
async function openExisting(wrapper: ReturnType<typeof setup>, action: 'edit' | 'detail') {
  await flushPromises()
  const dropdown = wrapper.findComponent(ElDropdown)
  dropdown.vm.$emit('command', action); dropdown.vm.$emit('visible-change', false); await flushPromises()
}
const savedStatement: FinanceStatement = { ...statement, lines: [{ ...product, reference_unit_price_cny: '0.3350', id: 'saved-line', production_task_product_id: product.id, line_number: 1, statement_revision: 1, unit_price: '2.1234', amount: '6.37' }] }

describe('对账页面状态（隔离组件测试，不代替真实API）', () => {
  beforeEach(() => { vi.clearAllMocks(); state.allowed = true; vi.mocked(fetchFinanceStatements).mockResolvedValue(result()); vi.mocked(fetchFinanceStatement).mockResolvedValue(statement); vi.mocked(fetchFinanceSourceProducts).mockResolvedValue(source) })

  it('整数金额逐行舍入且大数量不经过浮点', () => {
    expect(displayCents(previewLineAmount('60', '61.0900')!)).toBe('3665.40')
    expect(displayCents(previewLineAmount('3', '0.3350')! * 2n)).toBe('2.02')
    expect(displayCents(previewLineAmount('9007199254740993', '1')!)).toBe('9007199254740993.00')
    for (const price of ['0', '-1', '1e2', 'NaN', '1.00001']) expect(previewLineAmount('3', price)).toBeNull()
  })
  it('分页请求、筛选与新增顺序', async () => {
    const wrapper = setup()
    try {
      await flushPromises(); expect(wrapper.find('.erp-list-filter-actions').text()).toMatch(/重置.*应用筛选.*新增对账单/)
      expect(fetchFinanceStatements).toHaveBeenCalledWith({ page: 1, page_size: 20, q: '' }, expect.any(AbortSignal))
      await wrapper.find('.erp-list-filters input').setValue('任务号'); await button(wrapper, '应用筛选').trigger('click'); await flushPromises()
      expect(fetchFinanceStatements).toHaveBeenLastCalledWith({ page: 1, page_size: 20, q: '任务号' }, expect.any(AbortSignal))
    } finally { wrapper.unmount() }
  })
  it('刷新失败保留旧结果，初始失败不伪装空数据', async () => {
    const wrapper = setup()
    try { await flushPromises(); vi.mocked(fetchFinanceStatements).mockRejectedValueOnce(new Error('网络失败')); await button(wrapper, '应用筛选').trigger('click'); await flushPromises(); expect(wrapper.text()).toContain('刷新失败，保留上次结果'); expect(wrapper.text()).toContain(statement.number); await button(wrapper, '重试').trigger('click'); await flushPromises(); expect(wrapper.text()).not.toContain('网络失败') } finally { wrapper.unmount() }
    vi.mocked(fetchFinanceStatements).mockRejectedValueOnce(new Error('首次失败'))
    const failed = setup()
    try { await flushPromises(); expect(failed.text()).toContain('首次失败'); expect(failed.text()).not.toContain('暂无应收对账单') } finally { failed.unmount() }
  })
  it('迟到列表响应不能覆盖新筛选', async () => {
    let finish!: (result: FinanceStatementPage) => void
    vi.mocked(fetchFinanceStatements).mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    const wrapper = setup()
    try { await button(wrapper, '应用筛选').trigger('click'); await flushPromises(); finish(result([{ ...statement, number: '过期结果' }])); await flushPromises(); expect(wrapper.text()).not.toContain('过期结果') } finally { wrapper.unmount() }
  })
  it('无权限不发请求和展示业务数据', async () => {
    state.allowed = false; const wrapper = setup()
    try { await flushPromises(); expect(fetchFinanceStatements).not.toHaveBeenCalled(); expect(wrapper.text()).toContain('没有应收对账单查看权限'); expect(wrapper.text()).not.toContain('新增对账单') } finally { wrapper.unmount() }
  })
  it('仅选择任务也属于未保存，取消离开完整保留', async () => {
    const confirm = vi.spyOn(ElMessageBox, 'confirm').mockRejectedValue('cancel')
    const wrapper = setup()
    try { await fill(wrapper); await button(wrapper, '取消').trigger('click'); await flushPromises(); expect(confirm).toHaveBeenCalled(); expect(wrapper.find('.dialog-test').exists()).toBe(true); expect(wrapper.text()).toContain(product.product_name_snapshot) } finally { confirm.mockRestore(); wrapper.unmount() }
  })
  it('来源切换取消保留价格，确认后清空明细与归属', async () => {
    const confirmed = Object.assign('confirm' as const, { value: '', action: 'confirm' as const })
    const confirm = vi.spyOn(ElMessageBox, 'confirm').mockRejectedValueOnce('cancel').mockResolvedValueOnce(confirmed)
    const wrapper = setup()
    try {
      await fill(wrapper); await wrapper.get('input[aria-label="第1行对账单价"]').setValue('2.1234')
      const other = { ...task, id: 'task2', task_number: 'U03-OTHER' }
      wrapper.findComponent(FinanceTaskSelect).vm.$emit('task', other); await flushPromises()
      expect((wrapper.get('input[aria-label="第1行对账单价"]').element as HTMLInputElement).value).toBe('2.1234')
      vi.mocked(fetchFinanceSourceProducts).mockResolvedValueOnce({ ...source, task: other })
      wrapper.findComponent(FinanceTaskSelect).vm.$emit('task', other); await flushPromises()
      expect((checkbox(wrapper).element as HTMLInputElement).checked).toBe(false)
      expect((wrapper.get('input[aria-label="第1行对账单价"]').element as HTMLInputElement).value).toBe('0.3350')
      expect(wrapper.text()).toContain('已选 0 行')
    } finally { confirm.mockRestore(); wrapper.unmount() }
  })
  it('创建超时保留原体原键，并发点击只提交一次', async () => {
    let fail!: (error: AxiosError) => void
    vi.mocked(createFinanceStatement).mockImplementationOnce(() => new Promise((_, reject) => { fail = reject }))
    const wrapper = setup()
    try {
      await fill(wrapper); await Promise.all([button(wrapper, '保存对账单').trigger('click'), button(wrapper, '保存对账单').trigger('click')]); await flushPromises()
      expect(createFinanceStatement).toHaveBeenCalledTimes(1); fail(new AxiosError('timeout')); await flushPromises()
      expect(wrapper.text()).toContain('提交结果尚未确认')
      vi.mocked(createFinanceStatement).mockResolvedValueOnce(statement)
      await button(wrapper, '重试原提交').trigger('click'); await flushPromises()
      expect(vi.mocked(createFinanceStatement).mock.calls[0]).toEqual(vi.mocked(createFinanceStatement).mock.calls[1])
    } finally { wrapper.unmount() }
  })
  it('零总额和非法单价在保存前定位', async () => {
    const wrapper = setup()
    try {
      await fill(wrapper); await wrapper.get('input[aria-label="第1行对账单价"]').setValue('0.0001'); await button(wrapper, '保存对账单').trigger('click'); await flushPromises()
      expect(wrapper.text()).toContain('对账总额须大于零'); expect(createFinanceStatement).not.toHaveBeenCalled()
      await wrapper.get('input[aria-label="第1行对账单价"]').setValue('1e2'); await button(wrapper, '保存对账单').trigger('click'); await flushPromises()
      expect(wrapper.text()).toContain('请填写大于零、最多4位小数的单价')
    } finally { wrapper.unmount() }
  })
  it('选任务即展示产品，不默认勾选，无选择不能保存', async () => {
    const wrapper = setup()
    try {
      await flushPromises(); await button(wrapper, '新增对账单').trigger('click')
      wrapper.findComponent(FinanceTaskSelect).vm.$emit('task', task); await flushPromises()
      expect(wrapper.text()).toContain(product.product_name_snapshot); expect(wrapper.text()).not.toContain('选择产品行')
      expect((checkbox(wrapper).element as HTMLInputElement).checked).toBe(false)
      expect(button(wrapper, '保存对账单').attributes('disabled')).toBeDefined()
      expect(wrapper.find('.statement-summary').text()).toContain('0.00 元')
      await button(wrapper, '保存对账单').trigger('click'); expect(createFinanceStatement).not.toHaveBeenCalled()
    } finally { wrapper.unmount() }
  })
  it('新增显示当前人员及打开时间，编辑显示原制单人和服务器时间', async () => {
    const wrapper = setup()
    try {
      await flushPromises(); await button(wrapper, '新增对账单').trigger('click')
      expect((wrapper.get('input[aria-label="对账人员"]').element as HTMLInputElement).value).toBe('当前制单人')
      expect((wrapper.get('input[aria-label="对账时间"]').element as HTMLInputElement).value).toMatch(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/)
      expect(wrapper.find('.form-grid').text()).toContain('结算类型')
      await button(wrapper, '取消').trigger('click'); await flushPromises()
      vi.mocked(fetchFinanceStatement).mockResolvedValue({ ...savedStatement, created_at: '2026-10-23T08:09:10' })
      await openExisting(wrapper, 'edit')
      expect((wrapper.get('input[aria-label="对账人员"]').element as HTMLInputElement).value).toBe('合成财务')
      expect((wrapper.get('input[aria-label="对账时间"]').element as HTMLInputElement).value).toBe('2026-10-23 08:09:10')
      expect((wrapper.get('input[aria-label="开始时间"]').element as HTMLInputElement).value).toBe(savedStatement.task_order_date)
      expect((wrapper.get('input[aria-label="结束时间"]').element as HTMLInputElement).value).toBe(savedStatement.task_delivery_date)
      await button(wrapper, '取消').trigger('click'); await flushPromises(); await openExisting(wrapper, 'detail')
      expect(wrapper.find('.document-facts').text()).toContain(`开始时间${savedStatement.task_order_date}`)
      expect(wrapper.find('.document-facts').text()).toContain(`结束时间${savedStatement.task_delivery_date}`)
    } finally { wrapper.unmount() }
  })
  it('跨页勾选与调整单价保留，合计和提交只取勾选整行', async () => {
    const second = { ...product, id: 'second', product_name_snapshot: '第二页产品', quantity: '4', reference_unit_price_cny: '2.0000' }
    vi.mocked(fetchFinanceSourceProducts).mockImplementation(async (_id, query) => ({ ...source, data: query.page === 2 ? [second] : [product], meta: { page: query.page, page_size: 20, total: 21, total_pages: 2 } }))
    vi.mocked(createFinanceStatement).mockResolvedValue(statement)
    const wrapper = setup()
    try {
      await fill(wrapper); await wrapper.get('input[aria-label="第1行对账单价"]').setValue('3.0000')
      await wrapper.get('.product-footer .btn-next').trigger('click'); await flushPromises(); await checkbox(wrapper, second.product_name_snapshot).setValue(true)
      expect(wrapper.find('.statement-summary').text()).toContain('7 件'); expect(wrapper.find('.statement-summary').text()).toContain('17.00 元')
      await wrapper.get('.product-footer .btn-prev').trigger('click'); await flushPromises()
      expect((checkbox(wrapper).element as HTMLInputElement).checked).toBe(true)
      expect((wrapper.get('input[aria-label="第1行对账单价"]').element as HTMLInputElement).value).toBe('3.0000')
      await checkbox(wrapper).setValue(false); expect(wrapper.find('.statement-summary').text()).toContain('8.00 元')
      await button(wrapper, '保存对账单').trigger('click'); await flushPromises()
      expect(createFinanceStatement).toHaveBeenCalledWith(expect.objectContaining({ source_revision: source.source_revision, lines: [{ production_task_product_id: 'second', unit_price: '2.0000' }] }), expect.any(String))
    } finally { wrapper.unmount() }
  })
  it('开始结束显示任务当前日期，产品刷新回填日期且不写入保存体', async () => {
    vi.mocked(createFinanceStatement).mockResolvedValue(statement)
    const wrapper = setup()
    try {
      await fill(wrapper)
      expect((wrapper.get('input[aria-label="开始时间"]').element as HTMLInputElement).value).toBe(task.task_order_date)
      expect((wrapper.get('input[aria-label="结束时间"]').element as HTMLInputElement).value).toBe(task.task_delivery_date)
      expect(wrapper.get('input[aria-label="开始时间"]').attributes('readonly')).toBeDefined()
      expect(wrapper.get('input[aria-label="结束时间"]').attributes('readonly')).toBeDefined()
      vi.mocked(fetchFinanceSourceProducts).mockResolvedValueOnce({ ...source, task: { ...task, task_order_date: '2026-10-25', task_delivery_date: '2026-12-01' } })
      await button(wrapper, '刷新产品').trigger('click'); await flushPromises()
      expect((wrapper.get('input[aria-label="开始时间"]').element as HTMLInputElement).value).toBe('2026-10-25')
      expect((wrapper.get('input[aria-label="结束时间"]').element as HTMLInputElement).value).toBe('2026-12-01')
      await button(wrapper, '保存对账单').trigger('click'); await flushPromises()
      expect(vi.mocked(createFinanceStatement).mock.calls[0]![0]).toEqual({ production_task_id: task.id, source_revision: source.source_revision, acknowledge_salesperson_change: false, lines: [{ production_task_product_id: product.id, unit_price: product.reference_unit_price_cny }] })
    } finally { wrapper.unmount() }
  })
  it('编辑产品响应更新任务当前日期，保留原人员与历史来源快照语义', async () => {
    vi.mocked(fetchFinanceStatement).mockResolvedValue(savedStatement)
    vi.mocked(fetchFinanceSourceProducts).mockResolvedValue({ ...source, task: { ...task, task_order_date: '2026-10-26', task_delivery_date: '2026-12-03' } })
    const wrapper = setup()
    try {
      await openExisting(wrapper, 'edit')
      expect((wrapper.get('input[aria-label="开始时间"]').element as HTMLInputElement).value).toBe('2026-10-26')
      expect((wrapper.get('input[aria-label="结束时间"]').element as HTMLInputElement).value).toBe('2026-12-03')
      expect((wrapper.get('input[aria-label="对账人员"]').element as HTMLInputElement).value).toBe(savedStatement.operator.name)
      expect(wrapper.findAll('input').some(input => (input.element as HTMLInputElement).value === savedStatement.source_order_date)).toBe(false)
    } finally { wrapper.unmount() }
  })
  it('编辑预勾选已保存产品并保留原对账价，详情不请求来源或显示复选框', async () => {
    vi.mocked(fetchFinanceStatement).mockResolvedValue(savedStatement)
    vi.mocked(updateFinanceStatement).mockResolvedValue(savedStatement)
    const wrapper = setup()
    try {
      await openExisting(wrapper, 'edit')
      expect(fetchFinanceSourceProducts).toHaveBeenCalledWith(task.id, { page: 1, page_size: 20, editing_statement_id: statement.id }, expect.any(AbortSignal))
      expect((checkbox(wrapper).element as HTMLInputElement).checked).toBe(true)
      expect((wrapper.get('input[aria-label="第1行对账单价"]').element as HTMLInputElement).value).toBe('2.1234')
      await button(wrapper, '保存对账单').trigger('click'); await flushPromises()
      expect(updateFinanceStatement).toHaveBeenCalledWith(statement.id, expect.objectContaining({ lines: [{ production_task_product_id: product.id, unit_price: '2.1234' }] }), statement.etag)
      vi.mocked(fetchFinanceSourceProducts).mockClear(); await openExisting(wrapper, 'detail')
      expect(fetchFinanceSourceProducts).not.toHaveBeenCalled(); expect(wrapper.find('.statement-products input[type="checkbox"]').exists()).toBe(false)
      expect(wrapper.find('.statement-products').text()).toContain('2.1234')
    } finally { wrapper.unmount() }
  })
  it('占用产品禁选，已选失效行可取消且不会丢失其他勾选', async () => {
    const other = { ...product, id: 'other', product_name_snapshot: '其他可选产品' }
    vi.mocked(fetchFinanceSourceProducts).mockResolvedValue({ ...source, data: [product, other] })
    const wrapper = setup()
    try {
      await fill(wrapper); await checkbox(wrapper, other.product_name_snapshot).setValue(true)
      vi.mocked(fetchFinanceSourceProducts).mockResolvedValue({ ...source, data: [{ ...product, selectable: false, reason: '已被其他对账单占用' }, other] })
      await button(wrapper, '刷新产品').trigger('click'); await flushPromises()
      expect(wrapper.text()).toContain('已选产品中有 1 行已失效'); expect(button(wrapper, '保存对账单').attributes('disabled')).toBeDefined()
      expect(checkbox(wrapper).attributes('disabled')).toBeUndefined(); await checkbox(wrapper).setValue(false)
      expect(checkbox(wrapper).attributes('disabled')).toBeDefined()
      expect((checkbox(wrapper, other.product_name_snapshot).element as HTMLInputElement).checked).toBe(true)
      expect(button(wrapper, '保存对账单').attributes('disabled')).toBeUndefined()
    } finally { wrapper.unmount() }
  })
  it('来源摘要变更阻止保存，明确重新载入核对跨页数量并保留调价', async () => {
    const second = { ...product, id: 'second', product_name_snapshot: '第二页产品', quantity: '4' }
    const meta = { page_size: 20, total: 21, total_pages: 2 }
    vi.mocked(fetchFinanceSourceProducts).mockImplementation(async (_id, query) => ({ ...source, data: query.page === 2 ? [second] : [product], meta: { ...meta, page: query.page } }))
    const wrapper = setup()
    try {
      await fill(wrapper); await wrapper.get('input[aria-label="第1行对账单价"]').setValue('3.0000')
      await wrapper.get('.product-footer .btn-next').trigger('click'); await flushPromises(); await checkbox(wrapper, second.product_name_snapshot).setValue(true)
      vi.mocked(fetchFinanceSourceProducts).mockImplementation(async (_id, query) => ({ ...source, source_revision: 'b'.repeat(64), data: query.page === 2 ? [{ ...second, quantity: '8' }] : [{ ...product, reference_unit_price_cny: '99.0000' }], meta: { ...meta, page: query.page } }))
      await button(wrapper, '刷新产品').trigger('click'); await flushPromises()
      expect(wrapper.text()).toContain('生产来源已变化'); expect(button(wrapper, '保存对账单').attributes('disabled')).toBeDefined()
      await button(wrapper, '重新载入并核对').trigger('click'); await flushPromises()
      expect((wrapper.get('input[aria-label="第1行对账单价"]').element as HTMLInputElement).value).toBe('3.0000')
      expect(wrapper.find('.statement-summary').text()).toContain('11 件')
      vi.mocked(createFinanceStatement).mockResolvedValue(statement)
      await button(wrapper, '保存对账单').trigger('click'); await flushPromises()
      expect(createFinanceStatement).toHaveBeenCalledWith(expect.objectContaining({ source_revision: 'b'.repeat(64), lines: [{ production_task_product_id: product.id, unit_price: '3.0000' }, { production_task_product_id: second.id, unit_price: '0.3350' }] }), expect.any(String))
    } finally { wrapper.unmount() }
  })
  it('跨页仍保留失效项提示，取消失效项不丢有效选择', async () => {
    const second = { ...product, id: 'second', product_name_snapshot: '第二页产品' }
    vi.mocked(fetchFinanceStatement).mockResolvedValue(savedStatement)
    vi.mocked(fetchFinanceSourceProducts).mockImplementation(async (_id, query) => ({ ...source, data: query.page === 2 ? [second] : [{ ...product, selectable: false, reason: '被其他单据占用' }], meta: { page: query.page, page_size: 20, total: 21, total_pages: 2 } }))
    const wrapper = setup()
    try {
      await openExisting(wrapper, 'edit'); await wrapper.get('.product-footer .btn-next').trigger('click'); await flushPromises()
      await checkbox(wrapper, second.product_name_snapshot).setValue(true)
      expect(button(wrapper, '保存对账单').attributes('disabled')).toBeDefined()
      await wrapper.get('button[aria-label="取消失效产品合成产品"]').trigger('click'); await flushPromises()
      expect((checkbox(wrapper, second.product_name_snapshot).element as HTMLInputElement).checked).toBe(true)
      expect(button(wrapper, '保存对账单').attributes('disabled')).toBeUndefined(); expect(wrapper.text()).toContain('已选 1 行')
    } finally { wrapper.unmount() }
  })
  it('未选未调价行在来源更新后使用新参考价，取消再选仍保留人工调价', async () => {
    const second = { ...product, id: 'second', product_name_snapshot: '尚未选择产品', reference_unit_price_cny: '2.0000' }
    vi.mocked(fetchFinanceSourceProducts).mockResolvedValue({ ...source, data: [product, second] })
    vi.mocked(createFinanceStatement).mockResolvedValue(statement)
    const wrapper = setup()
    try {
      await fill(wrapper); await wrapper.get('input[aria-label="第1行对账单价"]').setValue('3.0000')
      await checkbox(wrapper).setValue(false)
      vi.mocked(fetchFinanceSourceProducts).mockResolvedValue({ ...source, source_revision: 'b'.repeat(64), data: [{ ...product, reference_unit_price_cny: '9.0000' }, { ...second, reference_unit_price_cny: '8.0000' }] })
      await button(wrapper, '刷新产品').trigger('click'); await flushPromises()
      await button(wrapper, '重新载入并核对').trigger('click'); await flushPromises()
      expect((wrapper.get('input[aria-label="第1行对账单价"]').element as HTMLInputElement).value).toBe('3.0000')
      expect((wrapper.get('input[aria-label="第2行对账单价"]').element as HTMLInputElement).value).toBe('8.0000')
      await checkbox(wrapper).setValue(true); await checkbox(wrapper, second.product_name_snapshot).setValue(true)
      await button(wrapper, '保存对账单').trigger('click'); await flushPromises()
      expect(createFinanceStatement).toHaveBeenCalledWith(expect.objectContaining({ lines: [{ production_task_product_id: product.id, unit_price: '3.0000' }, { production_task_product_id: second.id, unit_price: '8.0000' }] }), expect.any(String))
    } finally { wrapper.unmount() }
  })
  it('任务切换清空旧选择，旧响应不能覆盖新任务', async () => {
    let resolve!: (value: FinanceSourcePage) => void
    vi.mocked(fetchFinanceSourceProducts).mockImplementationOnce(() => new Promise(done => { resolve = done }))
    const confirm = vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue('confirm' as never)
    const wrapper = setup()
    try {
      await flushPromises(); await button(wrapper, '新增对账单').trigger('click')
      wrapper.findComponent(FinanceTaskSelect).vm.$emit('task', task); await flushPromises()
      expect(wrapper.text()).toContain('正在加载任务产品')
      const other = { ...task, id: 'task-other', task_number: 'NEW-TASK' }
      vi.mocked(fetchFinanceSourceProducts).mockResolvedValue({ ...source, task: other, data: [{ ...product, product_name_snapshot: '新任务产品' }] })
      wrapper.findComponent(FinanceTaskSelect).vm.$emit('task', other); await flushPromises()
      resolve(source); await flushPromises()
      expect(wrapper.find('.statement-products').text()).toContain('新任务产品'); expect(wrapper.find('.statement-products').text()).not.toContain('合成产品')
      expect(wrapper.text()).toContain('已选 0 行')
    } finally { confirm.mockRestore(); wrapper.unmount() }
  })
  it('来源加载失败禁止保存且显示重试，空产品明确显示空态', async () => {
    vi.mocked(fetchFinanceSourceProducts).mockRejectedValueOnce(new Error('产品连接失败'))
    const wrapper = setup()
    try {
      await flushPromises(); await button(wrapper, '新增对账单').trigger('click')
      wrapper.findComponent(FinanceTaskSelect).vm.$emit('task', task); await flushPromises()
      expect(wrapper.text()).toContain('产品连接失败'); expect(button(wrapper, '保存对账单').attributes('disabled')).toBeDefined()
      vi.mocked(fetchFinanceSourceProducts).mockResolvedValueOnce({ ...source, data: [], meta: { page: 1, page_size: 20, total: 0, total_pages: 1 } })
      await button(wrapper, '重试').trigger('click'); await flushPromises()
      expect(wrapper.text()).toContain('该任务没有产品明细'); expect(button(wrapper, '保存对账单').attributes('disabled')).toBeDefined()
    } finally { wrapper.unmount() }
  })
})
