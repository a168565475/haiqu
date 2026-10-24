import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElPagination } from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fetchFinanceAvailableDeposits } from '@/api/financeReceipts'
import type { ReceiptDepositAllocationInput, ReceiptDepositOption, ReceiptDepositPage, ReceiptStatementContext } from '@/types/financeReceipts'
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
const picker = () => mount(GoodsDepositSelectDialog, { attachTo: document.body, props: { modelValue: true, statement, selected: [], selectionEtag: '', maximumAmount: '480.00' }, global })
const button = (wrapper: ReturnType<typeof picker>, label: string) => wrapper.findAll('button').find(item => item.text() === label)!

describe('货款订金选择隔离组件测试', () => {
  beforeEach(() => { vi.clearAllMocks(); vi.mocked(fetchFinanceAvailableDeposits).mockResolvedValue(page()) })

  it('首次打开请求真实API契约，选择后交由主表填写金额', async () => {
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

  it('可用余额超过本次上限仍可选，服务端ETag变化不能确认', async () => {
    const wrapper = picker()
    try {
      await wrapper.setProps({ maximumAmount: '199.99' }); await flushPromises()
      expect(wrapper.find('input[type="checkbox"]').attributes('disabled')).toBeUndefined()
      await wrapper.find('input[type="checkbox"]').setValue(true)
      await button(wrapper, '确认选择').trigger('click')
      expect(wrapper.emitted('confirm')?.[0]).toEqual([[deposit]])
      vi.mocked(fetchFinanceAvailableDeposits).mockResolvedValueOnce(page([deposit], '"s2"'))
      await button(wrapper, '刷新').trigger('click'); await flushPromises()
      expect(wrapper.emitted('stale')).toHaveLength(1)
      expect(button(wrapper, '确认选择').attributes('disabled')).toBeDefined()
    } finally { wrapper.unmount() }
  })
  it('仅有可用余额的有效订金可选择，失效已选项允许移除', async () => {
    vi.mocked(fetchFinanceAvailableDeposits).mockResolvedValueOnce(page([
      { ...deposit, id: 'void', status: 'VOID', can_select: false, blocked_reason: '已作废' },
      { ...deposit, id: 'used', available_amount: '0.00' }, deposit,
    ]))
    const wrapper = picker()
    try {
      await flushPromises()
      const boxes = wrapper.findAll('input[type="checkbox"]')
      expect(boxes[0]!.attributes('disabled')).toBeDefined()
      expect(boxes[1]!.attributes('disabled')).toBeDefined()
      await boxes[2]!.setValue(true)
      vi.mocked(fetchFinanceAvailableDeposits).mockResolvedValueOnce(page([{ ...deposit, can_select: false, blocked_reason: '余额不可用' }]))
      await button(wrapper, '刷新').trigger('click'); await flushPromises()
      expect(button(wrapper, '确认选择').attributes('disabled')).toBeDefined()
      expect(wrapper.find('input[type="checkbox"]').attributes('disabled')).toBeUndefined()
      await wrapper.find('input[type="checkbox"]').setValue(false)
      expect(button(wrapper, '确认选择').attributes('disabled')).toBeUndefined()
    } finally { wrapper.unmount() }
  })
  it('跨页保留选择且确认带回刷新后的可用余额', async () => {
    const wrapper = picker()
    try {
      await flushPromises(); await wrapper.find('input[type="checkbox"]').setValue(true)
      const second = { ...deposit, id: 'second', number: 'SK-2', available_amount: '100.00' }
      vi.mocked(fetchFinanceAvailableDeposits).mockResolvedValueOnce({ ...page([second]), meta: { page: 2, page_size: 20, total: 21, total_pages: 2 } })
      wrapper.findComponent(ElPagination).vm.$emit('update:current-page', 2)
      wrapper.findComponent(ElPagination).vm.$emit('current-change', 2); await flushPromises()
      await wrapper.find('input[type="checkbox"]').setValue(true)
      vi.mocked(fetchFinanceAvailableDeposits).mockResolvedValueOnce(page([{ ...deposit, available_amount: '80.00' }]))
      wrapper.findComponent(ElPagination).vm.$emit('update:current-page', 1)
      wrapper.findComponent(ElPagination).vm.$emit('current-change', 1); await flushPromises()
      await button(wrapper, '确认选择').trigger('click')
      expect(wrapper.emitted('confirm')?.at(-1)).toEqual([[{ ...deposit, available_amount: '80.00' }, second]])
    } finally { wrapper.unmount() }
  })
  it('账单版本变化后，其他页旧选择未核验余额不能直接确认', async () => {
    const second = { ...deposit, id: 'second', number: 'SK-2' }
    const wrapper = picker()
    try {
      await flushPromises()
      await wrapper.setProps({ modelValue: false, selected: [deposit, second], selectionEtag: statement.etag })
      vi.mocked(fetchFinanceAvailableDeposits).mockResolvedValueOnce(page([deposit], '"s2"'))
      await wrapper.setProps({ modelValue: true, statement: { ...statement, etag: '"s2"' } }); await flushPromises()
      expect(wrapper.text()).toContain('请查看已选订金所在页')
      expect(button(wrapper, '确认选择').attributes('disabled')).toBeDefined()
      vi.mocked(fetchFinanceAvailableDeposits).mockResolvedValueOnce({ ...page([{ ...second, available_amount: '50.00' }], '"s2"'), meta: { page: 2, page_size: 20, total: 21, total_pages: 2 } })
      wrapper.findComponent(ElPagination).vm.$emit('update:current-page', 2)
      wrapper.findComponent(ElPagination).vm.$emit('current-change', 2); await flushPromises()
      await button(wrapper, '确认选择').trigger('click')
      expect(wrapper.emitted('confirm')?.at(-1)).toEqual([[deposit, { ...second, available_amount: '50.00' }]])
    } finally { wrapper.unmount() }
  })
})

describe('货款字段金额与输入保留', () => {
  it('M05显示700核销和280未付；刷新ETag须重确认，纯订金切换仅请求父层处理', async () => {
    const wrapper = mount(GoodsReceiptFields, { props: { statement, accountLines: [{ account_id: 'account', account_etag: '"a1"', cash_amount: '500.00', fee_amount: '5.00', received_on: '2026-10-23' }],
      uploadIds: ['upload'], depositAllocations: [], discountAmount: '20.00', pureDeposit: false }, global })
    try {
      wrapper.findComponent(GoodsDepositSelectDialog).vm.$emit('confirm', [deposit])
      await wrapper.setProps({ depositAllocations: [{ deposit_id: 'deposit', amount: '200.00' }] }); await flushPromises()
      expect(wrapper.emitted('summary')?.at(-1)).toEqual([{ settledAmount: '700.00', outstandingAfter: '280.00' }])
      expect(wrapper.emitted('validity')?.at(-1)).toEqual([true])
      expect(wrapper.text()).toContain('200.00 元')
      await wrapper.find('.pure-option input').setValue(true)
      expect(wrapper.emitted('update:pureDeposit')?.at(-1)).toEqual([true])
      expect(wrapper.props('accountLines')).toHaveLength(1)
      expect(wrapper.props('uploadIds')).toEqual(['upload'])
      await wrapper.setProps({ statement: { ...statement, etag: '"s2"' } })
      expect(wrapper.emitted('validity')?.at(-1)).toEqual([false])
      expect(wrapper.text()).toContain('重新确认可用余额及核销金额')
      expect(wrapper.find('input[aria-label="本次折让（元）"]').element).toHaveProperty('value', '20.00')
      expect(wrapper.props('depositAllocations')).toEqual([{ deposit_id: 'deposit', amount: '200.00' }])
    } finally { wrapper.unmount() }
  })
  const fields = () => {
    const wrapper = mount(GoodsReceiptFields, { props: { statement,
    accountLines: [], uploadIds: [], depositAllocations: [], discountAmount: '0.00', pureDeposit: true,
    'onUpdate:depositAllocations': (value: ReceiptDepositAllocationInput[]): void => { void wrapper.setProps({ depositAllocations: value }) },
    }, global })
    return wrapper
  }
  it('部分核销保留剩余订金，重复选入保留手填金额，新行默认余额', async () => {
    const wrapper = fields()
    try {
      wrapper.findComponent(GoodsDepositSelectDialog).vm.$emit('confirm', [deposit]); await flushPromises()
      expect(wrapper.props('depositAllocations')).toEqual([{ deposit_id: 'deposit', amount: '200.00' }])
      await wrapper.get('input[aria-label="SK-test本次核销金额"]').setValue('80.01'); await flushPromises()
      expect(wrapper.emitted('summary')?.at(-1)).toEqual([{ settledAmount: '80.01', outstandingAfter: '919.99' }])
      expect(wrapper.text()).toContain('119.99')
      expect(wrapper.emitted('validity')?.at(-1)).toEqual([true])
      wrapper.findComponent(GoodsDepositSelectDialog).vm.$emit('confirm', [deposit, { ...deposit, id: 'second', number: 'SK-2', available_amount: '50.00' }]); await flushPromises()
      expect(wrapper.props('depositAllocations')).toEqual([{ deposit_id: 'deposit', amount: '80.01' }, { deposit_id: 'second', amount: '50.00' }])
      const remove = wrapper.findAll('button').find(item => item.text() === '移除')!
      await remove.trigger('click'); await flushPromises()
      expect(wrapper.props('depositAllocations')).toEqual([{ deposit_id: 'second', amount: '50.00' }])
    } finally { wrapper.unmount() }
  })
  it.each(['0', '-1', '0.001', '', '200.01'])('逐笔金额%s不可保存；一分钱和余额上限可保存', async amount => {
    const wrapper = fields()
    try {
      wrapper.findComponent(GoodsDepositSelectDialog).vm.$emit('confirm', [deposit]); await flushPromises()
      const input = wrapper.get('input[aria-label="SK-test本次核销金额"]')
      await input.setValue(amount); await flushPromises()
      expect(wrapper.emitted('validity')?.at(-1)).toEqual([false])
      await input.setValue('0.01'); await flushPromises()
      expect(wrapper.emitted('validity')?.at(-1)).toEqual([true])
      await input.setValue('200.00'); await flushPromises()
      expect(wrapper.emitted('validity')?.at(-1)).toEqual([true])
    } finally { wrapper.unmount() }
  })
  it('现金与折让加部分订金超额时提示，未用订金约束继续生效', async () => {
    const wrapper = fields()
    try {
      await wrapper.setProps({ pureDeposit: false, uploadIds: ['file'], accountLines: [{ account_id: 'account', account_etag: '"a1"', cash_amount: '800.00', fee_amount: '0.00', received_on: '2026-10-24' }], discountAmount: '100.00' })
      wrapper.findComponent(GoodsDepositSelectDialog).vm.$emit('confirm', [deposit]); await flushPromises()
      expect(wrapper.text()).toContain('超出当前未付 100.00 元')
      expect(wrapper.emitted('validity')?.at(-1)).toEqual([false])
      await wrapper.get('input[aria-label="SK-test本次核销金额"]').setValue('100.00'); await flushPromises()
      expect(wrapper.text()).toContain('已收订金与本次到账、折让超出当前未付 100.00 元')
      expect(wrapper.emitted('validity')?.at(-1)).toEqual([false])
    } finally { wrapper.unmount() }
  })
  it('余额版本变化后须重确认，余额缩小不静默覆盖已填金额', async () => {
    const wrapper = fields()
    try {
      wrapper.findComponent(GoodsDepositSelectDialog).vm.$emit('confirm', [deposit]); await flushPromises()
      await wrapper.get('input[aria-label="SK-test本次核销金额"]').setValue('120.00'); await flushPromises()
      await wrapper.setProps({ statement: { ...statement, etag: '"s2"', available_deposit_amount: '100.00' } })
      expect(wrapper.emitted('validity')?.at(-1)).toEqual([false])
      wrapper.findComponent(GoodsDepositSelectDialog).vm.$emit('confirm', [{ ...deposit, available_amount: '100.00' }]); await flushPromises()
      expect(wrapper.props('depositAllocations')[0]?.amount).toBe('120.00')
      expect(wrapper.emitted('validity')?.at(-1)).toEqual([false])
      await wrapper.get('input[aria-label="SK-test本次核销金额"]').setValue('90.00'); await flushPromises()
      expect(wrapper.emitted('validity')?.at(-1)).toEqual([true])
    } finally { wrapper.unmount() }
  })
})
