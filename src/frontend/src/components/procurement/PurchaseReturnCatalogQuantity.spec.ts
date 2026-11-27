import { shallowMount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import type { PurchaseReturn } from '@/types/purchaseReturn'
import PurchaseReturnConfirmDialog from './PurchaseReturnConfirmDialog.vue'

describe('退货基础信息', () => {
  it('样品退货先显示打样单号，其后依次显示退货、采购、入库单号', () => {
    const record = {
      sample_number: 'DY01', return_number: 'TH01', order_number: 'CG01', inbound_number: 'RK01',
      status: 'QUALITY_GENERATED', lines: [],
    } as unknown as PurchaseReturn
    const wrapper = shallowMount(PurchaseReturnConfirmDialog, {
      props: { visible: true, record, submitting: false, action: 'view' },
      global: { renderStubDefaultSlot: true },
    })
    try {
      const info = wrapper.get('.return-confirm-summary')
      expect(info.get('header strong').text()).toBe('DY01')
      expect(info.findAll('dd').slice(0, 3).map(cell => cell.text())).toEqual(['TH01', 'CG01', 'RK01'])
    } finally { wrapper.unmount() }
  })
})

describe('新目录管材退货保留原根米显示', () => {
  it('按根退货在仓库详情只显示实际退根数', () => {
    const record = { status: 'QUALITY_GENERATED', lines: [{ id: 'line', raw_bar_length_m: '3.05',
      return_bar_count: 2, quantity: '2.0000', unit: '根' }] } as unknown as PurchaseReturn
    const wrapper = shallowMount(PurchaseReturnConfirmDialog, { props: { visible: true, record, submitting: false,
      action: 'view', showPipeRoots: true }, global: { renderStubDefaultSlot: true } })
    const cell = wrapper.get('.return-confirm-quantity')
    expect(cell.text()).toBe('2')
    expect(cell.element.nextElementSibling?.textContent).toBe('根')
    expect(cell.attributes('title')).toBeUndefined()
    wrapper.unmount()
  })
  it.each([[false, '7.25'], [true, '2 根 / 7.25']])('KG管材按退货重量显示，仓库根数展示=%s', (showPipeRoots, expected) => {
    const record = { status: 'QUALITY_GENERATED', lines: [{ id: 'line', material_catalog_id: 'catalog',
      raw_bar_length_m: '3.05', return_bar_count: 2, quantity: '7.2500', unit: 'KG' }] } as unknown as PurchaseReturn
    const wrapper = shallowMount(PurchaseReturnConfirmDialog, { props: { visible: true, record, submitting: false, action: 'view', showPipeRoots }, global: { renderStubDefaultSlot: true } })
    const cell = wrapper.get('.return-confirm-quantity')
    expect(cell.text()).toBe(expected)
    expect(cell.element.nextElementSibling?.textContent).toBe('kg')
    expect(cell.attributes('title')).not.toContain('米')
    expect(cell.text()).not.toContain('6.1')
    wrapper.unmount()
  })
  it.each([null, '', 'NaN', '-1'])('KG管材缺失或非法重量%s不回退成米数或零', value => {
    const record = { status: 'QUALITY_GENERATED', lines: [{ id: 'line', raw_bar_length_m: '3.05', return_bar_count: 2, quantity: value, unit: 'KG' }] } as unknown as PurchaseReturn
    const wrapper = shallowMount(PurchaseReturnConfirmDialog, { props: { visible: true, record, submitting: false, action: 'view' }, global: { renderStubDefaultSlot: true } })
    expect(wrapper.get('.return-confirm-quantity').text()).toBe('重量待核对')
    wrapper.unmount()
  })
  it('普通KG非管材使用原quantity，不依赖管材重量字段', () => {
    const record = { status: 'QUALITY_GENERATED', lines: [{ id: 'line', raw_bar_length_m: null, quantity: '7.2500', unit: 'KG' }] } as unknown as PurchaseReturn
    const wrapper = shallowMount(PurchaseReturnConfirmDialog, { props: { visible: true, record, submitting: false, action: 'view', showPipeRoots: true }, global: { renderStubDefaultSlot: true } })
    const cell = wrapper.get('.return-confirm-quantity')
    expect(cell.text()).toBe('7.25')
    expect(cell.element.nextElementSibling?.textContent).toBe('kg')
    wrapper.unmount()
  })
  it.each([2, null])('采购退货按原米制数量显示，不因根数%s改变单位', roots => {
    const record = {
      status: 'QUALITY_GENERATED', lines: [{ id: 'line', material_catalog_id: 'catalog',
        raw_bar_length_m: '3.05', return_bar_count: roots, quantity: '6.10', unit: '米' }],
    } as unknown as PurchaseReturn
    const wrapper = shallowMount(PurchaseReturnConfirmDialog, { props: { visible: true, record, submitting: false, action: 'view' },
      global: { renderStubDefaultSlot: true } })
    const cell = wrapper.get('.return-confirm-quantity')
    expect(cell.text()).toBe('6.1')
    expect(cell.element.nextElementSibling?.textContent).toBe('米')
    expect(cell.attributes('title')).toBeUndefined()
    wrapper.unmount()
  })
})
