import { flushPromises, shallowMount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '@/api/rawMaterials'
import HardwareRawMaterialCreateDialog from './HardwareRawMaterialCreateDialog.vue'

vi.mock('@/api/rawMaterials', () => ({ createRawMaterial: vi.fn(), fetchRawMaterialOptions: vi.fn() }))
beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(api.fetchRawMaterialOptions).mockResolvedValue({ item_types: [], categories: [{ id: 'c1', item_type: 'MATERIAL', category_name: '五金' }], units: [{ id: 'u1', unit_code: 'PCS', unit_name: '个' }], colors: [{ id: 'color1', color_card: 'A', color_code: '01', color_name: '黑色', label: 'A 黑色 01' }], warehouses: [{ warehouse_number: 'W1', warehouse_name: '原料仓' }], box_shapes: [] })
  vi.mocked(api.createRawMaterial).mockResolvedValue({ data: { id: 'saved-1' }, etag: 'raw-v1' } as never)
})
async function open(stageMaterial?: (payload: unknown, display: unknown) => void | Promise<void>) {
  const wrapper = shallowMount(HardwareRawMaterialCreateDialog, { props: { modelValue: true, categoryName: '五金', stageMaterial }, global: { plugins: [ElementPlus], renderStubDefaultSlot: true, stubs: { ElForm: false } } })
  await flushPromises()
  const vm = wrapper.vm as unknown as { form: Record<string, string>; submit: () => Promise<void>; submitError: string }
  Object.assign(vm.form, { material_number: 'TEST-1', material_name: '垫片', specification: 'M6', unit: 'u1', color: 'color1', material: '钢', warehouse_number: 'W1', notes: '测试' })
  return { wrapper, vm }
}
describe('原料新增窗暂存模式', () => {
  it('BOM 传入暂存回调时返回完整参数与展示名称，不创建正式原料', async () => {
    const stage = vi.fn()
    const { wrapper, vm } = await open(stage)
    try {
      expect(wrapper.findAllComponents({ name: 'ElAlert' }).some(alert => String(alert.props('title')).includes('暂存'))).toBe(true)
      await vm.submit()
      expect(stage).toHaveBeenCalledWith({ material_number: 'TEST-1', item_type: 'MATERIAL', category: 'c1', material_name: '垫片', specification: 'M6', unit: 'u1', color: 'color1', material: '钢', is_packaging_auxiliary: false, box_shape: '', notes: '测试', warehouse_number: 'W1', warehouse_name: '原料仓' }, { category_name: '五金', unit_code: 'PCS', unit_name: '个', color_name: '黑色' })
      expect(api.createRawMaterial).not.toHaveBeenCalled()
      expect(wrapper.emitted('created')).toBeUndefined()
      expect(wrapper.emitted('update:modelValue')).toEqual([[false]])
    } finally { wrapper.unmount() }
  })
  it('未传回调仍按原方式直接创建并返回真实记录', async () => {
    const { wrapper, vm } = await open()
    try {
      await vm.submit()
      expect(api.createRawMaterial).toHaveBeenCalledTimes(1)
      expect(wrapper.emitted('created')).toEqual([[{ id: 'saved-1' }]])
    } finally { wrapper.unmount() }
  })
  it('暂存回调失败保留输入且不关闭', async () => {
    const { wrapper, vm } = await open(vi.fn().mockRejectedValue(new Error('失败')))
    try {
      await vm.submit()
      expect(vm.form.material_name).toBe('垫片')
      expect(vm.submitError).not.toBe('')
      expect(wrapper.emitted('update:modelValue')).toBeUndefined()
      expect(api.createRawMaterial).not.toHaveBeenCalled()
    } finally { wrapper.unmount() }
  })
})
