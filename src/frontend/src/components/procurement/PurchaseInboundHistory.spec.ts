import { shallowMount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import type { PurchaseReadInbound, PurchaseReadInboundLine } from '@/types/purchaseOrderReadDetail'
import PurchaseInboundHistory from './PurchaseInboundHistory.vue'

vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ identityReady: true, user: { id: 'user', is_superuser: true } }) }))

function mountHistory(overrides: Partial<PurchaseReadInboundLine> = {}, showPipeRoots = false) {
  const line = { id: 'line', source_unit_text_snapshot: 'KG', measurement_kind: 'PIPE', raw_bar_length_m: '3.05',
    received_quantity: '61', accepted_quantity: '54.9', return_quantity: '6.1',
    received_bar_count: 20, accepted_bar_count: 18, return_bar_count: 2,
    received_weight_kg: '25.2500', accepted_weight_kg: '22.7500', return_weight_kg: '2.5000', ...overrides } as PurchaseReadInboundLine
  return shallowMount(PurchaseInboundHistory, { props: { purchaseOrderId: 'order', showPipeRoots, inbounds: [{ id: 'inbound', status: 'CONFIRMED', created_at: '2026-11-07', lines: [line] } as PurchaseReadInbound] },
    global: { stubs: { ElIcon: true, ElButton: true, ElTag: true, ElTooltip: true }, renderStubDefaultSlot: true } })
}

it.each([['生产任务单号', 'HT-001'], ['打样单号', 'DY-001']])('仓库弹窗在原批次摘要先显示%s', async (label, number) => {
  const wrapper = mountHistory()
  const [record] = wrapper.props('inbounds')!
  await wrapper.setProps({ inbounds: [{ ...record!, inbound_number: 'RK-001' }] })
  expect(wrapper.get('.summary-main > strong:nth-child(2)').text()).toBe('RK-001')
  await wrapper.setProps({ embedded: true, expandSingle: true, receiptReference: { label, number, purchaseOrderNumber: 'CG-001' } })
  expect(wrapper.findAll('.summary-main > span').slice(0, 3).map(field => field.text())).toEqual([
    `${label} ${number}`, '入库单号 RK-001', '采购单号 CG-001',
  ])
  expect(wrapper.findAll('.summary-main strong').map(field => field.text())).toEqual([number])
  wrapper.unmount()
})

describe('采购入库历史重量口径', () => {
  it('逐次显示已登记分区，历史未登记的记录明确标示', async () => {
    const wrapper = mountHistory()
    expect(wrapper.get('[data-testid="inbound-material-section"]').text()).toBe('材料分区 未登记')
    const [old] = wrapper.props('inbounds')!
    await wrapper.setProps({ inbounds: [{ ...old!, id: 'new', material_section: 'B', material_section_display: '五金件、塑料件、包材' }, old!] })
    expect(wrapper.findAll('[data-testid="inbound-material-section"]').map(field => field.text()))
      .toEqual(['材料分区 五金件、塑料件、包材', '材料分区 未登记'])
    wrapper.unmount()
  })
  it.each([false, true])('按根收货的采购和仓库记录都使用实收、合格、退货根数（仓库 %s）', showPipeRoots => {
    const wrapper = mountHistory({ received_weight_kg: null, accepted_weight_kg: null, return_weight_kg: null,
      calculation_snapshot: { receipt_quantity_mode: 'ROOTS' } }, showPipeRoots)
    expect(wrapper.findAll('tbody td.numeric').map(cell => cell.text())).toEqual(['20 根', '18 根', '2 根'])
    wrapper.unmount()
  })
  it('KG管材使用实际重量，隐藏根数与旧米数', () => {
    const wrapper = mountHistory()
    expect(wrapper.findAll('tbody td.numeric').map(cell => cell.text())).toEqual(['25.25 kg', '22.75 kg', '2.5 kg'])
    wrapper.unmount()
  })
  it('仓库入口显示已记录根数和实际重量', () => {
    const wrapper = mountHistory({}, true)
    expect(wrapper.findAll('tbody td.numeric').map(cell => cell.text())).toEqual(['20 根 / 25.25 kg', '18 根 / 22.75 kg', '2 根 / 2.5 kg'])
    wrapper.unmount()
  })
  it('仓库缺根数或重量时分别提示，不用米数回填', () => {
    const wrapper = mountHistory({ received_bar_count: null, accepted_weight_kg: null }, true)
    expect(wrapper.findAll('tbody td.numeric').map(cell => cell.text())).toEqual(['根数未记录 / 25.25 kg', '18 根 / 重量待核对', '2 根 / 2.5 kg'])
    wrapper.unmount()
  })
  it.each([null, '', 'NaN', '-1'])('KG管材无效重量%s不退回旧米数或零', value => {
    const wrapper = mountHistory({ received_weight_kg: value, accepted_weight_kg: value, return_weight_kg: value })
    expect(wrapper.findAll('tbody td.numeric').map(cell => cell.text())).toEqual(['重量待核对', '重量待核对', '重量待核对'])
    wrapper.unmount()
  })
  it('普通KG材料仍读取原quantity', () => {
    const wrapper = mountHistory({ measurement_kind: 'QUANTITY', raw_bar_length_m: null, received_weight_kg: null, accepted_weight_kg: null, return_weight_kg: null }, true)
    expect(wrapper.findAll('tbody td.numeric').map(cell => cell.text())).toEqual(['61 kg', '54.9 kg', '6.1 kg'])
    wrapper.unmount()
  })
  it('五金重量入库使用重量字段，不显示个数', () => {
    const wrapper = mountHistory({ measurement_kind: 'HARDWARE_WEIGHT', raw_bar_length_m: null, received_quantity: '12', accepted_quantity: '10.5', return_quantity: '1.5', received_weight_kg: '0.0475', accepted_weight_kg: '0.04', return_weight_kg: '0.0075' })
    expect(wrapper.findAll('tbody td.numeric').map(cell => cell.text())).toEqual(['0.0475 kg', '0.04 kg', '0.0075 kg'])
    wrapper.unmount()
  })
  it('旧米制管材采购历史只显示采购米数', () => {
    const wrapper = mountHistory({ source_unit_text_snapshot: '米' })
    expect(wrapper.findAll('tbody td.numeric').map(cell => cell.text())).toEqual(['61 米', '54.9 米', '6.1 米'])
    wrapper.unmount()
  })
  it.each(['KG', '千克', '公斤'])('五金%s采购的历史重量不拿数量顶替，原单位KG不显示件数', unit => {
    const wrapper = mountHistory({ measurement_kind: 'HARDWARE_WEIGHT', raw_bar_length_m: null,
      source_unit_text_snapshot: unit, piece_unit: unit, received_quantity: '1000', accepted_quantity: '900', return_quantity: '100',
      received_weight_kg: '4.5', accepted_weight_kg: '3.9', return_weight_kg: null }, true)
    expect(wrapper.findAll('tbody td.numeric').map(cell => cell.text())).toEqual(['4.5 kg', '3.9 kg', '重量待核对'])
    expect(wrapper.text()).not.toContain('参考')
    wrapper.unmount()
  })
  it('五金历史缺参考个数时明确未知，不把公斤数量换成个数', () => {
    const wrapper = mountHistory({ measurement_kind: 'HARDWARE_WEIGHT', raw_bar_length_m: null, piece_unit: '个',
      received_piece_count: null, accepted_piece_count: null, return_piece_count: null,
      received_quantity: '4.5', accepted_quantity: '3.9', return_quantity: '0.6' }, true)
    expect(wrapper.findAll('tbody td.numeric').map(cell => cell.text())).toEqual([
      '25.25 kg / 参考数量未记录', '22.75 kg / 参考数量未记录', '2.5 kg / 参考数量未记录',
    ])
    wrapper.unmount()
  })
  it.each(['个', '片'])('仓库五金历史同时显示%s数和实际KG，缺重不拿个数顶替', unit => {
    const wrapper = mountHistory({ measurement_kind: 'HARDWARE_WEIGHT', raw_bar_length_m: null,
      piece_unit: unit, received_quantity: '1000', accepted_quantity: '900', return_quantity: '100',
      received_piece_count: '1000', accepted_piece_count: '900', return_piece_count: '100',
      received_weight_kg: '4.5', accepted_weight_kg: '3.9', return_weight_kg: null }, true)
    expect(wrapper.findAll('tbody td.numeric').map(cell => cell.text())).toEqual([
      `4.5 kg / 约 1,000 ${unit}（参考）`, `3.9 kg / 约 900 ${unit}（参考）`, `重量待核对 / 约 100 ${unit}（参考）`,
    ])
    wrapper.unmount()
  })
})
