import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElMessageBox } from 'element-plus'
import { createPinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import SampleInventoryView from './SampleInventoryView.vue'
import { useAuthStore } from '@/stores/auth'

const routerPush = vi.hoisted(() => vi.fn())
const apiMocks = vi.hoisted(() => ({ fetchInventory: vi.fn(), deleteReceipt: vi.fn(), summary: vi.fn(), options: vi.fn() }))
enableAutoUnmount(afterEach)
afterEach(() => vi.restoreAllMocks())

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: routerPush }),
}))

const fixture = vi.hoisted(() => ({
  row: {
    id: 'inventory-line-1',
    receipt_id: 'receipt-1',
    receipt_number: 'RK-20260902-001',
    inbound_time: '2026-09-02T09:28:00+08:00',
    operator_name: '测试员工',
    sample_request_id: 'sample-1',
    sample_request_number: 'SYGJ-20260828-016',
    product_category: '户外桌椅',
    product_name: '铝框休闲椅',
    specification: '620×680×820',
    color: '蓝灰',
    sampling_quantity: 10,
    received_quantity: 10,
    outbound_quantity: 2,
    loaned_quantity: 2,
    available_quantity: 6,
    location: '样品库',
  },
}))

vi.mock('@/api/samples', () => ({
  fetchSampleInventory: apiMocks.fetchInventory.mockResolvedValue({
    data: [fixture.row],
    meta: { page: 1, page_size: 50, total: 1, total_pages: 1 },
  }),
  fetchSampleInventorySummary: apiMocks.summary.mockResolvedValue({
    month: '2026-10', current_available: 6, borrowed: 0, inbound_today: 6, outbound_today: 0, inbound_this_month: 6, outbound_this_month: 0, loaned_this_month: 0,
  }),
  fetchSampleInventoryOptions: apiMocks.options.mockResolvedValue({
    product_categories: ['户外桌椅'],
    locations: ['样品库'],
  }),
  fetchSampleInventoryEligible: vi.fn().mockResolvedValue({
    data: [],
    meta: { page: 1, page_size: 100, total: 0, total_pages: 0 },
  }),
  createSampleInventoryReceipt: vi.fn(),
  deleteSampleInventoryReceipt: apiMocks.deleteReceipt.mockResolvedValue(undefined),
}))

beforeEach(() => {
  vi.clearAllMocks()
  apiMocks.fetchInventory.mockResolvedValue({ data: [fixture.row], meta: { page: 1, page_size: 50, total: 1, total_pages: 1 } })
  apiMocks.summary.mockResolvedValue({ month: '2026-10', current_available: 6, borrowed: 0, inbound_today: 6, outbound_today: 0, inbound_this_month: 6, outbound_this_month: 0, loaned_this_month: 0, })
  apiMocks.options.mockResolvedValue({ product_categories: ['户外桌椅'], locations: ['样品库'] })
  apiMocks.deleteReceipt.mockResolvedValue(undefined)
})

async function render(permissions: string[] = []) {
  const pinia = createPinia()
  useAuthStore(pinia).user = { id: 1, username: 'tester', display_name: '测试员工', is_superuser: false, employee: null, permissions, data_scope: 'ALL' }
  const wrapper = mount(SampleInventoryView, { global: { plugins: [pinia, ElementPlus], stubs: { SampleInventoryReceiptDialog: true } } })
  await flushPromises()
  return wrapper
}

describe('SampleInventoryView', () => {
  it('以四项数字展示真实月数量，移除柱图和旧说明', async () => {
    apiMocks.summary.mockResolvedValueOnce({
      month: '2026-10', current_available: 20, borrowed: 5, inbound_today: 0, outbound_today: 0,
      inbound_this_month: 40, outbound_this_month: 10, loaned_this_month: 5,
    })
    const wrapper = await render()
    expect(wrapper.find('.sample-monthly-stat__heading').text()).toContain('本月样品 · 10月')
    expect(wrapper.findAll('.sample-monthly-stat__value').map(item => item.text())).toEqual(['40', '10', '5', '20'])
    expect(wrapper.find('.sample-monthly-stat svg').exists()).toBe(false)
    expect(wrapper.findAll('.sample-monthly-stat__label').map(item => item.text())).toEqual(['入库', '出库', '借出', '当前库存'])
    expect(wrapper.text()).not.toContain('统一管理样品库存、出库与借出记录')
    expect(wrapper.find('.inventory-tabs').exists()).toBe(false)
    expect(wrapper.find('.stats-grid').exists()).toBe(false)
    expect(wrapper.findAll('.filter-grid .el-form-item__label')).toHaveLength(0)
    const selects = wrapper.findComponent({ name: 'ElForm' }).findAllComponents({ name: 'ElSelect' })
    expect(selects.map(item => item.props('placeholder'))).toEqual(['产品类别', '入库位置', '库存状态'])
    expect(selects[2]!.props('modelValue')).toBe('AVAILABLE')
    expect(wrapper.text()).toContain('有库存（>0）')
  })

  it('真实零显示0且不绘制虚假高度，缺失字段保持未知并允许重试', async () => {
    apiMocks.summary.mockResolvedValueOnce({
      month: '2026-10', current_available: 0, borrowed: 0, inbound_today: 0, outbound_today: 0,
      inbound_this_month: 0, outbound_this_month: 0, loaned_this_month: 0,
    })
    const wrapper = await render()
    expect(wrapper.findAll('.sample-monthly-stat__value').map(item => item.text())).toEqual(['0', '0', '0', '0'])
    expect(wrapper.findAll('.sample-monthly-stat__bar')).toHaveLength(0)
    apiMocks.summary.mockResolvedValueOnce({ month: '2026-10', current_available: 6 })
    await wrapper.findAll('button').find(item => item.text() === '刷新')!.trigger('click')
    await flushPromises()
    expect(wrapper.findAll('.sample-monthly-stat__value').map(item => item.text())).toEqual(['—', '—', '—', '6'])
    expect(wrapper.find('.sample-monthly-stat__error').text()).toContain('库存统计数据不完整')
    await wrapper.findAll('button').find(item => item.text() === '重试统计')!.trigger('click')
    await flushPromises()
    expect(wrapper.find('.sample-monthly-stat__error').exists()).toBe(false)
  })

  it('展示打样数量、入库数量和扣减后的剩余库存', async () => {
    const pinia = createPinia()
    useAuthStore(pinia).user = {
      id: 1,
      username: 'tester',
      display_name: '测试员工',
      is_superuser: false,
      employee: null,
      permissions: ['samples.delete_sampleinventoryreceipt'],
      data_scope: 'ALL',
    }
    vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue(undefined as never)
    const wrapper = mount(SampleInventoryView, { global: { plugins: [pinia, ElementPlus] } })
    await flushPromises()
    await flushPromises()

    const headers = wrapper.findAll('.el-table__header-wrapper th').map((item) => item.text().trim())
    expect(headers).toEqual([
      '样品入库编号',
      '入库时间',
      '打样单号',
      '产品类别',
      '产品名称',
      '规格',
      '颜色',
      '打样数量',
      '入库数量',
      '剩余库存',
      '入库位置',
      '操作',
    ])
    const firstRowCells = wrapper.findAll('.el-table__body-wrapper .el-table__row').at(0)?.findAll('td') ?? []
    expect(firstRowCells[7]?.text().trim()).toBe('10')
    expect(firstRowCells[8]?.text().trim()).toBe('10')
    expect(firstRowCells[9]?.text().trim()).toBe('6')
    expect(wrapper.text()).toContain('RK-20260902-001')
    expect(wrapper.text()).toContain('SYGJ-20260828-016')
    expect(wrapper.text()).toContain('铝框休闲椅')
    expect(wrapper.find('.sample-monthly-stat').attributes('aria-label')).toContain('当前可用库存：6件')
    expect(wrapper.text()).toContain('有库存（>0）')
    expect(wrapper.text()).toContain('仅显示剩余库存大于 0 的入库明细')
    expect(wrapper.text()).not.toContain('未发生出库或借出')
    expect(wrapper.text()).not.toContain('已部分出库')
    expect(wrapper.text()).not.toContain('借出占用')
    expect(wrapper.text()).not.toContain('已保存视图')
    expect(apiMocks.fetchInventory).toHaveBeenCalledWith(expect.objectContaining({
      inventory_status: 'AVAILABLE',
    }))
    expect(wrapper.findAll('.heading-actions button').map((item) => item.text().trim())).toEqual(['样品入库', '样品出库', '样品借出'])

    await wrapper.find('.receipt-link').trigger('click')
    expect(routerPush).toHaveBeenCalledWith({
      name: 'sample-inventory-receipt-detail',
      params: { receiptId: 'receipt-1' },
    })

    expect(wrapper.findAll('.el-table__body-wrapper .el-table__row').at(0)?.findAll('td').at(-1)?.text()).toBe('更多')
    await wrapper.findAll('button').find(item => item.text() === '更多')!.trigger('click')
    await flushPromises()
    const menuItems = wrapper.findAllComponents({ name: 'ElDropdownItem' })
    expect(menuItems.map(item => item.text())).toEqual(['查看', '删除'])
    const deleteButton = menuItems.find((item) => item.text().trim() === '删除')
    expect(deleteButton).toBeDefined()
    await deleteButton?.get('[role="menuitem"]').trigger('click')
    await flushPromises()
    expect(apiMocks.deleteReceipt).toHaveBeenCalledWith('receipt-1')
  })

  it('统计失败显示未知而不是零，允许独立重试', async () => {
    apiMocks.summary.mockRejectedValueOnce(new Error('断网'))
    const wrapper = await render()
    expect(wrapper.findAll('.sample-monthly-stat__value').map(item => item.text())).toEqual(['—', '—', '—', '—'])
    expect(wrapper.find('[role="alert"]').text()).toContain('库存统计加载失败')
    await wrapper.findAll('button').find(item => item.text() === '重试统计')!.trigger('click')
    await flushPromises()
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    expect(wrapper.find('.sample-monthly-stat__value').text()).toBe('6')
  })

  it('无权限时禁用入库与跨页入口，并隐藏删除', async () => {
    const wrapper = await render()
    expect(wrapper.findAll('.heading-actions button').every(item => item.attributes('disabled') !== undefined)).toBe(true)
    expect(wrapper.find('.inventory-tabs').exists()).toBe(false)
    await wrapper.findAll('button').find(item => item.text() === '更多')!.trigger('click')
    await flushPromises()
    expect(wrapper.findAllComponents({ name: 'ElDropdownItem' }).map(item => item.text())).toEqual(['查看'])
    expect(wrapper.findComponent({ name: 'SampleInventoryReceiptDialog' }).exists()).toBe(false)
  })

  it('按现有权限打开入库弹窗和出库、借出页面', async () => {
    const wrapper = await render(['samples.add_sampleinventoryreceipt', 'samples.view_sampleinventoryoutboundline', 'samples.view_sampleinventoryloanline'])
    await wrapper.findAll('.heading-actions button')[0]!.trigger('click')
    expect(wrapper.findComponent({ name: 'SampleInventoryReceiptDialog' }).attributes('modelvalue')).toBe('true')
    await wrapper.findAll('.heading-actions button')[1]!.trigger('click')
    expect(routerPush).toHaveBeenLastCalledWith({ name: 'sample-outbound' })
    await wrapper.findAll('.heading-actions button')[2]!.trigger('click')
    expect(routerPush).toHaveBeenLastCalledWith({ name: 'sample-loans' })
  })

  it('搜索晚到响应不能覆盖新搜索结果，重置恢复默认库存筛选', async () => {
    const wrapper = await render()
    let resolveOld!: (result: unknown) => void
    apiMocks.fetchInventory.mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve }))
    await wrapper.find('input[aria-label="库存关键词"]').setValue('  旧产品  ')
    await wrapper.find('form').trigger('submit')
    expect(apiMocks.fetchInventory).toHaveBeenLastCalledWith(expect.objectContaining({ q: '旧产品', page: 1 }))
    apiMocks.fetchInventory.mockResolvedValueOnce({ data: [{ ...fixture.row, product_name: '新产品' }], meta: { total: 1 } })
    await wrapper.find('input[aria-label="库存关键词"]').setValue('新产品')
    await wrapper.find('form').trigger('submit'); await flushPromises()
    resolveOld({ data: [{ ...fixture.row, product_name: '旧产品' }], meta: { total: 1 } })
    await flushPromises()
    expect(wrapper.find('.el-table__body').text()).toContain('新产品')
    expect(wrapper.find('.el-table__body').text()).not.toContain('旧产品')
    await wrapper.findAll('button').find(item => item.text() === '重置')!.trigger('click'); await flushPromises()
    expect(apiMocks.fetchInventory).toHaveBeenLastCalledWith({ page: 1, page_size: 50, ordering: '-receipt__submitted_at', inventory_status: 'AVAILABLE' })
  })

  it('列表失败展示错误并允许重试，不阻断其他区域', async () => {
    apiMocks.fetchInventory.mockRejectedValueOnce(new Error('断网'))
    const wrapper = await render()
    expect(wrapper.find('.list-error').exists()).toBe(true)
    expect(wrapper.find('.sample-monthly-stat__value').text()).toBe('6')
    await wrapper.findAll('button').find(item => item.text() === '重新加载')!.trigger('click'); await flushPromises()
    expect(wrapper.find('.list-error').exists()).toBe(false)
    expect(wrapper.text()).toContain(fixture.row.receipt_number)
  })

  it('类别、库位、库存状态与分页使用真实查询契约', async () => {
    const wrapper = await render()
    for (const [label, value] of [['产品类别', '户外桌椅'], ['入库位置', '样品库'], ['库存状态', 'DEPLETED']]) {
      wrapper.findAllComponents({ name: 'ElSelect' }).find(item => item.props('ariaLabel') === label)!.vm.$emit('update:modelValue', value)
    }
    await wrapper.find('form').trigger('submit'); await flushPromises()
    expect(apiMocks.fetchInventory).toHaveBeenLastCalledWith(expect.objectContaining({ category_name: '户外桌椅', location: '样品库', inventory_status: 'DEPLETED', page: 1 }))
    const pagination = wrapper.findComponent({ name: 'ElPagination' })
    pagination.vm.$emit('update:current-page', 2); pagination.vm.$emit('current-change', 2)
    await flushPromises()
    expect(apiMocks.fetchInventory).toHaveBeenLastCalledWith(expect.objectContaining({ page: 2, page_size: 50 }))
    pagination.vm.$emit('update:page-size', 50); pagination.vm.$emit('size-change', 50)
    await flushPromises()
    expect(apiMocks.fetchInventory).toHaveBeenLastCalledWith(expect.objectContaining({ page: 1, page_size: 50 }))
  })

  it('删除确认期间不能重复发起，取消不会删除', async () => {
    let cancel!: (reason: string) => void
    const confirm = vi.spyOn(ElMessageBox, 'confirm').mockImplementation(() => new Promise((_, reject) => { cancel = reject }))
    const wrapper = await render(['samples.delete_sampleinventoryreceipt'])
    await wrapper.findAll('button').find(item => item.text() === '更多')!.trigger('click')
    await flushPromises()
    const button = wrapper.findAllComponents({ name: 'ElDropdownItem' }).find(item => item.text() === '删除')!
    await button.get('[role="menuitem"]').trigger('click'); await button.get('[role="menuitem"]').trigger('click')
    expect(confirm).toHaveBeenCalledTimes(1)
    cancel('cancel'); await flushPromises()
    expect(apiMocks.deleteReceipt).not.toHaveBeenCalled()
    expect(button.attributes('disabled')).toBeUndefined()
  })

  it('入库完成后刷新统计和选项，较慢的旧响应不覆盖新结果', async () => {
    let oldSummary!: (value: unknown) => void
    let oldOptions!: (value: unknown) => void
    apiMocks.summary.mockImplementationOnce(() => new Promise(resolve => { oldSummary = resolve }))
    apiMocks.options.mockImplementationOnce(() => new Promise(resolve => { oldOptions = resolve }))
    const wrapper = await render(['samples.add_sampleinventoryreceipt'])
    apiMocks.summary.mockResolvedValueOnce({ month: '2026-10', current_available: 12, borrowed: 0, inbound_today: 12, outbound_today: 0, inbound_this_month: 12, outbound_this_month: 0, loaned_this_month: 0, })
    apiMocks.options.mockResolvedValueOnce({ product_categories: ['新增类别'], locations: ['新增库位'] })
    expect(wrapper.findComponent({ name: 'SampleInventoryReceiptDialog' }).exists()).toBe(false)
    await wrapper.findAll('button').find(button => button.text() === '样品入库')!.trigger('click')
    await flushPromises()
    wrapper.findComponent({ name: 'SampleInventoryReceiptDialog' }).vm.$emit('created')
    await flushPromises()
    oldSummary({ month: '2026-10', current_available: 1, borrowed: 0, inbound_today: 1, outbound_today: 0, inbound_this_month: 1, outbound_this_month: 0, loaned_this_month: 0, })
    oldOptions({ product_categories: ['旧类别'], locations: ['旧库位'] })
    await flushPromises()
    expect(wrapper.find('.sample-monthly-stat__value').text()).toBe('12')
    expect(wrapper.findAllComponents({ name: 'ElOption' }).some(item => item.props('value') === '新增库位')).toBe(true)
    expect(wrapper.findAllComponents({ name: 'ElOption' }).some(item => item.props('value') === '旧库位')).toBe(false)
  })
})
