import { flushPromises, shallowMount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '@/api/internalReceipts'
import type { SemiReceiptRecord } from '@/types/internalReceipt'
import SemiReceiptRecordsView from './SemiReceiptRecordsView.vue'

vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }) }))
vi.mock('@/api/internalReceipts', () => ({ fetchSemiReceiptRecords: vi.fn(), fetchSemiReceiptRecord: vi.fn() }))
vi.mock('@/directives/glassSpotlight', () => ({ vGlassSpotlight: {} }))
vi.mock('@/directives/horizontalOverflow', () => ({ vHorizontalOverflow: {} }))

const record: SemiReceiptRecord = {
  id: 'record-1', receipt_number: 'RK-001', source: 'INTERNAL', source_display: '厂内车缝',
  production_order: 'HT-001', product: '折叠椅', stage: '车缝完成', quantity: '20', unit: '套',
  receipt_date: '2026-10-20', status: 'CONFIRMED', warehouse: '半成品仓', zone: '一楼', actor: '仓管员', remark: '',
  attributes: { part_name: '椅套', category: '裁片', material: '涤纶', specification: '600D', color: '黑色', unit_name: '套' },
  source_detail: { required: '100', received_before: '10', received_after: '30', input_quantity: null, input_unit: '米' },
}

beforeEach(() => {
  vi.resetAllMocks()
  vi.mocked(api.fetchSemiReceiptRecords).mockResolvedValue({ items: [record], total: 1 })
})

describe('半成品入库记录原料投入展示', () => {
  it.each([
    [null, '不核算'],
    ['12.5', '12.5 米'],
    ['0', '0 米'],
    [undefined, '—'],
  ])('原料投入为 %s 时显示 %s，不把缺失核算伪装成零', async (inputQuantity, expected) => {
    const detail = structuredClone(record)
    if (inputQuantity === undefined) delete detail.source_detail!.input_quantity
    else detail.source_detail!.input_quantity = inputQuantity
    vi.mocked(api.fetchSemiReceiptRecord).mockResolvedValue(detail)
    const wrapper = shallowMount(SemiReceiptRecordsView, { global: { plugins: [ElementPlus], renderStubDefaultSlot: true } })
    try {
      await flushPromises()
      await wrapper.get('.receipt-link').trigger('click')
      await flushPromises()
      const input = wrapper.findAll('.receipt-detail-progress label').find(label => label.text().startsWith('本次对应原料投入'))!
      expect(input.find('strong').text()).toBe(expected)
      expect(input.text()).not.toContain('NaN')
      expect(api.fetchSemiReceiptRecord).toHaveBeenCalledWith('record-1')
    } finally { wrapper.unmount() }
  })
})
