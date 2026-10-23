import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fetchFinanceAvailableDeposits } from '@/api/financeReceipts'
import type { ReceiptDepositOption, ReceiptDepositPage, ReceiptStatementContext } from '@/types/financeReceipts'
import GoodsDepositSelectDialog from './GoodsDepositSelectDialog.vue'
import GoodsReceiptFields from './GoodsReceiptFields.vue'

vi.mock('@/api/financeReceipts', () => ({ fetchFinanceAvailableDeposits: vi.fn() }))
const statement: ReceiptStatementContext = { id: 'statement', number: 'YSDZD-test', etag: '"s1"', task_number: 'SC-test',
  amount: '1000.00', outstanding_amount: '1000.00', available_deposit_amount: '200.00', bank_received_amount: '200.00', settled_amount: '0.00', discount_amount: '0.00' }
const deposit: ReceiptDepositOption = { id: 'deposit', number: 'SK-test', status: 'ACTIVE', received_on: '2026-10-23', created_at: '',
  deposit_amount: '200.00', available_amount: '200.00', can_select: true, blocked_reason: null, allocated_goods_id: null, allocated_goods_number: null, attachments: [] }
const page = (data = [deposit], etag = statement.etag): ReceiptDepositPage => ({ data, statement_etag: etag,
  outstanding_amount: '1000.00', available_deposit_amount: '200.00', meta: { page: 1, page_size: 20, total: data.length, total_pages: 1 } })
const global = { plugins: [ElementPlus], stubs: {
  AppWindowDialog: { props: ['modelValue'], template: '<div v-if="modelValue"><slot/><slot name="footer"/></div>' },
} }
const picker = () => mount(GoodsDepositSelectDialog, { attachTo: document.body, props: { modelValue: true, statement, selected: [], maximumAmount: '480.00' }, global })
const button = (wrapper: ReturnType<typeof picker>, label: string) => wrapper.findAll('button').find(item => item.text() === label)!

describe('货款订金选择隔离组件测试', () => {
  beforeEach(() => { vi.clearAllMocks(); vi.mocked(fetchFinanceAvailableDeposits).mockResolvedValue(page()) })

  it('首次打开请求真实API契约，整笔选择不编辑金额', async () => {
    const wrapper = picker()
    try {
      await flushPromises()
      expect(fetchFinanceAvailableDeposits).toHaveBeenCalledWith('statement', { q: '', page: 1, page_size: 20, include_unavailable: true }, expect.any(AbortSignal))
      await wrapper.find('.el-checkbox__inner').trigger('click')
      expect((wrapper.find('input[type="checkbox"]').element as HTMLInputElement).checked).toBe(true)
      await button(wrapper, '确认选择').trigger('click')
      expect(wrapper.emitted('confirm')?.[0]).toEqual([[deposit]])
      expect(wrapper.findAll('input[inputmode="decimal"]')).toHaveLength(0)
    } finally { wrapper.unmount() }
  })

  it('刷新失败保留已选与旧行，阻断确认', async () => {
    const wrapper = picker()
    try {
      await flushPromises(); await wrapper.find('input[type="checkbox"]').setValue(true)
      vi.mocked(fetchFinanceAvailableDeposits).mockRejectedValueOnce(new Error('网络失败'))
      await button(wrapper, '刷新').trigger('click'); await flushPromises()
      expect(wrapper.text()).toContain('已选 1 笔')
      expect(wrapper.text()).toContain('当前仍显示上次结果，不能确认选择')
      expect(button(wrapper, '确认选择').attributes('disabled')).toBeDefined()
      expect(wrapper.emitted('confirm')).toBeUndefined()
    } finally { wrapper.unmount() }
  })

  it('旧来源迟到响应不能覆盖新来源', async () => {
    let finish!: (result: ReceiptDepositPage) => void
    vi.mocked(fetchFinanceAvailableDeposits).mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    const wrapper = picker()
    try {
      await wrapper.setProps({ statement: { ...statement, id: 'new-statement' } })
      await flushPromises()
      finish(page([{ ...deposit, number: '过期结果' }])); await flushPromises()
      expect(wrapper.text()).toContain('SK-test')
      expect(wrapper.text()).not.toContain('过期结果')
      expect(vi.mocked(fetchFinanceAvailableDeposits).mock.calls[0]![2]?.aborted).toBe(true)
    } finally { wrapper.unmount() }
  })

  it('整笔超额不可选，服务端ETag变化不能确认', async () => {
    const wrapper = picker()
    try {
      await wrapper.setProps({ maximumAmount: '199.99' }); await flushPromises()
      expect(wrapper.find('input[type="checkbox"]').attributes('disabled')).toBeDefined()
      expect(wrapper.text()).toContain('整笔金额超过本次可核销余额')
      vi.mocked(fetchFinanceAvailableDeposits).mockResolvedValueOnce(page([deposit], '"s2"'))
      await button(wrapper, '刷新').trigger('click'); await flushPromises()
      expect(wrapper.emitted('stale')).toHaveLength(1)
      expect(button(wrapper, '确认选择').attributes('disabled')).toBeDefined()
    } finally { wrapper.unmount() }
  })
})

describe('货款字段金额与输入保留', () => {
  it('M05显示700核销和280未付；刷新ETag须重确认，纯订金切换仅请求父层处理', async () => {
    const wrapper = mount(GoodsReceiptFields, { props: { statement, accountLines: [{ account_id: 'account', account_etag: '"a1"', cash_amount: '500.00', fee_amount: '5.00', received_on: '2026-10-23' }],
      uploadIds: ['upload'], depositIds: [], discountAmount: '20.00', pureDeposit: false }, global })
    try {
      wrapper.findComponent(GoodsDepositSelectDialog).vm.$emit('confirm', [deposit])
      await wrapper.setProps({ depositIds: ['deposit'] }); await flushPromises()
      expect(wrapper.emitted('summary')?.at(-1)).toEqual([{ settledAmount: '700.00', outstandingAfter: '280.00' }])
      expect(wrapper.emitted('validity')?.at(-1)).toEqual([true])
      expect(wrapper.text()).toContain('200.00 元')
      await wrapper.find('.pure-option input').setValue(true)
      expect(wrapper.emitted('update:pureDeposit')?.at(-1)).toEqual([true])
      expect(wrapper.props('accountLines')).toHaveLength(1)
      expect(wrapper.props('uploadIds')).toEqual(['upload'])
      await wrapper.setProps({ statement: { ...statement, etag: '"s2"' } })
      expect(wrapper.emitted('validity')?.at(-1)).toEqual([false])
      expect(wrapper.text()).toContain('重新确认整笔抵扣')
      expect(wrapper.find('input[aria-label="本次折让（元）"]').element).toHaveProperty('value', '20.00')
      expect(wrapper.props('depositIds')).toEqual(['deposit'])
    } finally { wrapper.unmount() }
  })
})
