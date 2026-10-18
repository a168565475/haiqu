import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElMessageBox } from 'element-plus'
import { createPinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import SampleLoanView from './SampleLoanView.vue'
import { useAuthStore } from '@/stores/auth'

const routerPush = vi.hoisted(() => vi.fn())
const apiMocks = vi.hoisted(() => ({ deleteLoan: vi.fn(), list: vi.fn(), summary: vi.fn(), options: vi.fn() }))
enableAutoUnmount(afterEach)
afterEach(() => vi.restoreAllMocks())

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: routerPush }),
}))

const fixture = vi.hoisted(() => ({
  row: {
    id: 'loan-line-1',
    loan_id: 'loan-1',
    loan_number: 'JC-20260901-002',
    operator_name: '陈方煜',
    operated_at: '2026-09-01T11:08:00+08:00',
    sample_request_id: 'sample-1',
    sample_request_number: 'SYGJ-20260828-016',
    product_category: '户外桌椅',
    product_name: '铝框休闲椅',
    specification: '620×680×820',
    color: '蓝灰',
    loan_quantity: 1,
    borrower_name: '王立新',
    purpose_note: '客户现场确认',
  },
}))

vi.mock('@/api/samples', () => ({
  fetchSampleLoans: apiMocks.list.mockResolvedValue({
    data: [fixture.row],
    meta: { page: 1, page_size: 50, total: 1, total_pages: 1 },
  }),
  fetchSampleLoanSummary: apiMocks.summary.mockResolvedValue({
    active_documents: 3,
    cumulative_borrowed: 11,
    customer_confirmation: 5,
    showroom_or_photo: 6,
  }),
  fetchSampleLoanOptions: apiMocks.options.mockResolvedValue({
    borrower_names: ['王立新'],
    product_categories: ['户外桌椅'],
  }),
  fetchSampleLoanEligible: vi.fn().mockResolvedValue({
    data: [],
    meta: { page: 1, page_size: 100, total: 0, total_pages: 0 },
  }),
  createSampleLoan: vi.fn(),
  deleteSampleLoan: apiMocks.deleteLoan.mockResolvedValue(undefined),
}))

beforeEach(() => {
  vi.clearAllMocks()
  apiMocks.list.mockResolvedValue({ data: [fixture.row], meta: { page: 1, page_size: 50, total: 1, total_pages: 1 } })
  apiMocks.summary.mockResolvedValue({ active_documents: 3, cumulative_borrowed: 11, customer_confirmation: 5, showroom_or_photo: 6 })
  apiMocks.options.mockResolvedValue({ borrower_names: ['王立新'], product_categories: ['户外桌椅'] })
  apiMocks.deleteLoan.mockResolvedValue(undefined)
})
async function render(permissions: string[] = []) {
  const pinia = createPinia()
  useAuthStore(pinia).user = { id: 1, username: 'tester', display_name: '测试员工', is_superuser: false, employee: null, permissions, data_scope: 'ALL' }
  const wrapper = mount(SampleLoanView, { global: { plugins: [pinia, ElementPlus], stubs: { SampleLoanCreateDialog: true } } })
  await flushPromises()
  return wrapper
}

describe('SampleLoanView', () => {
  it('按原型合并规格颜色并加载接口结果', async () => {
    const pinia = createPinia()
    useAuthStore(pinia).user = {
      id: 1,
      username: 'tester',
      display_name: '测试员工',
      is_superuser: false,
      employee: null,
      permissions: ['samples.delete_sampleinventoryloan'],
      data_scope: 'ALL',
    }
    vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue(undefined as never)
    const wrapper = mount(SampleLoanView, { global: { plugins: [pinia, ElementPlus] } })
    await flushPromises()
    await flushPromises()

    const headers = wrapper.findAll('.el-table__header-wrapper th').map((item) => item.text().trim())
    expect(headers).toEqual([
      '借出编号',
      '操作人',
      '操作时间',
      '样品跟进单号',
      '产品类别',
      '产品名称',
      '规格 / 颜色',
      '借出数',
      '借用人',
      '用途 / 备注',
      '操作',
    ])
    expect(wrapper.text()).toContain('JC-20260901-002')
    expect(wrapper.text()).toContain('SYGJ-20260828-016')
    expect(wrapper.text()).toContain('王立新')
    expect(wrapper.text()).toContain('客户现场确认')
    expect(wrapper.text()).toContain('累计借出11')
    expect(wrapper.text()).toContain('620×680×820 / 蓝灰')
    expect(wrapper.findAll('.heading-actions button').map((item) => item.text().trim())).toEqual(['样品入库', '样品出库', '样品借出'])

    await wrapper.find('.document-link').trigger('click')
    expect(routerPush).toHaveBeenCalledWith({
      name: 'sample-loan-detail',
      params: { loanId: 'loan-1' },
    })

    const deleteButton = wrapper.findAll('button').find((item) => item.text().trim() === '删除')
    expect(deleteButton).toBeDefined()
    await deleteButton?.trigger('click')
    await flushPromises()
    expect(apiMocks.deleteLoan).toHaveBeenCalledWith('loan-1')
  })

  it('无权限时禁用借出和跨页入口，未开放导出明确禁用', async () => {
    const wrapper = await render()
    expect(wrapper.findAll('.heading-actions button').every(item => item.attributes('disabled') !== undefined)).toBe(true)
    expect(wrapper.findComponent({ name: 'SampleLoanCreateDialog' }).exists()).toBe(false)
    expect(wrapper.findAll('button').some(item => item.text() === '删除')).toBe(false)
    expect(wrapper.findAll('button').find(item => item.text() === '导出')!.attributes('disabled')).toBeDefined()
  })

  it('有权限时打开借出弹窗和库存、出库路由', async () => {
    const wrapper = await render(['samples.add_sampleinventoryloan', 'samples.view_sampleinventoryline', 'samples.view_sampleinventoryoutboundline'])
    const buttons = wrapper.findAll('.heading-actions button')
    await buttons[2]!.trigger('click')
    expect(wrapper.findComponent({ name: 'SampleLoanCreateDialog' }).attributes('modelvalue')).toBe('true')
    await buttons[0]!.trigger('click'); expect(routerPush).toHaveBeenLastCalledWith({ name: 'sample-inventory' })
    await buttons[1]!.trigger('click'); expect(routerPush).toHaveBeenLastCalledWith({ name: 'sample-outbound' })
  })

  it('搜索筛选分页传递接口条件，重置回到第一页', async () => {
    const wrapper = await render()
    await wrapper.find('input[aria-label="借出关键词"]').setValue(' 客户 ')
    for (const [label, value] of [['借用人', '王立新'], ['产品类别', '户外桌椅'], ['操作时间', 'THIS_MONTH']]) {
      wrapper.findAllComponents({ name: 'ElSelect' }).find(item => item.props('ariaLabel') === label)!.vm.$emit('update:modelValue', value)
    }
    await wrapper.find('form').trigger('submit'); await flushPromises()
    expect(apiMocks.list).toHaveBeenLastCalledWith({ page: 1, page_size: 50, ordering: '-loan__operated_at', q: '客户', borrower_name: '王立新', category_name: '户外桌椅', operated_period: 'THIS_MONTH' })
    const pagination = wrapper.findComponent({ name: 'ElPagination' })
    pagination.vm.$emit('update:current-page', 2); pagination.vm.$emit('current-change', 2); await flushPromises()
    expect(apiMocks.list).toHaveBeenLastCalledWith(expect.objectContaining({ page: 2 }))
    pagination.vm.$emit('update:page-size', 50); pagination.vm.$emit('size-change', 50); await flushPromises()
    expect(apiMocks.list).toHaveBeenLastCalledWith(expect.objectContaining({ page: 1, page_size: 50 }))
    await wrapper.findAll('button').find(item => item.text() === '重置')!.trigger('click'); await flushPromises()
    expect(apiMocks.list).toHaveBeenLastCalledWith({ page: 1, page_size: 50, ordering: '-loan__operated_at' })
  })

  it('接口失败显示错误和未知统计，重试后恢复', async () => {
    apiMocks.summary.mockRejectedValueOnce(new Error('断网'))
    apiMocks.options.mockRejectedValueOnce(new Error('断网'))
    apiMocks.list.mockRejectedValueOnce(new Error('断网'))
    const wrapper = await render()
    expect(wrapper.findAll('.stat-copy strong').map(item => item.text())).toEqual(['—', '—', '—', '—'])
    expect(wrapper.findAll('.load-error')).toHaveLength(2)
    expect(wrapper.find('.list-error').exists()).toBe(true)
    await wrapper.findAll('button').find(item => item.text() === '重新加载')!.trigger('click'); await flushPromises()
    expect(wrapper.findAll('.load-error')).toHaveLength(0)
    expect(wrapper.find('.list-error').exists()).toBe(false)
    expect(wrapper.find('.stat-copy strong').text()).toBe('3')
  })

  it('借出后的刷新不被旧列表、统计和选项请求覆盖', async () => {
    let oldList!: (value: unknown) => void, oldSummary!: (value: unknown) => void, oldOptions!: (value: unknown) => void
    apiMocks.list.mockImplementationOnce(() => new Promise(resolve => { oldList = resolve }))
    apiMocks.summary.mockImplementationOnce(() => new Promise(resolve => { oldSummary = resolve }))
    apiMocks.options.mockImplementationOnce(() => new Promise(resolve => { oldOptions = resolve }))
    const wrapper = await render(['samples.add_sampleinventoryloan'])
    expect(wrapper.findComponent({ name: 'SampleLoanCreateDialog' }).exists()).toBe(false)
    await wrapper.findAll('.heading-actions button').find(button => button.text() === '样品借出')!.trigger('click')
    await flushPromises()
    wrapper.findComponent({ name: 'SampleLoanCreateDialog' }).vm.$emit('created'); await flushPromises()
    oldList({ data: [], meta: { total: 0 } }); oldSummary({ active_documents: 0 }); oldOptions({ borrower_names: [], product_categories: [] })
    await flushPromises()
    expect(wrapper.text()).toContain(fixture.row.product_name)
    expect(wrapper.find('.stat-copy strong').text()).toBe('3')
    expect(wrapper.findAllComponents({ name: 'ElOption' }).some(item => item.props('value') === '王立新')).toBe(true)
  })

  it('删除确认防重复，取消不删除且恢复按钮', async () => {
    let cancel!: (reason: string) => void
    const confirm = vi.spyOn(ElMessageBox, 'confirm').mockImplementation(() => new Promise((_, reject) => { cancel = reject }))
    const wrapper = await render(['samples.delete_sampleinventoryloan'])
    const button = wrapper.findAll('button').find(item => item.text() === '删除')!
    await button.trigger('click'); await button.trigger('click')
    expect(confirm).toHaveBeenCalledTimes(1)
    cancel('cancel'); await flushPromises()
    expect(apiMocks.deleteLoan).not.toHaveBeenCalled()
    expect(button.attributes('disabled')).toBeUndefined()
  })

  it('缺失规格颜色、备注和非法日期使用占位', async () => {
    apiMocks.list.mockResolvedValueOnce({ data: [{ ...fixture.row, purpose_note: '', specification: '', color: '', operated_at: 'invalid' }], meta: { total: 1 } })
    const wrapper = await render()
    expect(wrapper.find('.el-table__body').text()).toContain('— / —')
    expect(wrapper.find('.el-table__body').text()).not.toContain('NaN')
  })
})
