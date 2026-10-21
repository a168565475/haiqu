import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import FinishedGoodsOutboundDetailView from './FinishedGoodsOutboundDetailView.vue'

const api = vi.hoisted(() => ({ detail: vi.fn() }))
vi.mock('vue-router', () => ({ useRoute: () => ({ params: { outboundId: 'out-1' } }), useRouter: () => ({ push: vi.fn() }) }))
vi.mock('@/api/inventory', () => ({ fetchFinishedGoodsOutbound: api.detail }))
let wrapper: ReturnType<typeof mount> | undefined
beforeEach(() => {
  api.detail.mockReset()
  api.detail.mockResolvedValue({ id: 'out-1', outbound_number: 'CK-TEST', shipment_date: '2026-10-21',
    responsible_name_snapshot: '测试负责人', loading_fee: '12.50', other_fee: '2.00', outbound_at: '',
    lines: [{ id: 'line-1', task_number_snapshot: 'SC-TEST', product_code_snapshot: 'CODE', product_name_snapshot: '测试产品',
      material_snapshot: '钢管', order_quantity: '10', received_quantity: 6, outbound_quantity: 2, unit_name: '个',
      warehouse_name: '成品仓', location_number: 'A1', quantity_per_box: 2, box_count: 1, tail_quantity: 0 }],
    loading_images: [{ id: 'image-1', name: '装卸凭证', url: '/api/v1/test-image/' }],
  })
})
afterEach(() => wrapper?.unmount())

it('详情展示产品数量、来源仓库、负责人、费用和装卸图片', async () => {
  wrapper = mount(FinishedGoodsOutboundDetailView, { global: { plugins: [ElementPlus] } })
  await flushPromises()
  for (const text of ['CK-TEST', 'SC-TEST', '钢管', '测试负责人', '12.50', '2.00']) expect(wrapper.text()).toContain(text)
  const cells = wrapper.findAll('tbody tr:first-child td').map(cell => cell.text())
  expect(cells.slice(7, 11)).toEqual(['10 个', '6 个', '2 个', '成品仓 / A1'])
  expect(wrapper.get('img').attributes('src')).toBe('/api/v1/test-image/')
})

it('订单数量缺失显示空值，入库数量为零时仍显示真实零值', async () => {
  const detail = await api.detail()
  detail.lines[0].order_quantity = null
  detail.lines[0].received_quantity = 0
  api.detail.mockResolvedValue(detail)
  wrapper = mount(FinishedGoodsOutboundDetailView, { global: { plugins: [ElementPlus] } })
  await flushPromises()
  const cells = wrapper.findAll('tbody tr:first-child td').map(cell => cell.text())
  expect(cells.slice(7, 10)).toEqual(['—', '0 个', '2 个'])
})

it('无明细和图片时展示明细空状态，不生成附件链接', async () => {
  const detail = await api.detail()
  api.detail.mockResolvedValue({ ...detail, lines: [], loading_images: [] })
  wrapper = mount(FinishedGoodsOutboundDetailView, { global: { plugins: [ElementPlus] } })
  await flushPromises()
  expect(wrapper.get('tbody').text()).toBe('暂无出库明细')
  expect(wrapper.find('.images-card').exists()).toBe(false)
})

it('刷新失败清空旧单据并显示错误，避免显示过期详情', async () => {
  wrapper = mount(FinishedGoodsOutboundDetailView, { global: { plugins: [ElementPlus] } })
  await flushPromises()
  api.detail.mockRejectedValueOnce(new Error('network failed'))
  await wrapper.findAll('button').find(button => button.text() === '刷新')!.trigger('click')
  await flushPromises()
  expect(wrapper.text()).toContain('出货单读取失败')
  expect(wrapper.text()).not.toContain('CK-TEST')
})
