import { flushPromises, shallowMount } from '@vue/test-utils'
import ElementPlus, { ElMessage } from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import Dialog from './ManualMaterialInboundDialog.vue'
import * as api from '@/api/inventory'

const permission = vi.hoisted(() => ({ allowed: true }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: () => permission.allowed }) }))
vi.mock('@/api/inventory', () => ({ createManualMaterialReceipt: vi.fn(), fetchManualMaterialOptions: vi.fn(), fetchMaterialReceivingOptions: vi.fn() }))
const material = { id: 'pipe', category_name: '管材', material_number: 'M01', material_name: '铁管', specification: '20*28*0.8*6140', unit_name: '根' }
type Form = { categoryId: string; rawMaterialId: string; warehouseId: string; zoneId: string; quantity: string; rawLength: string; inboundDate: string; remark: string }
type Vm = { form: Form; ready: boolean; submitting: boolean; submit: () => Promise<void> }
const wrappers: ReturnType<typeof shallowMount>[] = []
async function render() {
  const wrapper = shallowMount(Dialog, { global: { plugins: [ElementPlus] } })
  wrappers.push(wrapper)
  await flushPromises()
  const vm = wrapper.vm as unknown as Vm
  Object.assign(vm.form, { categoryId: 'tube', rawMaterialId: 'pipe', warehouseId: 'warehouse', zoneId: 'zone', quantity: '2', rawLength: '6', remark: '真实来源说明' })
  return { wrapper, vm }
}
beforeEach(() => {
  vi.resetAllMocks(); sessionStorage.clear(); permission.allowed = true
  vi.spyOn(ElMessage, 'error').mockImplementation(() => ({ close: vi.fn() }))
  vi.spyOn(ElMessage, 'success').mockImplementation(() => ({ close: vi.fn() }))
  vi.mocked(api.fetchManualMaterialOptions).mockResolvedValue({ categories: [{ id: 'tube', name: '管材' }], materials: [material] } as never)
  vi.mocked(api.fetchMaterialReceivingOptions).mockResolvedValue({ warehouses: [{ id: 'warehouse' }], zones: [{ id: 'zone', warehouse: 'warehouse' }] } as never)
  vi.mocked(api.createManualMaterialReceipt).mockResolvedValue({ inbound_number: 'RK001' } as never)
})
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()); vi.restoreAllMocks() })
describe('材料入库弹窗契约（模拟接口，不写真实库存）', () => {
  it('管材沿用根数和单根长度，成功后通知列表关闭刷新且防止重复提交', async () => {
    const { wrapper, vm } = await render()
    expect(vm.ready).toBe(true)
    await vm.submit()
    expect(api.createManualMaterialReceipt).toHaveBeenCalledWith(expect.objectContaining({ items: [{ raw_material_id: 'pipe', zone_id: 'zone', received_bar_count: '2', raw_bar_length_m: '6' }] }))
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
    normal.vm.form.quantity = '1.5'; normal.vm.form.rawLength = ''
    expect(normal.vm.ready).toBe(true); await normal.vm.submit()
    expect(api.createManualMaterialReceipt).toHaveBeenLastCalledWith(expect.objectContaining({ items: [{ raw_material_id: 'pipe', zone_id: 'zone', received_quantity: '1.5' }] }))
    permission.allowed = false
    const denied = await render()
    expect(denied.vm.ready).toBe(false)
  })
})
