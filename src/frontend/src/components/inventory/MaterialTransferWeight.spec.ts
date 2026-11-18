import { flushPromises, mount, shallowMount } from '@vue/test-utils'
import ElementPlus, { ElMessage } from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import MaterialTransferForm from './MaterialTransferForm.vue'
import MaterialTransferRecordsView from '@/views/inventory/MaterialTransferRecordsView.vue'
import * as api from '@/api/inventory'
import * as sourceApi from '@/api/inventoryMaterialSources'

vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ user: { is_superuser: true }, hasPermission: () => true }) }))
vi.mock('@/router/pageAccess', () => ({ canOpenPage: () => true }))
vi.mock('@/api/inventory', () => ({ createMaterialTransfer: vi.fn(), fetchMaterialReceivingOptions: vi.fn(), fetchMaterialTransfers: vi.fn() }))
vi.mock('@/api/inventoryMaterialSources', () => ({ fetchInboundMaterialOptions: vi.fn(), fetchInboundMaterials: vi.fn(), fetchInboundMaterial: vi.fn(), fetchInboundPublicOptions: vi.fn() }))
type Row = { quantity: string; rawLength: string; weight: string; warehouseId: string; zoneId: string; category: string; catalogId: string; catalog?: unknown; attributes: Record<string, string>; unitId: string }
type Vm = { rows: Row[]; form: { remark: string }; direction: 'IN' | 'OUT'; ready: boolean; submit: () => Promise<void>; chooseMaterial: (row: Row, id: string) => Promise<void>; sectionChanged: (category: string) => void }
const wrappers: ReturnType<typeof mount>[] = []
const catalog = {
  id: 'catalog', category_key: 'TUBE', template_key: 'TUBE', name: '测试管材', spray_enabled: false, updated_at: 'v1',
  base_warehouse_id: null, semi_warehouse_id: null,
  values: [
    { id: 'material', scope: 'BASE' as const, field_key: 'material', value: '铁', parent_id: null },
    { id: 'shape', scope: 'BASE' as const, field_key: 'shape', value: '方管', parent_id: null },
    { id: 'section', scope: 'BASE' as const, field_key: 'section_size', value: '25', parent_id: 'shape' },
    { id: 'thickness', scope: 'BASE' as const, field_key: 'thickness', value: '1.2', parent_id: null },
    { id: 'length', scope: 'BASE' as const, field_key: 'length', value: '6000', parent_id: null },
  ],
  units: [{ id: 'root-unit', scope: 'BASE' as const, unit_id: 'root', unit_name: '根' }],
}

beforeEach(() => {
  vi.resetAllMocks()
  for (const method of ['error', 'warning', 'success'] as const) vi.spyOn(ElMessage, method).mockImplementation(() => ({ close: vi.fn() }))
  vi.mocked(api.fetchMaterialReceivingOptions).mockResolvedValue({ warehouses: [{ id: 'warehouse' }], zones: [{ id: 'zone', warehouse: 'warehouse' }] } as never)
  vi.mocked(api.createMaterialTransfer).mockResolvedValue({ transfer_number: 'TF001' } as never)
  vi.mocked(sourceApi.fetchInboundMaterialOptions).mockResolvedValue({ categories: [{ key: 'TUBE', label: '管材类', templates: [{ key: 'TUBE', label: '管材', supports_spray: false, fields: [
    { key: 'material', label: '材质', kind: 'text' }, { key: 'shape', label: '截面形状', kind: 'shape' },
    { key: 'section_size', label: '规格', kind: 'dimension' }, { key: 'thickness', label: '厚度', kind: 'text' },
    { key: 'length', label: '长度', kind: 'dimension' }, { key: 'unit', label: '单位', kind: 'unit' },
  ] }] }], spray_fields: [], units: [], warehouses: [] } as never)
  vi.mocked(sourceApi.fetchInboundMaterials).mockResolvedValue({ data: [{ id: 'catalog', category_key: 'TUBE', template_key: 'TUBE', name: '测试管材', spray_enabled: false, updated_at: 'v1' }], meta: { page: 1, page_size: 200, total: 1, total_pages: 1 } } as never)
  vi.mocked(sourceApi.fetchInboundMaterial).mockResolvedValue({ data: catalog } as never)
  vi.mocked(sourceApi.fetchInboundPublicOptions).mockResolvedValue({ category_key: 'TUBE', template_key: 'TUBE', scope: 'BASE', values: catalog.values, units: [{ id: 'root', unit_name: '根' }], fields: [] })
})
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()); vi.restoreAllMocks() })
async function render() {
  const wrapper = mount(MaterialTransferForm, { global: { plugins: [ElementPlus], stubs: { SampleCatalogSelection: true, ElDatePicker: true } } })
  wrappers.push(wrapper); await flushPromises()
  const vm = wrapper.vm as unknown as Vm
  vm.form.remark = '盘点实收'
  await vm.chooseMaterial(vm.rows[0]!, 'catalog')
  Object.assign(vm.rows[0]!, { warehouseId: 'warehouse', zoneId: 'zone', rawLength: '6' })
  await flushPromises()
  await wrapper.get('input[aria-label="第 1 行数量"]').setValue('2')
  return { wrapper, vm }
}

describe('一般收发实际重量契约（模拟接口）', () => {
  it('从输入控件填写实收KG，与根数和长度独立提交', async () => {
    const { wrapper, vm } = await render()
    expect(vm.ready).toBe(false)
    await wrapper.get('input[aria-label="第 1 行实际重量"]').setValue('7.2512')
    expect(vm.ready).toBe(true); await vm.submit()
    expect(api.createMaterialTransfer).toHaveBeenCalledWith(expect.objectContaining({ direction: 'IN', items: [{
      material_catalog_id: 'catalog', material_selection: expect.objectContaining({ catalog_version: 'v1', scope: 'BASE', processing_state: 'RAW', unit_id: 'root', attributes: expect.objectContaining({ material: '铁', shape: '方管', section_size: '25' }) }), zone_id: 'zone', raw_bar_count: '2', raw_bar_length_m: '6', weight_quantity: '7.2512',
    }] }))
    expect(wrapper.emitted('saved')).toHaveLength(1)
  })
  it.each(['', '0', '-1', 'NaN', '1.23456'])('管材实际重量%s无效时不能入库', async weight => {
    const { wrapper, vm } = await render()
    await wrapper.get('input[aria-label="第 1 行实际重量"]').setValue(weight)
    expect(vm.ready).toBe(false); await vm.submit()
    expect(api.createMaterialTransfer).not.toHaveBeenCalled()
  })
  it('一般出库仅提交根数，实际KG交给库存余额分摊', async () => {
    const { wrapper, vm } = await render()
    await wrapper.get('input[aria-label="第 1 行实际重量"]').setValue('99')
    vm.direction = 'OUT'
    await flushPromises()
    expect(wrapper.find('input[aria-label="第 1 行实际重量"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('出库按库存分摊')
    expect(vm.ready).toBe(true); await vm.submit()
    const payload = vi.mocked(api.createMaterialTransfer).mock.calls[0]![0]
    expect(payload.direction).toBe('OUT')
    expect(payload.items[0]).toMatchObject({ raw_bar_count: '2', raw_bar_length_m: '6' })
    expect(payload.items[0]).not.toHaveProperty('weight_quantity')
  })
  it('普通KG物料仍用原quantity', async () => {
    const { wrapper, vm } = await render()
    const hardware = { ...catalog, id: 'hardware', category_key: 'HARDWARE', template_key: 'HARDWARE', values: [], units: [] }
    vi.mocked(sourceApi.fetchInboundMaterial).mockResolvedValueOnce({ data: hardware } as never)
    vi.mocked(sourceApi.fetchInboundPublicOptions).mockResolvedValueOnce({ category_key: 'HARDWARE', template_key: 'HARDWARE', scope: 'BASE', fields: [], values: [{ id: 'spec', scope: 'BASE', field_key: 'specification', value: 'M8', parent_id: null }], units: [{ id: 'kg', unit_name: 'KG' }] })
    const state = vm as unknown as { catalogOptions: { categories: unknown[] } }
    state.catalogOptions.categories.push({ key: 'HARDWARE', label: '五金', templates: [{ key: 'HARDWARE', fields: [{ key: 'specification', label: '规格', kind: 'text' }] }] })
    vm.sectionChanged('hardware')
    await vm.chooseMaterial(vm.rows[0]!, 'hardware')
    Object.assign(vm.rows[0]!, { warehouseId: 'warehouse', zoneId: 'zone' })
    await flushPromises(); await wrapper.get('input[aria-label="第 1 行数量"]').setValue('7.2512')
    expect(vm.ready).toBe(true); await vm.submit()
    expect(vi.mocked(api.createMaterialTransfer).mock.calls[0]![0].items[0]).toMatchObject({ quantity: '7.2512' })
    expect(vi.mocked(api.createMaterialTransfer).mock.calls[0]![0].items[0]).toMatchObject({ material_catalog_id: 'hardware', material_selection: expect.objectContaining({ unit_id: 'kg', attributes: { specification: 'M8' } }) })
    expect(vi.mocked(api.createMaterialTransfer).mock.calls[0]![0].items[0]).not.toHaveProperty('weight_quantity')
  })
  it('收发记录显示根+实际KG，缺少重量提示核对，普通KG保持quantity', async () => {
    vi.mocked(api.fetchMaterialTransfers).mockResolvedValue([{ id: 'transfer', direction: 'OUT', lines: [
      { catalog_name: '管材', quantity: '2', raw_bar_length_m: '6', weight_quantity: '7.2512', unit_name: '根' },
      { catalog_name: '缺重管材', quantity: '3', raw_bar_length_m: '6', weight_quantity: null, unit_name: '根' },
      { catalog_name: '普通KG', quantity: '4.25', raw_bar_length_m: null, unit_name: 'KG' },
    ] }] as never)
    const wrapper = shallowMount(MaterialTransferRecordsView, { global: { plugins: [ElementPlus], renderStubDefaultSlot: true } })
    wrappers.push(wrapper); await flushPromises()
    const records = wrapper.findAll('.records-table tbody tr')
    expect(records).toHaveLength(3)
    expect(records[0]!.text()).toContain('7.2512')
    expect(records[1]!.text()).toContain('重量待核对')
    expect(records[2]!.text()).toContain('4.25')
    expect(records[2]!.text()).toContain('KG')
    expect(wrapper.text()).not.toContain('/ 12 kg')
  })
})
