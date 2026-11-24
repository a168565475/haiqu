import { flushPromises, shallowMount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import Dialog from './ManualMaterialInboundDialog.vue'
import type { SampleMaterialLine } from '@/types/sampleMaterial'

const mocks = vi.hoisted(() => ({ create: vi.fn(), options: vi.fn() }))
vi.mock('@/api/inventory', () => ({ createManualMaterialReceipt: mocks.create, fetchMaterialReceivingOptions: mocks.options, fetchManualMaterialOptions: vi.fn() }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ user: { id: 19 }, initialized: true, identityReady: true,
  identityGeneration: 0, identityRequestGeneration: 0, hasPermission: () => true }) }))
beforeEach(() => { sessionStorage.clear(); mocks.options.mockResolvedValue({ warehouses: [{ id: 'warehouse' }], zones: [{ id: 'zone', warehouse: 'warehouse' }] }) })
afterEach(() => vi.clearAllMocks())

describe('R2 手工管材保留按根操作', () => {
  it('非根管材不能旁路成普通数量提交', async () => {
    const wrapper = shallowMount(Dialog, { global: { plugins: [ElementPlus] } }); await flushPromises()
    const vm = wrapper.vm as unknown as { form: Record<string, string>; rows: Array<{ categoryId: string; warehouseId: string; zoneId: string; quantity: string; rawLength: string; selection: SampleMaterialLine }>; ready: boolean }
    const row = vm.rows[0]!
    vm.form.remark = '管材恢复原入口'
    Object.assign(row, { categoryId: 'tube', warehouseId: 'warehouse', zoneId: 'zone' })
    Object.assign(row.selection, { category: 'tube', material_catalog_id: 'catalog', name: '原管', specification: '25', unitId: 'kg', unitLabel: '公斤',
      material_selection: { catalog_version: 'v1', scope: 'BASE', processing_state: 'RAW', attributes: { section_size: '25' }, unit_id: 'kg' } })
    await flushPromises()
    row.quantity = '2'; row.rawLength = '6'
    expect(vm.ready).toBe(false)
    expect(mocks.create).not.toHaveBeenCalled()
    wrapper.unmount()
  })
})
