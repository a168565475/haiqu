import { shallowMount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import SupplierAmountPopover from './SupplierAmountPopover.vue'

const global = { stubs: { ElPopover: { template: '<div><slot name="reference"/><slot/></div>' } } }

describe('供应商金额悬浮明细', () => {
  it('多供应商显示数量，零金额与未核价分开显示', () => {
    const wrapper = shallowMount(SupplierAmountPopover, { global, props: {
      currency: 'CNY', suppliers: [
        { supplier_name: '供应商甲', total_amount: '0.0000' },
        { supplier_name: '供应商乙', total_amount: null },
        { supplier_name: '供应商丙', total_amount: '1234.5678' },
      ],
    } })
    expect(wrapper.get('.supplier-summary-trigger').text()).toBe('共 3 家供应商')
    expect(wrapper.findAll('.supplier-popover-row strong').map(row => row.text())).toEqual(['¥0.00', '待核价', '¥1,234.5678'])
    wrapper.unmount()
  })
  it('采购进度可作为触发文字，退货使用本次金额标题和币种', () => {
    const wrapper = shallowMount(SupplierAmountPopover, { global, props: {
      currency: 'USD', label: '24/24 行 · 22家', amountTitle: '本次退货金额',
      suppliers: [{ supplier_name: '退货供应商', total_amount: '2.4690' }],
    } })
    expect(wrapper.get('.supplier-summary-trigger').text()).toBe('24/24 行 · 22家')
    expect(wrapper.get('.supplier-popover-heading').text()).toContain('本次退货金额')
    expect(wrapper.get('.supplier-popover-row strong').text()).toBe('USD 2.469')
    wrapper.unmount()
  })
  it('没有供应商时保留进度而不渲染空气泡', () => {
    const wrapper = shallowMount(SupplierAmountPopover, { global, props: { suppliers: [], label: '0/2 行 · 0家' } })
    expect(wrapper.text()).toBe('0/2 行 · 0家')
    expect(wrapper.find('.supplier-popover-list').exists()).toBe(false)
    wrapper.unmount()
  })
  it('大额采购金额保留后端全部有效位', () => {
    const wrapper = shallowMount(SupplierAmountPopover, { global, props: {
      currency: 'CNY', suppliers: [{ supplier_name: '大额供应商', total_amount: '123456789012345678.1234' }],
    } })
    expect(wrapper.get('.supplier-popover-row strong').text()).toBe('¥123,456,789,012,345,678.1234')
    wrapper.unmount()
  })
})
