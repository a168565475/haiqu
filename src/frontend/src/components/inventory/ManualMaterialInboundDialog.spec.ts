import { flushPromises, shallowMount } from '@vue/test-utils'
import ElementPlus, { ElMessage } from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import Dialog from './ManualMaterialInboundDialog.vue'
import * as api from '@/api/inventory'
import type { SampleMaterialLine } from '@/types/sampleMaterial'

const permission = vi.hoisted(() => ({ allowed: true }))
const identity = vi.hoisted(() => ({ user: { id: 7 }, initialized: true, identityReady: true, identityGeneration: 0, identityRequestGeneration: 0, hasPermission: () => permission.allowed }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => identity }))
vi.mock('@/api/inventory', () => ({ createManualMaterialReceipt: vi.fn(), fetchManualMaterialOptions: vi.fn(), fetchMaterialReceivingOptions: vi.fn() }))
const material = { id: 'pipe', category_name: '管材', material_number: 'M01', material_name: '铁管', specification: '20*28*0.8*6140', unit_name: '根' }
type Form = { categoryId: string; rawMaterialId: string; warehouseId: string; zoneId: string; quantity: string; rawLength: string; inboundDate: string; remark: string }
type Vm = { form: Form; selectionRow: SampleMaterialLine; ready: boolean; rejected: boolean; submitting: boolean; submit: () => Promise<void>; editRejected: () => void }
const selection = { catalog_version: 'v1', scope: 'BASE' as const, processing_state: 'RAW' as const, attributes: { specification: '25' }, unit_id: 'root' }
const wrappers: ReturnType<typeof shallowMount>[] = []
async function mountDialog() {
  const wrapper = shallowMount(Dialog, { global: { plugins: [ElementPlus], renderStubDefaultSlot: true } })
  wrappers.push(wrapper)
  await flushPromises()
  const vm = wrapper.vm as unknown as Vm
  return { wrapper, vm }
}
async function render() {
  const { wrapper, vm } = await mountDialog()
  Object.assign(vm.form, { categoryId: 'tube', rawMaterialId: 'pipe', warehouseId: 'warehouse', zoneId: 'zone', quantity: '2', rawLength: '6', remark: '真实来源说明' })
  Object.assign(vm.selectionRow, { material_catalog_id: 'catalog', material_selection: selection, name: '铁管', specification: '25', unitId: 'root', unitLabel: '根' })
  return { wrapper, vm }
}
beforeEach(() => {
  vi.resetAllMocks(); sessionStorage.clear(); permission.allowed = true
  Object.assign(identity, { user: { id: 7 }, initialized: true, identityReady: true, identityGeneration: 0, identityRequestGeneration: 0 })
  vi.spyOn(ElMessage, 'error').mockImplementation(() => ({ close: vi.fn() }))
  vi.spyOn(ElMessage, 'success').mockImplementation(() => ({ close: vi.fn() }))
  vi.mocked(api.fetchManualMaterialOptions).mockResolvedValue({ categories: [{ id: 'tube', name: '管材' }], materials: [material] } as never)
  vi.mocked(api.fetchMaterialReceivingOptions).mockResolvedValue({ warehouses: [{ id: 'warehouse' }], zones: [{ id: 'zone', warehouse: 'warehouse' }] } as never)
  vi.mocked(api.createManualMaterialReceipt).mockResolvedValue({ inbound_number: 'RK001' } as never)
})
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()); vi.restoreAllMocks() })
describe('材料入库弹窗契约（模拟接口，不写真实库存）', () => {
  it('真实持久化关闭重开后，412修正保留品类选料数量及手选库区', async () => {
    vi.mocked(api.fetchMaterialReceivingOptions).mockResolvedValue({ warehouses: [{ id: 'warehouse' }, { id: 'manual-warehouse' }],
      zones: [{ id: 'zone', warehouse: 'warehouse' }, { id: 'manual-zone', warehouse: 'manual-warehouse' }] } as never)
    const first = await render()
    Object.assign(first.vm.form, { categoryId: 'hardware', warehouseId: 'manual-warehouse', zoneId: 'manual-zone', quantity: '1.25', rawLength: '' })
    Object.assign(first.vm.selectionRow, { category: 'hardware', name: '五金', unitId: 'kg', unitLabel: '公斤', material_selection: { ...selection, unit_id: 'kg' } })
    await flushPromises()
    first.vm.form.quantity = '1.25'
    vi.mocked(api.createManualMaterialReceipt).mockRejectedValueOnce(new Error('结果未知'))
    await first.vm.submit()
    const original = JSON.parse(JSON.stringify(vi.mocked(api.createManualMaterialReceipt).mock.calls[0]![0]))
    const raw = sessionStorage.getItem('manual-material-inbound-request-id:user:7')
    first.wrapper.unmount()
    // 第二次只挂载，从真实sessionStorage恢复，绝不通过render补写categoryId。
    const restored = await mountDialog()
    expect(restored.vm.form.categoryId).toBe('hardware')
    expect(restored.vm.form.quantity).toBe('1.25')
    expect(restored.vm.form.warehouseId).toBe('manual-warehouse')
    expect(restored.vm.form.zoneId).toBe('manual-zone')
    expect(sessionStorage.getItem('manual-material-inbound-request-id:user:7')).toBe(raw)
    vi.mocked(api.createManualMaterialReceipt).mockRejectedValueOnce({ response: { status: 412 } })
    await restored.vm.submit()
    expect(api.createManualMaterialReceipt).toHaveBeenLastCalledWith(original)
    restored.vm.editRejected(); await flushPromises()
    const panel = restored.wrapper.findComponent({ name: 'SampleCatalogSelection' })
    expect(panel.exists()).toBe(true)
    expect(panel.props('modelValue').material_catalog_id).toBe('catalog')
    panel.vm.$emit('loaded', { id: 'catalog', base_warehouse_id: 'warehouse' }); await flushPromises()
    expect(restored.vm.form.categoryId).toBe('hardware')
    expect(restored.vm.form.quantity).toBe('1.25')
    expect(restored.vm.form.warehouseId).toBe('manual-warehouse')
    expect(restored.vm.form.zoneId).toBe('manual-zone')
    expect(restored.vm.ready).toBe(true)
  })

  it('明确校验拒绝后保留输入并允许修正，网络结果不明保持原请求', async () => {
    const { vm } = await render()
    vi.mocked(api.createManualMaterialReceipt).mockRejectedValueOnce({ response: { status: 412 } })
    await vm.submit()
    expect(vm.rejected).toBe(true)
    vm.editRejected()
    expect(vm.form.quantity).toBe('2')
    expect(sessionStorage.getItem('manual-material-inbound-request-id:user:7')).toBeNull()
    vi.mocked(api.createManualMaterialReceipt).mockRejectedValueOnce(new Error('unknown'))
    await vm.submit()
    expect(vm.rejected).toBe(false)
    expect(sessionStorage.getItem('manual-material-inbound-request-id:user:7')).not.toBeNull()
  })
  it.each(['', 'historical-bare-uuid', '{broken'])('legacy裸UUID/损坏值仅隔离不认领，不生成新请求绕过 %j', async raw => {
    const key = 'manual-material-inbound-request-id'; sessionStorage.setItem(key, raw)
    const { vm } = await render(); await vm.submit()
    expect(vm.ready).toBe(false); expect(api.createManualMaterialReceipt).not.toHaveBeenCalled()
    expect(sessionStorage.getItem(key)).toBe(raw); expect(sessionStorage.getItem(`${key}:user:7`)).toBeNull()
  })
  it('失败后即使修改当前表单，也只原样重试owned完整payload', async () => {
    const { vm } = await render()
    vi.mocked(api.createManualMaterialReceipt).mockRejectedValueOnce(new Error('unknown result'))
    await vm.submit()
    const original = JSON.parse(JSON.stringify(vi.mocked(api.createManualMaterialReceipt).mock.calls[0]![0]))
    const key = 'manual-material-inbound-request-id:user:7'
    expect(JSON.parse(sessionStorage.getItem(key)!).payload).toEqual(original)
    vm.form.quantity = '99'; vm.form.rawLength = '8'; vm.form.remark = '后改内容'
    await vm.submit()
    expect(api.createManualMaterialReceipt).toHaveBeenLastCalledWith(original)
  })
  it('A请求晚回成功不能删除A pending、发saved或对B生效', async () => {
    const { vm, wrapper } = await render()
    let finish!: (value: never) => void
    vi.mocked(api.createManualMaterialReceipt).mockReturnValueOnce(new Promise(resolve => { finish = resolve }))
    const operation = vm.submit(); await flushPromises()
    const key = 'manual-material-inbound-request-id:user:7', raw = sessionStorage.getItem(key)
    identity.user = { id: 8 }; identity.identityGeneration++; identity.identityRequestGeneration++
    finish({ inbound_number: 'late' } as never); await operation
    expect(sessionStorage.getItem(key)).toBe(raw); expect(wrapper.emitted('saved')).toBeUndefined()
    expect(sessionStorage.getItem('manual-material-inbound-request-id:user:8')).toBeNull()
  })
  it('管材沿用根数和单根长度，成功后通知列表关闭刷新且防止重复提交', async () => {
    const { wrapper, vm } = await render()
    expect(vm.ready).toBe(true)
    await vm.submit()
    expect(api.createManualMaterialReceipt).toHaveBeenCalledWith(expect.objectContaining({ items: [{ material_catalog_id: 'catalog', material_selection: selection, zone_id: 'zone', received_bar_count: '2', raw_bar_length_m: '6' }] }))
    expect(api.fetchManualMaterialOptions).not.toHaveBeenCalled()
    expect(wrapper.emitted('saved')).toHaveLength(1)
    expect(vm.ready).toBe(false)
  })
  it('失败保留输入和重试编号，不关闭弹窗；提交中阻止关闭', async () => {
    const { wrapper, vm } = await render()
    let reject!: (reason: Error) => void
    vi.mocked(api.createManualMaterialReceipt).mockReturnValueOnce(new Promise((_, fail) => { reject = fail }))
    const pending = vm.submit(); await flushPromises()
    const window = wrapper.findComponent({ name: 'AppWindowDialog' })
    expect(window.props('showClose')).toBe(false)
    window.vm.$emit('update:modelValue', false)
    expect(wrapper.emitted('close')).toBeUndefined()
    reject(new Error('网络中断')); await pending
    expect(wrapper.emitted('saved')).toBeUndefined()
    expect(vm.form.quantity).toBe('2'); expect(vm.form.rawLength).toBe('6')
    await vm.submit()
    const calls = vi.mocked(api.createManualMaterialReceipt).mock.calls
    expect(calls[0]![0].client_request_id).toBe(calls[1]![0].client_request_id)
  })
  it('普通材料仍提交数量，管材小数根、缺长度与无权限不可提交', async () => {
    const { vm } = await render()
    vm.form.quantity = '1.5'; expect(vm.ready).toBe(false)
    vm.form.quantity = '2'; vm.form.rawLength = ''; expect(vm.ready).toBe(false)
    vi.mocked(api.fetchManualMaterialOptions).mockResolvedValue({ categories: [], materials: [{ ...material, category_name: '面料', unit_name: '米' }] } as never)
    const normal = await render()
    Object.assign(normal.vm.selectionRow, { category: 'fabric', unitId: 'meter', unitLabel: '米', material_selection: { ...selection, unit_id: 'meter' } })
    normal.vm.form.quantity = '1.5'; normal.vm.form.rawLength = ''
    expect(normal.vm.ready).toBe(true); await normal.vm.submit()
    expect(api.createManualMaterialReceipt).toHaveBeenLastCalledWith(expect.objectContaining({ items: [{ material_catalog_id: 'catalog', material_selection: { ...selection, unit_id: 'meter' }, zone_id: 'zone', received_quantity: '1.5' }] }))
    permission.allowed = false
    const denied = await render()
    expect(denied.vm.ready).toBe(false)
  })
})
