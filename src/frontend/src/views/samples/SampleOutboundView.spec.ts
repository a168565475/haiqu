import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElMessageBox } from 'element-plus'
import { createPinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import SampleOutboundView from './SampleOutboundView.vue'
import { useAuthStore } from '@/stores/auth'

const routerPush = vi.hoisted(() => vi.fn())
const apiMocks = vi.hoisted(() => ({ deleteOutbound: vi.fn(), list: vi.fn(), summary: vi.fn(), options: vi.fn() }))
enableAutoUnmount(afterEach)
afterEach(() => vi.restoreAllMocks())

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: routerPush }),
}))

const fixture = vi.hoisted(() => ({
  row: {
    id: 'outbound-line-1',
    outbound_id: 'outbound-1',
    outbound_number: 'CK-20260902-001',
    operator_name: '陈方煜',
    operated_at: '2026-09-02T09:28:00+08:00',
    sample_request_id: 'sample-1',
    sample_request_number: 'SYGJ-20260828-016',
    product_category: '户外桌椅',
    product_name: '铝框休闲椅',
    specification: '620×680×820',
    color: '蓝灰',
    outbound_quantity: 2,
    outbound_method: 'MERCHANDISER_MAIL',
    outbound_method_display: '跟单员邮寄',
    courier_company: '顺丰速运',
    tracking_number: 'SF1234567890',
    remark: '',
  },
}))

vi.mock('@/api/samples', () => ({
  fetchSampleOutbound: apiMocks.list.mockResolvedValue({
    data: [fixture.row],
    meta: { page: 1, page_size: 50, total: 1, total_pages: 1 },
  }),
  fetchSampleOutboundSummary: apiMocks.summary.mockResolvedValue({
    outbound_today: 3,
    outbound_this_month: 18,
    mailed: 12,
    salesperson_carried: 5,
  }),
  fetchSampleOutboundOptions: apiMocks.options.mockResolvedValue({
    outbound_methods: [
      { value: 'MERCHANDISER_MAIL', label: '跟单员邮寄' },
      { value: 'SALESPERSON_CARRY', label: '业务员带走' },
      { value: 'OTHER', label: '其他' },
    ],
    product_categories: ['户外桌椅'],
  }),
  fetchSampleOutboundEligible: vi.fn().mockResolvedValue({
    data: [],
    meta: { page: 1, page_size: 100, total: 0, total_pages: 0 },
  }),
  createSampleOutbound: vi.fn(),
  deleteSampleOutbound: apiMocks.deleteOutbound.mockResolvedValue(undefined),
}))

beforeEach(() => {
  vi.clearAllMocks()
  apiMocks.list.mockResolvedValue({ data: [fixture.row], meta: { page: 1, page_size: 50, total: 1, total_pages: 1 } })
  apiMocks.summary.mockResolvedValue({ outbound_today: 3, outbound_this_month: 18, mailed: 12, salesperson_carried: 5 })
  apiMocks.options.mockResolvedValue({ outbound_methods: [{ value: 'MERCHANDISER_MAIL', label: '跟单员邮寄' }], product_categories: ['户外桌椅'] })
  apiMocks.deleteOutbound.mockResolvedValue(undefined)
})
async function render(permissions: string[] = []) {
  const pinia = createPinia()
  useAuthStore(pinia).user = { id: 1, username: 'tester', display_name: '测试员工', is_superuser: false, employee: null, permissions, data_scope: 'ALL' }
  const wrapper = mount(SampleOutboundView, { global: { plugins: [pinia, ElementPlus], stubs: { SampleOutboundCreateDialog: true } } })
  await flushPromises()
  return wrapper
}

describe('SampleOutboundView', () => {
  it('按原型合并展示规格颜色并加载真实接口结果', async () => {
    const pinia = createPinia()
    useAuthStore(pinia).user = {
      id: 1,
      username: 'tester',
      display_name: '测试员工',
      is_superuser: false,
      employee: null,
      permissions: ['samples.delete_sampleinventoryoutbound'],
      data_scope: 'ALL',
    }
    vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue(undefined as never)
    const wrapper = mount(SampleOutboundView, { global: { plugins: [pinia, ElementPlus] } })
    await flushPromises()
    await flushPromises()

    const headers = wrapper.findAll('.el-table__header-wrapper th').map((item) => item.text().trim())
    expect(headers).toEqual([
      '出库编号',
      '操作人',
      '操作时间',
      '样品跟进单号',
      '产品类别',
      '产品名称',
      '规格 / 颜色',
      '出库数',
      '出库方式',
      '快递公司',
      '快递单号 / 备注',
      '操作',
    ])
    expect(wrapper.text()).toContain('CK-20260902-001')
    expect(wrapper.text()).toContain('SYGJ-20260828-016')
    expect(wrapper.text()).toContain('跟单员邮寄')
    expect(wrapper.text()).toContain('SF1234567890')
    expect(wrapper.text()).toContain('今日出库3')
    expect(wrapper.text()).toContain('620×680×820 / 蓝灰')
    expect(wrapper.findAll('.heading-actions button').map((item) => item.text().trim())).toEqual(['样品入库', '样品出库', '样品借出'])

    await wrapper.find('.document-link').trigger('click')
    expect(routerPush).toHaveBeenCalledWith({
      name: 'sample-outbound-detail',
      params: { outboundId: 'outbound-1' },
    })

    const deleteButton = wrapper.findAll('button').find((item) => item.text().trim() === '删除')
    expect(deleteButton).toBeDefined()
    await deleteButton?.trigger('click')
    await flushPromises()
    expect(apiMocks.deleteOutbound).toHaveBeenCalledWith('outbound-1')
  })

  it('无权限禁用出库和跨页入口，未开放导出明确禁用', async () => {
    const wrapper = await render()
    expect(wrapper.findAll('.heading-actions button').every(item => item.attributes('disabled') !== undefined)).toBe(true)
    expect(wrapper.findComponent({ name: 'SampleOutboundCreateDialog' }).exists()).toBe(false)
    expect(wrapper.findAll('button').some(item => item.text() === '删除')).toBe(false)
    expect(wrapper.findAll('button').find(item => item.text() === '导出')!.attributes('disabled')).toBeDefined()
  })

  it('有权限打开出库弹窗和库存、借出路由', async () => {
    const wrapper = await render(['samples.add_sampleinventoryoutbound', 'samples.view_sampleinventoryline', 'samples.view_sampleinventoryloanline'])
    const buttons = wrapper.findAll('.heading-actions button')
    await buttons[1]!.trigger('click')
    expect(wrapper.findComponent({ name: 'SampleOutboundCreateDialog' }).attributes('modelvalue')).toBe('true')
    await buttons[0]!.trigger('click'); expect(routerPush).toHaveBeenLastCalledWith({ name: 'sample-inventory' })
    await buttons[2]!.trigger('click'); expect(routerPush).toHaveBeenLastCalledWith({ name: 'sample-loans' })
  })

  it('搜索筛选分页携带现有接口字段，重置清空条件', async () => {
    const wrapper = await render()
    await wrapper.find('input[aria-label="出库关键词"]').setValue(' SF123 ')
    for (const [label, value] of [['出库方式', 'MERCHANDISER_MAIL'], ['产品类别', '户外桌椅'], ['操作时间', 'THIS_MONTH']]) {
      wrapper.findAllComponents({ name: 'ElSelect' }).find(item => item.props('ariaLabel') === label)!.vm.$emit('update:modelValue', value)
    }
    await wrapper.find('form').trigger('submit'); await flushPromises()
    expect(apiMocks.list).toHaveBeenLastCalledWith({ page: 1, page_size: 50, ordering: '-outbound__operated_at', q: 'SF123', outbound_method: 'MERCHANDISER_MAIL', category_name: '户外桌椅', operated_period: 'THIS_MONTH' })
    const pagination = wrapper.findComponent({ name: 'ElPagination' })
    pagination.vm.$emit('update:current-page', 2); pagination.vm.$emit('current-change', 2); await flushPromises()
    expect(apiMocks.list).toHaveBeenLastCalledWith(expect.objectContaining({ page: 2 }))
    pagination.vm.$emit('update:page-size', 50); pagination.vm.$emit('size-change', 50); await flushPromises()
    expect(apiMocks.list).toHaveBeenLastCalledWith(expect.objectContaining({ page: 1, page_size: 50 }))
    await wrapper.findAll('button').find(item => item.text() === '重置')!.trigger('click'); await flushPromises()
    expect(apiMocks.list).toHaveBeenLastCalledWith({ page: 1, page_size: 50, ordering: '-outbound__operated_at' })
  })

  it('加载失败可分别重试，未知统计不显示为零', async () => {
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

  it('出库后的刷新不受未完成的旧列表、统计和选项请求覆盖', async () => {
    let oldList!: (value: unknown) => void, oldSummary!: (value: unknown) => void, oldOptions!: (value: unknown) => void
    apiMocks.list.mockImplementationOnce(() => new Promise(resolve => { oldList = resolve }))
    apiMocks.summary.mockImplementationOnce(() => new Promise(resolve => { oldSummary = resolve }))
    apiMocks.options.mockImplementationOnce(() => new Promise(resolve => { oldOptions = resolve }))
    const wrapper = await render(['samples.add_sampleinventoryoutbound'])
    expect(wrapper.findComponent({ name: 'SampleOutboundCreateDialog' }).exists()).toBe(false)
    await wrapper.findAll('button').find(button => button.text() === '样品出库')!.trigger('click')
    await flushPromises()
    wrapper.findComponent({ name: 'SampleOutboundCreateDialog' }).vm.$emit('created'); await flushPromises()
    oldList({ data: [], meta: { total: 0 } }); oldSummary({ outbound_today: 0 }); oldOptions({ outbound_methods: [], product_categories: [] })
    await flushPromises()
    expect(wrapper.text()).toContain(fixture.row.product_name)
    expect(wrapper.find('.stat-copy strong').text()).toBe('3')
    expect(wrapper.findAllComponents({ name: 'ElOption' }).some(item => item.props('value') === '户外桌椅')).toBe(true)
  })

  it('删除确认和请求期间防重复，取消不调用删除', async () => {
    let cancel!: (reason: string) => void
    const confirm = vi.spyOn(ElMessageBox, 'confirm').mockImplementation(() => new Promise((_, reject) => { cancel = reject }))
    const wrapper = await render(['samples.delete_sampleinventoryoutbound'])
    const button = wrapper.findAll('button').find(item => item.text() === '删除')!
    await button.trigger('click'); await button.trigger('click')
    expect(confirm).toHaveBeenCalledTimes(1)
    cancel('cancel'); await flushPromises()
    expect(apiMocks.deleteOutbound).not.toHaveBeenCalled()
    expect(button.attributes('disabled')).toBeUndefined()
  })

  it('其他出库方式展示备注，缺失字段和非法日期显示占位', async () => {
    apiMocks.list.mockResolvedValueOnce({ data: [{ ...fixture.row, outbound_method: 'OTHER', remark: '展会样品', specification: '', color: '', operated_at: 'invalid' }], meta: { total: 1 } })
    const wrapper = await render()
    expect(wrapper.find('.el-table__body').text()).toContain('展会样品')
    expect(wrapper.find('.el-table__body').text()).toContain('— / —')
    expect(wrapper.find('.el-table__body').text()).not.toContain('NaN')
  })
})
