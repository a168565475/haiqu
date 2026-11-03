import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { expect, it, vi } from 'vitest'
import Lookup from './SampleInventoryLookup.vue'

vi.mock('@/api/sampleWarehouse', () => ({ fetchSampleInventoryCandidates: vi.fn().mockResolvedValue({ lines: [{ lineKey: 'pipe', candidates: [{
  balanceId: 'stock', stockMode: 'PUBLIC_V2', materialNumber: '', warehouseName: '材料仓', zoneName: '一区',
  availableQuantity: '2', unitLabel: '根', rawBarLengthM: '3.00', meterQuantity: '6.00' }] }] }) }))

it('R2 新目录仍勾选实际库存根数，1根实际3米回填供料3米', async () => {
  const line = { key: 'pipe', category: 'tube' as const, material_catalog_id: 'catalog', name: '原管', specification: '25', material: '铁', color: '',
    quantity: '5', unitId: '', unitLabel: '米', pipeInputMode: 'TOTAL_METERS' as const, notes: '', supplyQuantity: '', inventoryAllocations: [] }
  const wrapper = mount(Lookup, { props: { sampleId: 'sample', lines: [line], activeLineKey: '', modelValue: true },
    global: { plugins: [ElementPlus], stubs: { AppWindowDialog: { template: '<div><slot /><slot name="footer" /></div>' } } } })
  try {
    await flushPromises()
    await wrapper.get('input[type="checkbox"]').setValue(true)
    await wrapper.get('input[aria-label^="供料数量"]').setValue('1')
    const apply = wrapper.findAll('button').find(item => item.text() === '应用关联')!
    await apply.trigger('click'); await flushPromises()
    expect(wrapper.emitted('apply')![0]![0]).toEqual([expect.objectContaining({ supplyQuantity: '3',
      inventoryAllocations: [expect.objectContaining({ quantity: '1', rawBarLengthM: '3.00' })] })])
    expect(wrapper.findAll('.el-table__header th').map(item => item.text())).toContain('单根长度')
    await wrapper.get('input[aria-label^="供料数量"]').setValue('0.5')
    await apply.trigger('click'); await flushPromises()
    expect(wrapper.emitted('apply')).toHaveLength(1)
    expect(wrapper.text()).toContain('整数根')
  } finally { wrapper.unmount() }
})
