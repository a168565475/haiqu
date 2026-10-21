import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import FinishedReceiptRecordsPanel from './FinishedReceiptRecordsPanel.vue'

const api = vi.hoisted(() => ({ records: vi.fn(), detail: vi.fn(), options: vi.fn() }))
vi.mock('vue-router', () => ({ useRoute: () => ({ query: {} }), useRouter: () => ({ replace: vi.fn() }) }))
vi.mock('@/api/finishedReceipts', () => ({ fetchFinishedRecords: api.records, fetchFinishedRecord: api.detail }))
vi.mock('@/api/inventory', () => ({ fetchFinishedGoodsFilterOptions: api.options }))
vi.mock('@/directives/horizontalOverflow', () => ({ vHorizontalOverflow: {} }))
const wrappers: ReturnType<typeof mount>[] = []
beforeEach(() => {
  vi.resetAllMocks()
  api.records.mockResolvedValue({ items: [], total: 0 })
  api.options.mockResolvedValue({ warehouses: [], zones: [] })
})
afterEach(() => wrappers.splice(0).forEach(wrapper => wrapper.unmount()))

describe('成品入库记录排除样品', () => {
  it('首次读取和筛选重置都排除样品', async () => {
    const wrapper = mount(FinishedReceiptRecordsPanel, { global: { plugins: [ElementPlus] } })
    wrappers.push(wrapper)
    await flushPromises()
    expect(api.records).toHaveBeenLastCalledWith(expect.objectContaining({ exclude_sample: true, source: '' }))
    const vm = wrapper.vm as any
    vm.source = 'ASSEMBLY'
    vm.search()
    await flushPromises()
    expect(api.records).toHaveBeenLastCalledWith(expect.objectContaining({ exclude_sample: true, source: 'ASSEMBLY' }))
    await wrapper.findAll('button').find(button => button.text() === '重置')!.trigger('click')
    await flushPromises()
    expect(api.records).toHaveBeenLastCalledWith(expect.objectContaining({ exclude_sample: true, source: '' }))
  })
})

describe('成品入库详情数量单位', () => {
  it.each(['张', '个'])('使用记录的%s单位区分数量、整箱和箱位', async unit => {
    api.detail.mockResolvedValue({
      id: 'receipt-1', receipt_number: 'CPRK-1', source_type: 'PRODUCTION_ORDER',
      unit_name: unit, received_quantity: 2001, quantity_per_box: 4,
      box_count: 500, tail_quantity: 1, occupied_box_slots: 501,
      received_before: 0, received_after: 2001, maximum_receivable: 2100,
    })
    const wrapper = mount(FinishedReceiptRecordsPanel, { global: {
      plugins: [ElementPlus], stubs: { AppWindowDialog: { template: '<div><slot /></div>' } },
    } })
    wrappers.push(wrapper)
    await (wrapper.vm as any).show('receipt-1')
    await flushPromises()
    const summary = wrapper.get('.fg-detail-summary').text()
    expect(summary).toContain(`每箱数量：4 ${unit}/箱`)
    expect(summary).toContain('整箱数：500 箱')
    expect(summary).toContain(`尾数：1 ${unit}`)
    expect(summary).toContain('占用箱位：501 箱位')
    expect(wrapper.get('.fg-helper').text()).toContain(`本单入库前 0 ${unit}，本次 2001 ${unit}`)
  })

  it('没有包装信息时保持未计算', async () => {
    api.detail.mockResolvedValue({
      id: 'receipt-1', source_type: 'PRODUCTION_ORDER', unit_name: '张',
      quantity_per_box: null, box_count: null, tail_quantity: null, occupied_box_slots: null,
    })
    const wrapper = mount(FinishedReceiptRecordsPanel, { global: {
      plugins: [ElementPlus], stubs: { AppWindowDialog: { template: '<div><slot /></div>' } },
    } })
    wrappers.push(wrapper)
    await (wrapper.vm as any).show('receipt-1')
    await flushPromises()
    expect(wrapper.get('.fg-detail-summary').findAll('span').map(span => span.text())).toEqual([
      '每箱数量：未计算', '整箱数：未计算', '尾数：未计算', '占用箱位：未计算',
    ])
  })
})
