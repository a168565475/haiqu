import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import FinanceStatementReceipts from './FinanceStatementReceipts.vue'
import ReceiptEditor from './ReceiptEditor.vue'
import { fetchFinanceStatementReceipts } from '@/api/financeStatements'
import type { FinanceStatement } from '@/types/financeStatements'

const state = vi.hoisted(() => ({ allowed: true }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ user: { is_superuser: false }, hasPermission: () => state.allowed }) }))
vi.mock('@/api/financeStatements', () => ({ fetchFinanceStatementReceipts: vi.fn(), fetchFinanceStatement: vi.fn() }))
vi.mock('@/api/financeReceipts', () => ({ fetchFinanceReceipt: vi.fn(), deleteFinanceReceipt: vi.fn() }))
const statement = { id: 'statement-id', status: 'ACTIVE' } as FinanceStatement
const setup = (status = 'ACTIVE') => mount(FinanceStatementReceipts, { props: { statement: { ...statement, status: status as FinanceStatement['status'] } }, global: { plugins: [ElementPlus], stubs: { ReceiptEditor: true, ReceiptDetail: true, AppWindowDialog: true } } })
describe('对账详情收款接入', () => {
  beforeEach(() => { vi.clearAllMocks(); state.allowed = true; vi.mocked(fetchFinanceStatementReceipts).mockResolvedValue({ data: [], meta: { page: 1, page_size: 20, total: 0, total_pages: 1 } }) })
  it('读取当前账单分页历史，登记沿用该账单关系', async () => {
    const wrapper = setup()
    try {
      await flushPromises(); expect(fetchFinanceStatementReceipts).toHaveBeenCalledWith('statement-id', 1, expect.any(AbortSignal)); expect(wrapper.text()).toContain('尚无收款记录')
      await wrapper.findAll('button').find(button => button.text() === '登记货款')!.trigger('click')
      expect(wrapper.findComponent(ReceiptEditor).props()).toMatchObject({ modelValue: true, receiptType: 'GOODS', initialStatementId: 'statement-id' })
      wrapper.findComponent(ReceiptEditor).vm.$emit('saved'); await flushPromises(); expect(wrapper.emitted('changed')).toHaveLength(1)
    } finally { wrapper.unmount() }
  })
  it('作废不开放收款，无权限不请求历史', async () => {
    const wrapper = setup('VOID')
    try { await flushPromises(); expect(wrapper.text()).not.toContain('登记订金') } finally { wrapper.unmount() }
    vi.clearAllMocks(); state.allowed = false
    const denied = setup()
    try { await flushPromises(); expect(fetchFinanceStatementReceipts).not.toHaveBeenCalled(); expect(denied.text()).toContain('没有收款查看权限') } finally { denied.unmount() }
  })
  it('历史读取失败明确报错，不显示空记录成功', async () => {
    vi.mocked(fetchFinanceStatementReceipts).mockRejectedValueOnce(new Error('连接失败'))
    const wrapper = setup()
    try { await flushPromises(); expect(wrapper.text()).toContain('连接失败'); expect(wrapper.text()).not.toContain('尚无收款记录') } finally { wrapper.unmount() }
  })
})
