import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElDropdown, ElDropdownItem, ElMessage, ElMessageBox } from 'element-plus'
import type { MessageBoxData } from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AxiosError } from 'axios'
import FinanceStatementsView from './FinanceStatementsView.vue'
import FinanceReceiptsView from './FinanceReceiptsView.vue'
import FinanceStatementReceipts from './FinanceStatementReceipts.vue'
import { deleteFinanceStatement, fetchFinanceStatement, fetchFinanceStatementReceipts, fetchFinanceStatements } from '@/api/financeStatements'
import { deleteFinanceReceipt, fetchFinanceReceipt, fetchFinanceReceipts } from '@/api/financeReceipts'
import type { FinanceStatement } from '@/types/financeStatements'
import type { Receipt } from '@/types/financeReceipts'

const access = vi.hoisted(() => ({ deleteAllowed: true }))
vi.mock('vue-router', () => ({ onBeforeRouteLeave: vi.fn(), useRoute: () => ({ query: {} }) }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ user: { is_superuser: false }, hasPermission: (permission: string) => !permission.startsWith('finance.delete_') || access.deleteAllowed }) }))
vi.mock('@/api/financeStatements', () => ({ deleteFinanceStatement: vi.fn(), fetchFinanceStatement: vi.fn(), fetchFinanceStatements: vi.fn(), fetchFinanceStatementReceipts: vi.fn(), createFinanceStatement: vi.fn(), fetchFinanceSourceProducts: vi.fn(), updateFinanceStatement: vi.fn(), voidFinanceStatement: vi.fn() }))
vi.mock('@/api/financeReceipts', () => ({ deleteFinanceReceipt: vi.fn(), fetchFinanceReceipt: vi.fn(), fetchFinanceReceipts: vi.fn(), voidFinanceReceipt: vi.fn() }))

// 合成数据只用于组件行为验证，不访问真实业务 API。
const statement: FinanceStatement = {
  id: 'statement', number: 'TEST-STATEMENT', status: 'VOID', etag: '"statement-list"', can_delete: true, delete_block_reason: null,
  can_edit: false, can_void: false, blocked_reason: null, production_task_id: 'task', task_number: 'TASK', source_order_date: '2026-10-23', task_order_date: '2026-10-24', task_delivery_date: '2026-11-15',
  salesperson: { id: 'sales', code: 'SALES', name: '合成业务员' }, operator: { id: 'operator', code: 'FIN', name: '合成财务' },
  created_at: '', updated_at: '', source_revision: 'revision', statement_revision: 1, amount: '10.00', settled_amount: '0.00',
  discount_amount: '0.00', outstanding_amount: '0.00', available_deposit_amount: '0.00', bank_received_amount: '0.00', settlement_status: 'UNSETTLED',
  lines: [], quantity_totals: [], void_reason: '测试', voided_at: null,
}
const receipt: Receipt = {
  id: 'receipt', number: 'TEST-RECEIPT', status: 'VOID', receipt_type: 'DEPOSIT', statement_id: statement.id,
  etag: '"receipt-list"', statement_etag: statement.etag, can_delete: true, delete_block_reason: null, can_void: false, blocked_reason: null,
  statement_snapshot: { number: statement.number, production_task_id: 'task', task_number: 'TASK', salesperson_id: 'sales', salesperson_code: 'SALES', salesperson_name: '合成业务员', source_order_date: '2026-10-23', amount: '10.00', outstanding_before: '10.00', outstanding_after: '10.00' },
  cash_amount: '10.00', fee_amount: '0.00', deposit_amount: '10.00', allocated_deposit_amount: '0.00', discount_amount: '0.00', settled_amount: '0.00',
  outstanding_before: '10.00', outstanding_after: '10.00', account_lines: [], attachments: [], inherited_attachments: [], allocations: [],
  operator: statement.operator, created_at: '', updated_at: '', void_reason: '测试', voided_at: null,
}
const meta = { page: 1, page_size: 20, total: 1, total_pages: 1 }
const cases = [
  { name: '对账列表', component: FinanceStatementsView, row: statement, fetch: fetchFinanceStatement, list: fetchFinanceStatements, remove: deleteFinanceStatement },
  { name: '收款列表', component: FinanceReceiptsView, row: receipt, fetch: fetchFinanceReceipt, list: fetchFinanceReceipts, remove: deleteFinanceReceipt },
  { name: '对账收款历史', component: FinanceStatementReceipts, row: receipt, fetch: fetchFinanceReceipt, list: fetchFinanceStatementReceipts, remove: deleteFinanceReceipt },
] as const
function httpError(status: number) {
  return new AxiosError('请求失败', undefined, undefined, undefined, { status, data: { error: { message: `合成错误 ${status}` } } } as never)
}

describe.each(cases)('$name彻底删除（合成组件测试）', scenario => {
  const setup = () => mount(scenario.component, {
    props: scenario.component === FinanceStatementReceipts ? { statement } : {},
    global: { plugins: [ElementPlus], stubs: {
      AppWindowDialog: { props: ['modelValue'], template: '<div v-if="modelValue"><slot/><slot name="footer"/></div>' },
      FinanceTaskSelect: true, ReceiptEditor: true, ReceiptDetail: true,
      ...(scenario.component !== FinanceStatementReceipts ? { FinanceStatementReceipts: true } : {}),
    } },
  })
  let wrapper: ReturnType<typeof setup> | undefined
  const start = async () => {
    const dropdown = wrapper!.findComponent(ElDropdown)
    dropdown.vm.$emit('command', 'delete')
    dropdown.vm.$emit('visible-change', false)
    await flushPromises()
  }
  beforeEach(() => {
    vi.resetAllMocks(); access.deleteAllowed = true
    vi.mocked(fetchFinanceStatements).mockResolvedValue({ data: [statement], meta })
    vi.mocked(fetchFinanceReceipts).mockResolvedValue({ data: [receipt], meta })
    vi.mocked(fetchFinanceStatementReceipts).mockResolvedValue({ data: [receipt], meta })
    vi.mocked(fetchFinanceStatement).mockResolvedValue({ ...statement, etag: '"fresh"' })
    vi.mocked(fetchFinanceReceipt).mockResolvedValue({ ...receipt, etag: '"fresh"' })
    vi.mocked(deleteFinanceStatement).mockResolvedValue(undefined)
    vi.mocked(deleteFinanceReceipt).mockResolvedValue(undefined)
    vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue('confirm' as MessageBoxData)
    vi.spyOn(ElMessage, 'warning').mockImplementation(() => ({ close: vi.fn() }))
    vi.spyOn(ElMessage, 'error').mockImplementation(() => ({ close: vi.fn() }))
    vi.spyOn(ElMessage, 'success').mockImplementation(() => ({ close: vi.fn() }))
  })
  afterEach(() => { wrapper?.unmount(); wrapper = undefined; vi.restoreAllMocks() })

  it('仅独立删除权限与作废状态共同满足才出现入口', async () => {
    access.deleteAllowed = false
    wrapper = setup(); await flushPromises()
    expect(wrapper.findAllComponents(ElDropdownItem).some(item => item.props('command') === 'delete')).toBe(false)
    await start(); expect(scenario.fetch).not.toHaveBeenCalled(); expect(scenario.remove).not.toHaveBeenCalled()
    wrapper.unmount(); access.deleteAllowed = true
    vi.mocked(scenario.list).mockResolvedValue({ data: [{ ...scenario.row, status: 'ACTIVE' }], meta } as never)
    wrapper = setup(); await flushPromises()
    expect(wrapper.findAllComponents(ElDropdownItem).some(item => item.props('command') === 'delete')).toBe(false)
    await start(); expect(scenario.remove).not.toHaveBeenCalled()
  })
  it('最新版本确认含单号和不可恢复说明，成功后刷新', async () => {
    wrapper = setup(); await flushPromises(); await start()
    expect(ElMessageBox.confirm).toHaveBeenCalledWith(expect.stringContaining(scenario.row.number), expect.any(String), expect.objectContaining({ confirmButtonText: '彻底删除' }))
    expect(vi.mocked(ElMessageBox.confirm).mock.calls[0]![0]).toContain('无法恢复')
    if (scenario.row.id === 'receipt') expect(vi.mocked(ElMessageBox.confirm).mock.calls[0]![0]).toContain('独占水单')
    expect(scenario.remove).toHaveBeenCalledExactlyOnceWith(scenario.row.id, '"fresh"')
    expect(scenario.list).toHaveBeenCalledTimes(2)
    if (scenario.component === FinanceStatementReceipts) expect(wrapper.emitted('changed')).toHaveLength(1)
  })
  it('取消确认不发送删除请求', async () => {
    vi.mocked(ElMessageBox.confirm).mockRejectedValueOnce('cancel')
    wrapper = setup(); await flushPromises(); await start()
    expect(scenario.remove).not.toHaveBeenCalled(); expect(ElMessage.success).not.toHaveBeenCalled()
  })
  it('最新关联阻止删除并显示服务端原因', async () => {
    vi.mocked(scenario.fetch).mockResolvedValueOnce({ ...scenario.row, can_delete: false, delete_block_reason: '请先删除关联货款 TEST-GOODS' } as never)
    wrapper = setup(); await flushPromises(); await start()
    expect(ElMessage.warning).toHaveBeenCalledWith('请先删除关联货款 TEST-GOODS')
    expect(ElMessageBox.confirm).not.toHaveBeenCalled(); expect(scenario.remove).not.toHaveBeenCalled()
  })
  it('最新版本缺失时不发送无版本删除', async () => {
    vi.mocked(scenario.fetch).mockResolvedValueOnce({ ...scenario.row, etag: '' } as never)
    wrapper = setup(); await flushPromises(); await start()
    expect(ElMessage.error).toHaveBeenCalledWith(expect.stringContaining('未取得单据版本')); expect(scenario.remove).not.toHaveBeenCalled()
  })
  it('列表显示关联阻止原因，删除入口不可点击', async () => {
    vi.mocked(scenario.list).mockResolvedValueOnce({ data: [{ ...scenario.row, can_delete: false, delete_block_reason: '尚有关联单据' }], meta } as never)
    wrapper = setup(); await flushPromises()
    const item = wrapper.findAllComponents(ElDropdownItem).find(item => item.props('command') === 'delete')!
    expect(item.props('disabled')).toBe(true); expect(item.html()).toContain('title="尚有关联单据"')
  })
  it('确认等待期间重复操作只读一次且只提交一次', async () => {
    let confirm!: (value: MessageBoxData) => void
    vi.mocked(ElMessageBox.confirm).mockImplementationOnce(() => new Promise(resolve => { confirm = resolve }))
    wrapper = setup(); await flushPromises(); await start(); await start()
    expect(scenario.fetch).toHaveBeenCalledTimes(1); expect(scenario.remove).not.toHaveBeenCalled()
    confirm('confirm' as MessageBoxData); await flushPromises(); expect(scenario.remove).toHaveBeenCalledTimes(1)
  })
  it.each([401, 403, 409, 428, 500])('%s失败保留行且不提示成功', async status => {
    vi.mocked(scenario.remove).mockRejectedValueOnce(httpError(status))
    wrapper = setup(); await flushPromises(); await start()
    expect(wrapper.text()).toContain(scenario.row.number); expect(ElMessage.error).toHaveBeenCalledWith(`合成错误 ${status}`)
    expect(scenario.list).toHaveBeenCalledTimes(1); expect(ElMessage.success).not.toHaveBeenCalled()
    expect(wrapper.emitted('changed')).toBeUndefined()
  })
  it('412刷新后要求重新确认，不自动重试删除', async () => {
    vi.mocked(scenario.remove).mockRejectedValueOnce(httpError(412))
    wrapper = setup(); await flushPromises(); await start()
    expect(ElMessage.warning).toHaveBeenCalledWith(expect.stringContaining('重新确认'))
    expect(scenario.list).toHaveBeenCalledTimes(2); expect(scenario.remove).toHaveBeenCalledTimes(1); expect(ElMessage.success).not.toHaveBeenCalled()
  })
  it('404明确提示已不存在并刷新，不伪装本次成功', async () => {
    vi.mocked(scenario.remove).mockRejectedValueOnce(httpError(404))
    wrapper = setup(); await flushPromises(); await start()
    expect(ElMessage.warning).toHaveBeenCalledWith(expect.stringContaining('已不存在'))
    expect(scenario.list).toHaveBeenCalledTimes(2); expect(ElMessage.success).not.toHaveBeenCalled()
  })
  it('卸载后的迟到读取不弹确认也不发删除', async () => {
    let resolve!: (value: never) => void
    vi.mocked(scenario.fetch).mockImplementationOnce(() => new Promise<never>(done => { resolve = done }))
    wrapper = setup(); await flushPromises(); await start(); wrapper.unmount(); wrapper = undefined
    resolve({ ...scenario.row, etag: '"late"' } as never); await flushPromises()
    expect(ElMessageBox.confirm).not.toHaveBeenCalled(); expect(scenario.remove).not.toHaveBeenCalled()
  })
  it('卸载后的迟到删除结果不触发提示或刷新', async () => {
    let resolve!: () => void
    vi.mocked(scenario.remove).mockImplementationOnce(() => new Promise<void>(done => { resolve = done }))
    wrapper = setup(); await flushPromises(); await start(); wrapper.unmount(); wrapper = undefined
    resolve(); await flushPromises()
    expect(ElMessage.success).not.toHaveBeenCalled(); expect(scenario.list).toHaveBeenCalledTimes(1)
  })
  if (scenario.component === FinanceStatementReceipts) {
    it('切换对账单后，旧收款读取不能继续删除', async () => {
      let resolve!: (value: Receipt) => void
      vi.mocked(fetchFinanceReceipt).mockImplementationOnce(() => new Promise(done => { resolve = done }))
      wrapper = setup(); await flushPromises(); await start()
      await wrapper.setProps({ statement: { ...statement, id: 'another-statement' } }); await flushPromises()
      resolve(receipt); await flushPromises()
      expect(ElMessageBox.confirm).not.toHaveBeenCalled(); expect(deleteFinanceReceipt).not.toHaveBeenCalled()
    })
  }
})
