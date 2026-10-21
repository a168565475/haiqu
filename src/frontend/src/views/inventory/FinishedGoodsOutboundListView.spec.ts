import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import FinishedGoodsOutboundListView from './FinishedGoodsOutboundListView.vue'

const api = vi.hoisted(() => ({ list: vi.fn(), options: vi.fn(), push: vi.fn() }))
vi.mock('vue-router', () => ({ useRoute: () => ({ query: { product_line_id: 'task-line' } }), useRouter: () => ({ push: api.push }) }))
vi.mock('@/api/inventory', () => ({ fetchFinishedGoodsOutbounds: api.list, fetchFinishedGoodsFilterOptions: api.options }))
vi.mock('@/directives/glassSpotlight', () => ({ vGlassSpotlight: {} }))
vi.mock('@/directives/horizontalOverflow', () => ({ vHorizontalOverflow: {} }))
let wrapper: ReturnType<typeof mount> | undefined
const fixture = () => ({ total: 1, items: [{
  id: 'out-1', outbound_number: 'CK-001', shipment_date: '2026-10-21', responsible_employee_name: '负责人', loading_fee: '12.50', other_fee: '2.00',
  lines: [
    { id: 'line-1', product_code_snapshot: 'CODE-A', product_name_snapshot: '产品A', specification_snapshot: '10×20', actual_color: '红', order_quantity: 2000, received_quantity: 800, outbound_quantity: 300, unit_name: '箱', warehouse_name: '成品仓A' },
    { id: 'line-2', product_code_snapshot: 'CODE-B', product_name_snapshot: '产品B', specification_snapshot: '20×30', actual_color: '蓝', order_quantity: 1500, received_quantity: 600, outbound_quantity: 200, unit_name: '个', warehouse_name: '成品仓B' },
  ],
}] })
beforeEach(() => {
  vi.resetAllMocks()
  api.list.mockResolvedValue(fixture())
  api.options.mockResolvedValue({ warehouses: [{ id: 'warehouse-a', warehouse_name: '成品仓A' }], zones: [] })
})
afterEach(() => wrapper?.unmount())

it('同单不同产品逐行保留各自数量、单位和仓库，整单费用及分页不重复', async () => {
  wrapper = mount(FinishedGoodsOutboundListView, { global: { plugins: [ElementPlus] } })
  await flushPromises()
  const rows = wrapper.findAll('tbody tr')
  expect(rows).toHaveLength(2)
  for (const value of ['CODE-A', '产品A', '10×20', '红', '2,000', '800', '300', '箱', '成品仓A']) expect(rows[0].text()).toContain(value)
  for (const value of ['CODE-B', '产品B', '20×30', '蓝', '1,500', '600', '200', '个', '成品仓B']) expect(rows[1].text()).toContain(value)
  expect(wrapper.text().match(/12\.50/g)).toHaveLength(1)
  expect(rows[0].get('td').attributes('rowspan')).toBe('2')
  expect(rows.every(row => row.classes().includes('last-document'))).toBe(true)
  expect(rows[0].findAll('.document-cell')).toHaveLength(6)
  expect(rows[1].findAll('.document-cell')).toHaveLength(0)
  expect(wrapper.get('footer').text()).toContain('共 1 张')
  expect(wrapper.find('.breadcrumb').exists()).toBe(false)
  expect(wrapper.find('.sub-title').exists()).toBe(false)
  await wrapper.findAll('button').find(button => button.text() === '查看出货单')!.trigger('click')
  expect(api.push).toHaveBeenCalledWith({ name: 'finished-goods-outbound-detail', params: { outboundId: 'out-1' } })
})

it('应用与重置向服务端传递筛选，翻页使用已应用值并保留产品范围', async () => {
  wrapper = mount(FinishedGoodsOutboundListView, { global: { plugins: [ElementPlus] } })
  await flushPromises()
  const input = wrapper.get('input[placeholder="搜索出货单号、生产任务单号或产品信息"]')
  await input.setValue(' CODE-A ')
  ;(wrapper.vm as any).warehouse = 'warehouse-a'
  await wrapper.findAll('button').find(button => button.text() === '应用筛选')!.trigger('click')
  await flushPromises()
  expect(api.list).toHaveBeenLastCalledWith(expect.objectContaining({ q: 'CODE-A', warehouse_id: 'warehouse-a', product_line_id: 'task-line', page: 1 }))
  await input.setValue('未应用的关键词')
  const pagination = wrapper.findComponent({ name: 'ElPagination' })
  pagination.vm.$emit('update:current-page', 2); pagination.vm.$emit('current-change', 2)
  await flushPromises()
  expect(api.list).toHaveBeenLastCalledWith(expect.objectContaining({ q: 'CODE-A', page: 2 }))
  await wrapper.findAll('button').find(button => button.text() === '重置')!.trigger('click')
  await flushPromises()
  expect(api.list).toHaveBeenLastCalledWith(expect.objectContaining({ q: undefined, warehouse_id: undefined, page: 1, product_line_id: 'task-line' }))
})

it('失败后清除旧明细；来源数量缺失显示未知，真实零值保留', async () => {
  const data = fixture()
  Object.assign(data.items[0].lines[0], { order_quantity: null, received_quantity: 0 })
  api.list.mockResolvedValue(data)
  wrapper = mount(FinishedGoodsOutboundListView, { global: { plugins: [ElementPlus] } })
  await flushPromises()
  expect(wrapper.findAll('tbody tr')[0].findAll('td').slice(8, 11).map(cell => cell.text())).toEqual(['—', '0', '300'])
  api.list.mockRejectedValueOnce(new Error('unavailable'))
  await wrapper.findAll('button').find(button => button.text() === '应用筛选')!.trigger('click')
  await flushPromises()
  expect(wrapper.text()).toContain('出库记录读取失败')
  expect(wrapper.text()).not.toContain('CODE-A')
})
