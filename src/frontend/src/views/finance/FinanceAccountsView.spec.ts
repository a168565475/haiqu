import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { AxiosError } from 'axios'
import FinanceAccountsView from './FinanceAccountsView.vue'
import { fetchFinanceAccounts, fetchFinanceAccount, createFinanceAccount } from '@/api/financeAccounts'
import type { FinanceAccount, FinanceAccountPage } from '@/types/financeAccounts'

const state = vi.hoisted(() => ({ allowed: true }))
vi.mock('vue-router', () => ({ onBeforeRouteLeave: vi.fn() }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ user: { is_superuser: false }, hasPermission: () => state.allowed }) }))
vi.mock('@/api/financeAccounts', () => ({ fetchFinanceAccounts: vi.fn(), fetchFinanceAccount: vi.fn(), createFinanceAccount: vi.fn(), updateFinanceAccount: vi.fn(), deleteFinanceAccount: vi.fn() }))
vi.mock('@/api/referenceData', () => ({ fetchMasterDataList: vi.fn().mockResolvedValue({ data: [{ id: 'currency', code: 'CNY', chinese_name: '人民币' }], meta: { total: 1 } }) }))
const account: FinanceAccount = { id: 'account', code: 'ZH-TEST', account_type: '银行账户', category: '基本户', name: '合成账户', account_number: '0000000000000000101', currency_id: 'currency', currency_code: 'CNY', currency_name: '人民币', status: 'ACTIVE', etag: '"v1"', can_delete: true, delete_block_reason: null, created_at: '', updated_at: '' }
const result = (data = [account]): FinanceAccountPage => ({ data, meta: { page: 1, page_size: 20, total: data.length, total_pages: 1 } })
const setup = () => mount(FinanceAccountsView, { global: { plugins: [ElementPlus], stubs: { PageContainer: { template: '<main><slot/></main>' }, AppWindowDialog: { props: ['modelValue'], template: '<div v-if="modelValue" class="dialog-test"><slot/><slot name="footer"/></div>' } } } })
const button = (wrapper: ReturnType<typeof setup>, text: string) => wrapper.findAll('button').find(item => item.text() === text)!

describe('公司账户真实请求状态管理（隔离组件测试）', () => {
  beforeEach(() => { vi.clearAllMocks(); state.allowed = true; vi.mocked(fetchFinanceAccounts).mockResolvedValue(result()); vi.mocked(fetchFinanceAccount).mockResolvedValue(account) })

  it('七列与完整文本账号；筛选新增顺序和分页请求', async () => {
    const wrapper = setup()
    try {
      await flushPromises()
      expect(wrapper.text()).toContain(account.account_number)
      expect(wrapper.text()).toContain('账户类别')
      expect(wrapper.find('.erp-list-filter-actions').text()).toMatch(/重置.*应用筛选.*新增账户/)
      expect(fetchFinanceAccounts).toHaveBeenCalledWith({ page: 1, page_size: 20, q: '' }, expect.any(AbortSignal))
      await wrapper.find('.erp-list-filters input').setValue('完整账号')
      await button(wrapper, '应用筛选').trigger('click'); await flushPromises()
      expect(fetchFinanceAccounts).toHaveBeenLastCalledWith({ page: 1, page_size: 20, q: '完整账号' }, expect.any(AbortSignal))
    } finally { wrapper.unmount() }
  })

  it('刷新失败保留结果，初始失败区别空列表', async () => {
    const wrapper = setup()
    try {
      await flushPromises()
      vi.mocked(fetchFinanceAccounts).mockRejectedValueOnce(new Error('网络失败'))
      await button(wrapper, '刷新').trigger('click'); await flushPromises()
      expect(wrapper.text()).toContain('刷新失败，保留上次结果')
      expect(wrapper.text()).toContain(account.account_number)
    } finally { wrapper.unmount() }
    vi.mocked(fetchFinanceAccounts).mockRejectedValueOnce(new Error('首次失败'))
    const failed = setup()
    try { await flushPromises(); expect(failed.text()).toContain('首次失败'); expect(failed.text()).not.toContain('暂无公司账户') } finally { failed.unmount() }
  })

  it('忽略旧请求，不让迟到响应覆盖当前搜索', async () => {
    let finish!: (value: FinanceAccountPage) => void
    vi.mocked(fetchFinanceAccounts).mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    const wrapper = setup()
    try {
      await button(wrapper, '应用筛选').trigger('click'); await flushPromises()
      finish(result([{ ...account, name: '过期结果' }]))
      await flushPromises()
      expect(wrapper.text()).not.toContain('过期结果')
      expect(wrapper.text()).toContain(account.name)
    } finally { wrapper.unmount() }
  })

  it('无权时不发账户请求、不展示新增和业务数据', async () => {
    state.allowed = false
    const wrapper = setup()
    try { await flushPromises(); expect(fetchFinanceAccounts).not.toHaveBeenCalled(); expect(wrapper.text()).toContain('没有公司账户查看权限'); expect(wrapper.text()).not.toContain('新增账户') } finally { wrapper.unmount() }
  })

  it('新增失败保留输入；超时重试使用相同键和原始体', async () => {
    const wrapper = setup()
    try {
      await flushPromises(); await button(wrapper, '新增账户').trigger('click'); await flushPromises()
      const fields = wrapper.findAll('.dialog-test .el-input input')
      await fields[0]!.setValue('银行账户'); await fields[2]!.setValue('基本户'); await fields[3]!.setValue('待保存账户'); await fields[4]!.setValue('0000000000000000101')
      const selects = wrapper.findAllComponents({ name: 'ElSelect' })
      selects[selects.length - 1]!.vm.$emit('update:modelValue', 'currency')
      await flushPromises()
      let rejectSubmission!: (error: AxiosError) => void
      vi.mocked(createFinanceAccount).mockImplementationOnce(() => new Promise((_, reject) => { rejectSubmission = reject }))
      await Promise.all([button(wrapper, '保存账户').trigger('click'), button(wrapper, '保存账户').trigger('click')]); await flushPromises()
      expect(createFinanceAccount).toHaveBeenCalledTimes(1)
      expect(button(wrapper, '保存账户').classes()).toContain('is-loading')
      rejectSubmission(new AxiosError('timeout')); await flushPromises()
      expect(wrapper.text()).toContain('提交结果尚未确认')
      vi.mocked(createFinanceAccount).mockResolvedValueOnce(account)
      await button(wrapper, '重试原提交').trigger('click'); await flushPromises()
      expect(createFinanceAccount).toHaveBeenCalledTimes(2)
      expect(vi.mocked(createFinanceAccount).mock.calls[0]).toEqual(vi.mocked(createFinanceAccount).mock.calls[1])
    } finally { wrapper.unmount() }
  })
})
