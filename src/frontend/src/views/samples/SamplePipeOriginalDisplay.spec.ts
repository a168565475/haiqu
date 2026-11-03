import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { describe, expect, it, vi } from 'vitest'
import View from './SampleMaterialIssueView.vue'

vi.mock('vue-router', () => ({ useRoute: () => ({ name: 'sample-material-issue-confirm', params: { sampleId: 'sample' } }), useRouter: () => ({ push: vi.fn() }) }))
vi.mock('@/api/samples', () => ({ fetchSample: vi.fn().mockResolvedValue({ data: { id: 'sample', request_number: 'SRQ-R2', products: [] } }) }))
vi.mock('@/api/sampleMaterialIssue', () => ({ confirmSampleMaterialIssue: vi.fn(), initiateSampleMaterialIssue: vi.fn(), fetchSampleMaterialIssue: vi.fn().mockResolvedValue({
  etag: 'v1', data: { available: true, status: 'ISSUED', statusLabel: '已领料', canConfirm: false, lines: [{ id: 'line', lineKey: 'key',
    category: 'tube', material_catalog_id: 'catalog', material_selection_snapshot: { unit_name: '根' }, unitLabel: '米', name: '原管', specification: '25',
    requestedQuantity: '5', warehouseQuantity: '3', procurementQuantity: '2', arrivedQuantity: '3', availableQuantity: '6', issuedQuantity: '6', shortageQuantity: '0',
    barCount: 2, pipeBatches: [{ balanceId: 'balance', warehouseName: '材料仓', zoneName: '一区', rawBarLengthM: '3', barCount: 2, meterQuantity: '6' }] }] } }) }))

describe('R2 样品管材显示沿原根米，不套生产支', () => {
  it('根制快照搭配业务米数，显示实际2根/6米', async () => {
    const wrapper = mount(View, { global: { plugins: [ElementPlus] } }); await flushPromises()
    expect(wrapper.find('[data-testid="readonly-issued-quantity"]').text()).toBe('2 根 / 6 米')
    expect(wrapper.findAll('.issue-table tbody td')[11]!.text()).toBe('米')
    wrapper.unmount()
  })
})
