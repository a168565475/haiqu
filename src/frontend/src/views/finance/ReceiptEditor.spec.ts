import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElMessageBox } from 'element-plus'
import { AxiosError } from 'axios'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ReceiptEditor from './ReceiptEditor.vue'
import { createFinanceReceipt, fetchReceiptAttachment } from '@/api/financeReceipts'
import { fetchFinanceStatement } from '@/api/financeStatements'
import type { FinanceStatement } from '@/types/financeStatements'
import type { Receipt, ReceiptFile, ReceiptType } from '@/types/financeReceipts'

vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ user: { is_superuser: false }, hasPermission: () => true }) }))
vi.mock('@/api/financeReceipts', () => ({ createFinanceReceipt: vi.fn(), fetchReceiptAttachment: vi.fn(), fetchReceiptAccounts: vi.fn() }))
vi.mock('@/api/financeStatements', () => ({ fetchFinanceStatement: vi.fn(), fetchFinanceSourceTasks: vi.fn(), fetchFinanceStatements: vi.fn() }))
const statement = { id: 'statement', number: 'YSDZD1', production_task_id: 'task', task_number: 'TASK1', status: 'ACTIVE', etag: '"v1"',
  amount: '100.00', outstanding_amount: '100.00', available_deposit_amount: '0.00', bank_received_amount: '0.00', salesperson: { code: 'SALE', name: '隔离业务员' } } as FinanceStatement
const setup = (receiptType: ReceiptType = 'DEPOSIT', realAccounts = false) => mount(ReceiptEditor, { props: { modelValue: true, receiptType, initialStatementId: 'statement' },
  global: { plugins: [ElementPlus], stubs: {
    AppWindowDialog: { props: ['modelValue'], template: '<div v-if="modelValue"><slot/><slot name="footer"/></div>' },
    ReceiptAccountLines: realAccounts ? false : { name: 'ReceiptAccountLines', template: '<div/>' },
    ReceiptUploads: { name: 'ReceiptUploads', template: '<div/>' }, ReceiptSourceSelect: true, GoodsReceiptFields: true,
  } } })
const button = (wrapper: ReturnType<typeof setup>, text: string) => wrapper.findAll('button').find(item => item.text() === text)!
async function fill(wrapper: ReturnType<typeof setup>) {
  await flushPromises()
  wrapper.findComponent({ name: 'ReceiptAccountLines' }).vm.$emit('update:modelValue', [{ key: 'line', account_id: 'account', account_etag: '"a1"', cash_amount: '25.00', fee_amount: '1.00', received_on: '2026-10-23' }])
  wrapper.findComponent({ name: 'ReceiptUploads' }).vm.$emit('update:modelValue', [{ id: 'upload', status: 'UNBOUND' }])
  await flushPromises()
}
describe('收款草稿保护（隔离组件测试）', () => {
  beforeEach(() => {
    vi.clearAllMocks(); vi.mocked(fetchFinanceStatement).mockResolvedValue(statement)
    URL.createObjectURL = vi.fn(() => 'blob:u04-preview'); URL.revokeObjectURL = vi.fn()
  })
  it('保存防重复，超时后同键同体同ETag重试并禁止离开', async () => {
    const wrapper = setup()
    try {
      await fill(wrapper)
      let reject!: (error: AxiosError) => void
      vi.mocked(createFinanceReceipt).mockImplementationOnce(() => new Promise((_, fail) => { reject = fail }))
      await Promise.all([button(wrapper, '保存并生效').trigger('click'), button(wrapper, '保存并生效').trigger('click')]); await flushPromises()
      expect(createFinanceReceipt).toHaveBeenCalledTimes(1)
      reject(new AxiosError('timeout')); await flushPromises()
      expect(await wrapper.vm.confirmLeave()).toBe(false)
      vi.mocked(createFinanceReceipt).mockResolvedValue({ id: 'receipt', status: 'ACTIVE' } as Receipt)
      await button(wrapper, '重试原提交').trigger('click'); await flushPromises()
      expect(vi.mocked(createFinanceReceipt).mock.calls[0]).toEqual(vi.mocked(createFinanceReceipt).mock.calls[1])
      expect(wrapper.emitted('saved')).toHaveLength(1)
    } finally { wrapper.unmount() }
  })
  it('订金超出未付时保留明细并阻止提交', async () => {
    const wrapper = setup()
    try {
      await fill(wrapper)
      wrapper.findComponent({ name: 'ReceiptAccountLines' }).vm.$emit('update:modelValue', [{ key: 'line', account_id: 'account', account_etag: '"a1"', cash_amount: '101.00', fee_amount: '1.00', received_on: '2026-10-23' }])
      await flushPromises(); await button(wrapper, '保存并生效').trigger('click'); await flushPromises()
      expect(createFinanceReceipt).not.toHaveBeenCalled(); expect(wrapper.text()).toContain('超过当前未付'); expect(wrapper.text()).toContain('101.00')
    } finally { wrapper.unmount() }
  })
  it('关闭再打开不接受上次来源迟到响应', async () => {
    let finish!: (value: FinanceStatement) => void
    vi.mocked(fetchFinanceStatement).mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    const wrapper = setup()
    try {
      await wrapper.setProps({ modelValue: false }); await wrapper.setProps({ modelValue: true, initialStatementId: undefined })
      finish(statement); await flushPromises(); expect(wrapper.text()).not.toContain('YSDZD1')
      expect(button(wrapper, '保存并生效').attributes('disabled')).toBeUndefined()
    } finally { wrapper.unmount() }
  })
  it.each(['close', 'task', 'statement'])('预览迟到成功在%s后失效', async (change) => {
    const confirm = vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue(Object.assign('confirm' as const, { value: '', action: 'confirm' as const }))
    let finish!: (value: Blob) => void
    vi.mocked(fetchReceiptAttachment).mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    const wrapper = setup('GOODS')
    try {
      await flushPromises()
      wrapper.findComponent({ name: 'GoodsReceiptFields' }).vm.$emit('preview', 'receipt', { file_id: 'file', original_name: '旧水单.png' } as ReceiptFile)
      await flushPromises()
      if (change === 'close') {
        await wrapper.setProps({ modelValue: false }); await wrapper.setProps({ modelValue: true, initialStatementId: undefined })
      } else wrapper.findComponent({ name: 'ReceiptSourceSelect' }).vm.$emit(change, change === 'task'
        ? { id: 'new-task', task_number: 'NEW' } : { ...statement, id: 'new-statement' })
      await flushPromises(); finish(new Blob(['old'])); await flushPromises()
      expect(wrapper.find('img.receipt-slip-preview').exists()).toBe(false)
      expect(URL.createObjectURL).not.toHaveBeenCalled()
    } finally { wrapper.unmount(); confirm.mockRestore() }
  })
  it('只展示最后一次预览，关闭释放URL且迟到失败不污染新草稿', async () => {
    let fail!: (error: Error) => void
    vi.mocked(fetchReceiptAttachment).mockImplementationOnce(() => new Promise((_, reject) => { fail = reject }))
      .mockResolvedValueOnce(new Blob(['new']))
    const wrapper = setup('GOODS')
    try {
      await flushPromises()
      const goods = wrapper.findComponent({ name: 'GoodsReceiptFields' })
      goods.vm.$emit('preview', 'receipt', { file_id: 'old', original_name: '旧水单.png' })
      goods.vm.$emit('preview', 'receipt', { file_id: 'new', original_name: '新水单.png' })
      await flushPromises(); expect(wrapper.get('img').attributes('alt')).toBe('新水单.png')
      await wrapper.setProps({ modelValue: false })
      expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:u04-preview')
      await wrapper.setProps({ modelValue: true }); await flushPromises()
      fail(new Error('旧预览失败')); await flushPromises()
      expect(wrapper.text()).not.toContain('旧预览失败'); expect(wrapper.find('img').exists()).toBe(false)
    } finally { wrapper.unmount() }
  })
  it('较早成功的预览不能覆盖较晚选择', async () => {
    let finish!: (value: Blob) => void
    vi.mocked(fetchReceiptAttachment).mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
      .mockResolvedValueOnce(new Blob(['new']))
    const wrapper = setup('GOODS')
    try {
      await flushPromises(); const goods = wrapper.findComponent({ name: 'GoodsReceiptFields' })
      goods.vm.$emit('preview', 'receipt', { file_id: 'old', original_name: '旧水单.png' })
      goods.vm.$emit('preview', 'receipt', { file_id: 'new', original_name: '新水单.png' })
      await flushPromises(); finish(new Blob(['old'])); await flushPromises()
      expect(wrapper.get('img').attributes('alt')).toBe('新水单.png'); expect(URL.createObjectURL).toHaveBeenCalledTimes(1)
    } finally { wrapper.unmount() }
  })
  it.each(['flat', 'nested'])('第二行服务端%s错误定位字段，修改金额仅清理该字段错误', async (shape) => {
    const wrapper = setup('DEPOSIT', true)
    try {
      await flushPromises()
      const lines = [0, 1].map(index => ({ key: `line-${index}`, account_id: `account-${index}`, account_etag: '"a1"',
        cash_amount: '20.00', fee_amount: '1.00', received_on: '2026-10-23', account: { name: `账户${index}`, account_number: '00123', currency_code: 'CNY' } }))
      wrapper.findComponent({ name: 'ReceiptAccountLines' }).vm.$emit('update:modelValue', lines)
      wrapper.findComponent({ name: 'ReceiptUploads' }).vm.$emit('update:modelValue', [{ id: 'upload', status: 'UNBOUND' }])
      const field_errors = shape === 'flat'
        ? { 'account_lines.1.cash_amount': ['金额超出允许范围。'], 'account_lines.1.fee_amount': ['请核对手续费。'] }
        : { account_lines: [{}, { cash_amount: ['金额超出允许范围。'], fee_amount: ['请核对手续费。'] }] }
      vi.mocked(createFinanceReceipt).mockRejectedValueOnce({ isAxiosError: true, response: { status: 400, data: { error: { message: '输入有误', field_errors } } } })
      await flushPromises(); await button(wrapper, '保存并生效').trigger('click'); await flushPromises()
      expect(createFinanceReceipt).toHaveBeenCalledTimes(1)
      expect(wrapper.findComponent({ name: 'ReceiptAccountLines' }).props('fieldErrors')).toMatchObject({ 'account_lines.1.cash_amount': '金额超出允许范围。' })
      const rows = wrapper.findAll('.account-entry')
      expect(rows[0]!.find('.el-form-item__error').exists()).toBe(false)
      await vi.waitFor(() => expect(rows[1]!.text()).toContain('金额超出允许范围。'))
      expect(rows[1]!.text()).toContain('请核对手续费。')
      await rows[1]!.get('input[aria-label="第2行实际到账"]').setValue('19.00'); await flushPromises()
      await vi.waitFor(() => expect(rows[1]!.text()).not.toContain('金额超出允许范围。'))
      expect(rows[1]!.text()).toContain('请核对手续费。')
      expect((rows[0]!.get('input[aria-label="第1行实际到账"]').element as HTMLInputElement).value).toBe('20.00')
    } finally { wrapper.unmount() }
  })
})
