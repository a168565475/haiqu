import { flushPromises, shallowMount } from '@vue/test-utils'
import ElementPlus, { ElMessage } from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import Dialog from './ManualMaterialInboundDialog.vue'
import * as api from '@/api/inventory'
import type { SampleMaterialLine } from '@/types/sampleMaterial'
import type { MaterialCatalog } from '@/types/materialCatalog'
import type { MaterialReceivingOptions } from '@/types/inventory'

const permission = vi.hoisted(() => ({ allowed: true }))
const identity = vi.hoisted(() => ({ user: { id: 7 }, initialized: true, identityReady: true, identityGeneration: 0, identityRequestGeneration: 0, hasPermission: () => permission.allowed }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => identity }))
vi.mock('@/api/inventory', () => ({ createManualMaterialReceipt: vi.fn(), fetchManualMaterialOptions: vi.fn(), fetchMaterialReceivingOptions: vi.fn() }))
type Row = { key: string; categoryId: string; rawMaterialId: string; warehouseId: string; zoneId: string; quantity: string; rawLength: string; weight: string; selection: SampleMaterialLine; loadedCatalogId: string }
type Vm = {
  form: { inboundDate: string; remark: string }; rows: Row[]; ready: boolean; rejected: boolean; submitting: boolean; canEdit: boolean
  inventoryOptions: MaterialReceivingOptions
  addRow: () => void; removeRow: (key: string) => void; categoryChanged: (row: Row) => void; warehouseChanged: (row: Row) => void
  openSelection: (row: Row) => void; updateSelection: (value: SampleMaterialLine) => void; catalogLoaded: (catalog: MaterialCatalog) => void
  submit: () => Promise<void>; editRejected: () => void
}
const selection = { catalog_version: 'v1', scope: 'BASE' as const, processing_state: 'RAW' as const, attributes: { specification: '25' }, unit_id: 'root' }
const ownedKey = 'manual-material-inbound-request-id:user:7'
const wrappers: ReturnType<typeof shallowMount>[] = []
async function mountDialog() {
  const wrapper = shallowMount(Dialog, { global: { plugins: [ElementPlus], renderStubDefaultSlot: true } })
  wrappers.push(wrapper); await flushPromises()
  return { wrapper, vm: wrapper.vm as unknown as Vm }
}
async function fillPipe(row: Row) {
  Object.assign(row, { categoryId: 'tube', warehouseId: 'warehouse', zoneId: 'zone' })
  Object.assign(row.selection, { category: 'tube', material_catalog_id: 'catalog', material_selection: { ...selection }, name: '铁管', specification: '25', unitId: 'root', unitLabel: '根' })
  await flushPromises(); row.quantity = '2'; row.rawLength = '6'; row.weight = '7.2500'
}
async function fillFabric(row: Row) {
  Object.assign(row, { categoryId: 'fabric', warehouseId: 'manual-warehouse', zoneId: 'manual-zone' })
  Object.assign(row.selection, { category: 'fabric', material_catalog_id: 'fabric-catalog', material_selection: { ...selection, unit_id: 'meter' }, name: '面料', specification: '150', unitId: 'meter', unitLabel: '米' })
  await flushPromises(); row.quantity = '1.25'; row.rawLength = ''
}
async function render() {
  const result = await mountDialog(); result.vm.form.remark = '真实来源说明'
  await fillPipe(result.vm.rows[0]!); return result
}
beforeEach(() => {
  vi.resetAllMocks(); sessionStorage.clear(); permission.allowed = true
  Object.assign(identity, { user: { id: 7 }, initialized: true, identityReady: true, identityGeneration: 0, identityRequestGeneration: 0 })
  for (const method of ['error', 'warning', 'success'] as const) vi.spyOn(ElMessage, method).mockImplementation(() => ({ close: vi.fn() }))
  vi.mocked(api.fetchManualMaterialOptions).mockResolvedValue({ categories: [{ id: 'tube', name: '管材' }], materials: [{ id: 'pipe', category_name: '管材', material_name: '铁管', unit_name: '根' }] } as never)
  vi.mocked(api.fetchMaterialReceivingOptions).mockResolvedValue({ warehouses: [{ id: 'warehouse' }, { id: 'manual-warehouse' }, { id: 'multi-zone-warehouse' }], zones: [
    { id: 'zone', warehouse: 'warehouse' }, { id: 'manual-zone', warehouse: 'manual-warehouse' },
    { id: 'zone-a', warehouse: 'multi-zone-warehouse' }, { id: 'zone-b', warehouse: 'multi-zone-warehouse' },
  ] } as never)
  vi.mocked(api.createManualMaterialReceipt).mockResolvedValue({ inbound_number: 'RK001' } as never)
})
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()); vi.restoreAllMocks() })

describe('批量材料入库弹窗契约（模拟接口，不写真实库存）', () => {
  it('不同材料和库区作为同一张单一次提交，管材保持根数和实际长度', async () => {
    const { wrapper, vm } = await render(); vm.addRow(); await fillFabric(vm.rows[1]!)
    expect(vm.ready).toBe(true); await vm.submit()
    expect(api.createManualMaterialReceipt).toHaveBeenCalledTimes(1)
    expect(api.createManualMaterialReceipt).toHaveBeenCalledWith(expect.objectContaining({ remark: '真实来源说明', items: [
      { material_catalog_id: 'catalog', material_selection: selection, zone_id: 'zone', received_bar_count: '2', raw_bar_length_m: '6', received_weight_kg: '7.2500' },
      { material_catalog_id: 'fabric-catalog', material_selection: { ...selection, unit_id: 'meter' }, zone_id: 'manual-zone', received_quantity: '1.25' },
    ] }))
    expect(api.fetchManualMaterialOptions).not.toHaveBeenCalled()
    expect(wrapper.emitted('saved')).toHaveLength(1)
    expect(ElMessage.success).toHaveBeenCalledWith(expect.stringContaining('RK001'))
    expect(vm.ready).toBe(false); await vm.submit()
    expect(api.createManualMaterialReceipt).toHaveBeenCalledTimes(1)
  })
  it.each(['', '0', '-1', 'NaN', '1.23456'])('新管材入库重量%s不合法时不提交', async weight => {
    const { vm } = await render(); vm.rows[0]!.weight = weight
    expect(vm.ready).toBe(false); await vm.submit()
    expect(api.createManualMaterialReceipt).not.toHaveBeenCalled()
  })
  it('新增行不完整时整单不提交，删除该草稿后保留原行身份与内容', async () => {
    const { vm } = await render(); const firstKey = vm.rows[0]!.key
    vm.addRow(); const blankKey = vm.rows[1]!.key
    expect(blankKey).not.toBe(firstKey); expect(vm.ready).toBe(false)
    await vm.submit(); expect(api.createManualMaterialReceipt).not.toHaveBeenCalled()
    vm.removeRow(blankKey)
    expect(vm.rows).toHaveLength(1); expect(vm.rows[0]!.key).toBe(firstKey)
    expect(vm.rows[0]!.quantity).toBe('2'); expect(vm.ready).toBe(true)
    vm.removeRow(firstKey); expect(vm.rows).toHaveLength(1)
  })
  it('最多保留100行，删除中间行后其他行不会串数据', async () => {
    const { vm } = await render(); vm.addRow(); await fillFabric(vm.rows[1]!)
    const fabricKey = vm.rows[1]!.key
    for (let index = 0; index < 105; index++) vm.addRow()
    expect(vm.rows).toHaveLength(100); expect(new Set(vm.rows.map(row => row.key)).size).toBe(100)
    vm.removeRow(vm.rows[0]!.key)
    expect(vm.rows[0]!.key).toBe(fabricKey); expect(vm.rows[0]!.selection.name).toBe('面料'); expect(vm.rows[0]!.quantity).toBe('1.25')
    vm.addRow(); expect(vm.rows).toHaveLength(100)
  })
  it('每行独立改变品类和单位，选料仅更新当前行', async () => {
    const { vm } = await render(); vm.addRow(); await fillFabric(vm.rows[1]!)
    const first = vm.rows[0]!, second = vm.rows[1]!
    vm.openSelection(second)
    vm.updateSelection({ ...second.selection, unitId: 'kg', unitLabel: '公斤', material_selection: { ...selection, unit_id: 'kg' } })
    await flushPromises()
    expect(second.quantity).toBe(''); expect(second.rawLength).toBe('')
    expect(first.quantity).toBe('2'); expect(first.rawLength).toBe('6'); expect(first.selection.unitLabel).toBe('根')
    second.categoryId = 'hardware'; vm.categoryChanged(second)
    expect(second.selection.material_catalog_id).toBeFalsy(); expect(second.selection.category).toBe('hardware')
    expect(first.selection.material_catalog_id).toBe('catalog')
  })
  it('默认仓只作用于当前行，同材料重新加载不覆盖手选仓，多库区不猜选', async () => {
    const { vm } = await render(); vm.addRow(); await fillFabric(vm.rows[1]!)
    const first = vm.rows[0]!, second = vm.rows[1]!
    vm.openSelection(second); vm.catalogLoaded({ id: 'fabric-catalog', base_warehouse_id: 'warehouse' } as MaterialCatalog)
    expect(second.warehouseId).toBe('warehouse'); expect(second.zoneId).toBe('zone')
    second.warehouseId = 'manual-warehouse'; vm.warehouseChanged(second)
    vm.catalogLoaded({ id: 'fabric-catalog', base_warehouse_id: 'warehouse' } as MaterialCatalog)
    expect(second.warehouseId).toBe('manual-warehouse'); expect(second.zoneId).toBe('manual-zone')
    second.warehouseId = 'multi-zone-warehouse'; vm.warehouseChanged(second)
    expect(second.zoneId).toBe(''); expect(first.warehouseId).toBe('warehouse'); expect(first.zoneId).toBe('zone')
  })
  it('一般入库仅提供材料仓，半成品默认仓不能自动选中且不影响其他行', async () => {
    vi.mocked(api.fetchMaterialReceivingOptions).mockResolvedValue({ warehouses: [
      { id: 'warehouse', warehouse_type: 'MATERIAL' }, { id: 'semi-warehouse', warehouse_type: 'SEMI_FINISHED' }, { id: 'legacy-warehouse' },
    ], zones: [{ id: 'zone', warehouse: 'warehouse' }, { id: 'semi-zone', warehouse: 'semi-warehouse' }, { id: 'legacy-zone', warehouse: 'legacy-warehouse' }] } as never)
    const { vm } = await render(); vm.addRow(); await fillFabric(vm.rows[1]!)
    expect(vm.inventoryOptions.warehouses.map(item => item.id)).toEqual(['warehouse', 'legacy-warehouse'])
    expect(vm.inventoryOptions.zones.map(item => item.id)).toEqual(['zone', 'legacy-zone'])
    const first = vm.rows[0]!, second = vm.rows[1]!
    vm.openSelection(second); vm.catalogLoaded({ id: 'fabric-catalog', base_warehouse_id: 'semi-warehouse' } as MaterialCatalog)
    expect(second.warehouseId).toBe(''); expect(second.zoneId).toBe('')
    expect(first.warehouseId).toBe('warehouse'); expect(first.zoneId).toBe('zone'); expect(first.quantity).toBe('2')
    second.warehouseId = 'semi-warehouse'; second.zoneId = 'semi-zone'
    expect(vm.ready).toBe(false); await vm.submit(); expect(api.createManualMaterialReceipt).not.toHaveBeenCalled()
  })
  it('多行未知结果关闭重开后精确重放，412修正保留所有行及手选库区', async () => {
    const first = await render(); first.vm.addRow(); await fillFabric(first.vm.rows[1]!)
    vi.mocked(api.createManualMaterialReceipt).mockRejectedValueOnce(new Error('结果未知')); await first.vm.submit()
    const original = JSON.parse(JSON.stringify(vi.mocked(api.createManualMaterialReceipt).mock.calls[0]![0]))
    const raw = sessionStorage.getItem(ownedKey); first.wrapper.unmount()
    const restored = await mountDialog()
    expect(restored.vm.rows).toHaveLength(2); expect(restored.vm.rows[1]!.categoryId).toBe('fabric')
    expect(restored.vm.rows[1]!.quantity).toBe('1.25'); expect(restored.vm.rows[1]!.warehouseId).toBe('manual-warehouse')
    expect(restored.vm.rows[0]!.weight).toBe('7.2500')
    expect(restored.vm.rows[1]!.zoneId).toBe('manual-zone'); expect(sessionStorage.getItem(ownedKey)).toBe(raw)
    expect(restored.vm.canEdit).toBe(false)
    // 恢复展示的嵌套属性也不能与待重放请求共享可变引用。
    restored.vm.rows[1]!.selection.material_selection!.attributes.specification = '后改规格'
    vi.mocked(api.createManualMaterialReceipt).mockRejectedValueOnce({ response: { status: 412 } }); await restored.vm.submit()
    expect(api.createManualMaterialReceipt).toHaveBeenLastCalledWith(original)
    restored.vm.editRejected(); await flushPromises(); restored.vm.openSelection(restored.vm.rows[1]!); await flushPromises()
    const panel = restored.wrapper.findComponent({ name: 'SampleCatalogSelection' })
    expect(panel.exists()).toBe(true); expect(panel.props('modelValue').material_catalog_id).toBe('fabric-catalog')
    panel.vm.$emit('loaded', { id: 'fabric-catalog', base_warehouse_id: 'warehouse' }); await flushPromises()
    expect(restored.vm.rows[1]!.warehouseId).toBe('manual-warehouse'); expect(restored.vm.rows[1]!.quantity).toBe('1.25')
    expect(restored.vm.ready).toBe(true)
  })
  it('兼容旧单行pending格式，恢复显示但不增删原始payload字段', async () => {
    const payload = { client_request_id: '1d0ab89c-2f87-43c3-bd97-c472c18fa1ca', inbound_date: '2026-01-01', remark: '旧单行待核对', items: [{ material_catalog_id: 'old-catalog', material_selection: selection, zone_id: 'manual-zone', received_bar_count: '3', raw_bar_length_m: '6.25' }] }
    const oldSelection = { key: 'old-row', category: 'tube', name: '旧管材', specification: '25', material: '', color: '', quantity: '', notes: '', unitId: 'root', unitLabel: '根', material_catalog_id: 'old-catalog', material_selection: selection }
    const raw = JSON.stringify({ payload, selection: oldSelection }); sessionStorage.setItem(ownedKey, raw)
    const { vm } = await mountDialog()
    expect(vm.rows).toHaveLength(1); expect(vm.rows[0]!.selection.name).toBe('旧管材'); expect(vm.rows[0]!.quantity).toBe('3')
    expect(vm.rows[0]!.rawLength).toBe('6.25'); expect(vm.rows[0]!.warehouseId).toBe('manual-warehouse')
    expect(sessionStorage.getItem(ownedKey)).toBe(raw); await vm.submit()
    expect(api.createManualMaterialReceipt).toHaveBeenCalledWith(payload)
  })
  it('旧原料ID待核对记录仍按原请求重放，不转换成目录材料', async () => {
    const payload = { client_request_id: 'f32f24f0-eeb4-4113-a8ef-71308797b294', inbound_date: '2026-01-01', remark: '旧原料待核对', items: [{ raw_material_id: 'pipe', zone_id: 'zone', received_bar_count: '2', raw_bar_length_m: '6' }] }
    sessionStorage.setItem(ownedKey, JSON.stringify({ payload })); const { vm } = await mountDialog()
    expect(vm.rows[0]!.rawMaterialId).toBe('pipe'); expect(api.fetchManualMaterialOptions).toHaveBeenCalledTimes(1)
    await vm.submit(); expect(api.createManualMaterialReceipt).toHaveBeenCalledWith(payload)
  })
  it('多行待核对记录中一行损坏时保留整份记录并报错，不丢弃坏行重放其余行', async () => {
    const payload = { client_request_id: '58beb806-c3b5-4d63-93a9-1d128f106ca0', inbound_date: '2026-01-01', remark: '待核对整单', items: [
      { material_catalog_id: 'catalog', material_selection: selection, zone_id: 'zone', received_bar_count: '2', raw_bar_length_m: '6' },
      { material_catalog_id: 'fabric-catalog', material_selection: { ...selection, unit_id: 'meter' }, received_quantity: '1.25' },
    ] }
    const raw = JSON.stringify({ payload }); sessionStorage.setItem(ownedKey, raw)
    const { vm, wrapper } = await mountDialog()
    expect(vm.ready).toBe(false); await vm.submit()
    expect(api.createManualMaterialReceipt).not.toHaveBeenCalled(); expect(sessionStorage.getItem(ownedKey)).toBe(raw)
    const alert = wrapper.findComponent({ name: 'ElAlert' })
    expect(alert.props('type')).toBe('error'); expect(alert.props('title')).toContain('记录无法读取')
  })
  it.each([400, 412, 428])('明确%s校验拒绝后可修正原行，结果不明仍保留原请求', async status => {
    const { vm } = await render(); vi.mocked(api.createManualMaterialReceipt).mockRejectedValueOnce({ response: { status } })
    await vm.submit(); expect(vm.rejected).toBe(true); vm.editRejected()
    expect(vm.rows[0]!.quantity).toBe('2'); expect(sessionStorage.getItem(ownedKey)).toBeNull()
    vi.mocked(api.createManualMaterialReceipt).mockRejectedValueOnce(new Error('unknown')); await vm.submit()
    expect(vm.rejected).toBe(false); expect(sessionStorage.getItem(ownedKey)).not.toBeNull()
  })
  it('批量校验错误指出具体行和原因，并保留整单供用户修正', async () => {
    const { vm, wrapper } = await render(); vm.addRow(); await fillFabric(vm.rows[1]!)
    vi.mocked(api.createManualMaterialReceipt).mockRejectedValueOnce({ response: { status: 400, data: { error: {
      message: '请求参数校验失败。', field_errors: { items: [{}, { zone_id: ['库区不可用。'] }] },
    } } } })
    await vm.submit()
    expect(ElMessage.error).toHaveBeenCalledWith(expect.stringContaining('第 2 行'))
    expect(ElMessage.error).toHaveBeenCalledWith(expect.stringContaining('库区不可用'))
    expect(vm.rejected).toBe(true); expect(vm.canEdit).toBe(false); expect(wrapper.emitted('saved')).toBeUndefined()
    expect(JSON.parse(sessionStorage.getItem(ownedKey)!).payload.items).toHaveLength(2)
    vm.editRejected()
    expect(vm.rows).toHaveLength(2); expect(vm.rows[0]!.quantity).toBe('2'); expect(vm.rows[1]!.quantity).toBe('1.25')
    expect(vm.rows[1]!.zoneId).toBe('manual-zone'); expect(vm.canEdit).toBe(true)
  })
  it.each(['', 'historical-bare-uuid', '{broken'])('无主旧记录仅隔离保留，不生成新请求绕过 %j', async raw => {
    const key = 'manual-material-inbound-request-id'; sessionStorage.setItem(key, raw)
    const { vm } = await render(); await vm.submit()
    expect(vm.ready).toBe(false); expect(api.createManualMaterialReceipt).not.toHaveBeenCalled()
    expect(sessionStorage.getItem(key)).toBe(raw); expect(sessionStorage.getItem(ownedKey)).toBeNull()
  })
  it.each([403, 409, 500])('%s不能作为确定未入库的校验失败解锁整单', async status => {
    const { vm } = await render()
    vi.mocked(api.createManualMaterialReceipt).mockRejectedValueOnce({ response: { status } })
    await vm.submit(); const raw = sessionStorage.getItem(ownedKey)
    expect(vm.rejected).toBe(false); expect(vm.canEdit).toBe(false)
    vm.editRejected()
    expect(sessionStorage.getItem(ownedKey)).toBe(raw); expect(vm.canEdit).toBe(false)
  })
  it('结果未知锁定整单，内部当前表单变化也不能改变重放payload', async () => {
    const { vm } = await render(); vm.addRow(); await fillFabric(vm.rows[1]!)
    vi.mocked(api.createManualMaterialReceipt).mockRejectedValueOnce(new Error('unknown result')); await vm.submit()
    const original = JSON.parse(JSON.stringify(vi.mocked(api.createManualMaterialReceipt).mock.calls[0]![0]))
    expect(JSON.parse(sessionStorage.getItem(ownedKey)!).payload).toEqual(original); expect(vm.canEdit).toBe(false)
    vm.addRow(); vm.removeRow(vm.rows[1]!.key); expect(vm.rows).toHaveLength(2)
    vm.rows[0]!.quantity = '99'; vm.rows[1]!.zoneId = 'zone'; vm.form.remark = '后改内容'
    await vm.submit(); expect(api.createManualMaterialReceipt).toHaveBeenLastCalledWith(original)
  })
  it('A请求晚回成功不能删除A pending、发saved或对B生效', async () => {
    const { vm, wrapper } = await render(); let finish!: (value: never) => void
    vi.mocked(api.createManualMaterialReceipt).mockReturnValueOnce(new Promise(resolve => { finish = resolve }))
    const operation = vm.submit(); await flushPromises(); const raw = sessionStorage.getItem(ownedKey)
    identity.user = { id: 8 }; identity.identityGeneration++; identity.identityRequestGeneration++
    finish({ inbound_number: 'late' } as never); await operation
    expect(sessionStorage.getItem(ownedKey)).toBe(raw); expect(wrapper.emitted('saved')).toBeUndefined()
    expect(sessionStorage.getItem('manual-material-inbound-request-id:user:8')).toBeNull()
  })
  it('提交中禁止关闭与重复发送，网络失败后同一编号重试', async () => {
    const { wrapper, vm } = await render(); let reject!: (reason: Error) => void
    vi.mocked(api.createManualMaterialReceipt).mockReturnValueOnce(new Promise((_, fail) => { reject = fail }))
    const pending = vm.submit(); await flushPromises()
    const window = wrapper.findComponent({ name: 'AppWindowDialog' }); expect(window.props('showClose')).toBe(false)
    window.vm.$emit('update:modelValue', false); expect(wrapper.emitted('close')).toBeUndefined()
    await vm.submit(); expect(api.createManualMaterialReceipt).toHaveBeenCalledTimes(1)
    reject(new Error('网络中断')); await pending; expect(wrapper.emitted('saved')).toBeUndefined()
    expect(vm.rows[0]!.quantity).toBe('2'); expect(vm.rows[0]!.rawLength).toBe('6'); await vm.submit()
    const calls = vi.mocked(api.createManualMaterialReceipt).mock.calls
    expect(calls[0]![0].client_request_id).toBe(calls[1]![0].client_request_id)
  })
  it('普通材料保留小数，管材小数根、缺长度、未来日期和无权限不可提交', async () => {
    const { vm } = await render(); const row = vm.rows[0]!
    row.quantity = '1.5'; expect(vm.ready).toBe(false); row.quantity = '2'; row.rawLength = ''; expect(vm.ready).toBe(false)
    await fillFabric(row); expect(vm.ready).toBe(true); vm.form.inboundDate = '9999-01-01'; expect(vm.ready).toBe(false)
    await vm.submit(); expect(api.createManualMaterialReceipt).not.toHaveBeenCalled()
    permission.allowed = false; const denied = await render(); expect(denied.vm.ready).toBe(false)
  })
  it('全单备注仅含空白时不得发送，即使每条材料都有效', async () => {
    const { vm } = await render(); vm.addRow(); await fillFabric(vm.rows[1]!)
    vm.form.remark = '  \n  '
    expect(vm.ready).toBe(false); await vm.submit(); expect(api.createManualMaterialReceipt).not.toHaveBeenCalled()
    expect(sessionStorage.getItem(ownedKey)).toBeNull()
  })
})
