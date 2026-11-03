import { shallowMount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import type { PurchaseReturn } from '@/types/purchaseReturn'
import PurchaseReturnConfirmDialog from './PurchaseReturnConfirmDialog.vue'

describe('新目录管材退货保留原根米显示', () => {
  it.each([[2, '2'], [null, '根数未记录']])('使用保存退货根数 %s', (roots, expected) => {
    const record = {
      status: 'QUALITY_GENERATED', lines: [{ id: 'line', material_catalog_id: 'catalog',
        raw_bar_length_m: '3.05', return_bar_count: roots, quantity: '6.10', unit: '米' }],
    } as unknown as PurchaseReturn
    const wrapper = shallowMount(PurchaseReturnConfirmDialog, { props: { visible: true, record, submitting: false, action: 'view' },
      global: { renderStubDefaultSlot: true } })
    const cell = wrapper.get('.return-confirm-quantity')
    expect(cell.text()).toBe(expected)
    expect(cell.element.nextElementSibling?.textContent).toBe('根')
    expect(cell.attributes('title')).toContain('3.05 米/根')
    wrapper.unmount()
  })
})
