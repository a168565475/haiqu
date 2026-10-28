import { flushPromises, shallowMount, type VueWrapper } from '@vue/test-utils'
import { AxiosError } from 'axios'
import ElementPlus, { ElMessage } from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '@/api/boms'
import * as colors from '@/api/productionData'
import type { ProductColor } from '@/types/productionData'
import BomEditorView from './BomEditorView.vue'

const applyCreatedColor = vi.fn()
vi.mock('vue-router', () => ({ useRoute: () => ({ params: { bomId: 'b1' } }), useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: () => true, moduleCan: () => true }) }))
vi.mock('@/api/boms', async original => ({ ...await original<typeof import('@/api/boms')>(), fetchBomForEdit: vi.fn() }))
vi.mock('@/api/productionData', async original => ({ ...await original<typeof import('@/api/productionData')>(), fetchAllProductionDataRecords: vi.fn(), createProductionDataRecord: vi.fn() }))

const saved: ProductColor = { id: 'saved-color', color_card: 'A', color_code: '001', color_name: '西瓜红',
  status: 'ACTIVE', archived_at: null, sort_order: 0, description: '', image_url: null, has_image: false, created_at: '', updated_at: '' }
interface Editor {
  productColorDraft: { color_card: string; color_code: string; color_name: string }
  productConfirmColors: ProductColor[]
  productConfirmColorCreateVisible: boolean
  productConfirmLoading: boolean
  createConfirmedColor: () => Promise<void>
}
let wrapper: VueWrapper
async function open() {
  wrapper = shallowMount(BomEditorView, { global: { plugins: [ElementPlus], stubs: {
    BomProductConfirmationDialogs: { template: '<div />', setup: () => ({ applyCreatedColor }) },
  } } })
  await flushPromises()
  const vm = wrapper.vm as unknown as Editor
  vm.productColorDraft = { color_card: ' A ', color_code: '001', color_name: '西瓜红' }
  vm.productConfirmColorCreateVisible = true
  return vm
}
beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(api.fetchBomForEdit).mockResolvedValue({ data: { id: 'b1', status: 'PENDING_CONFIRMATION', sections: [],
    product_information_confirmed: true, order_quantity: '10', current_order_quantity: '10', configured_field_labels: {} }, etag: 'v1' } as never)
  vi.mocked(colors.fetchAllProductionDataRecords).mockReset().mockResolvedValue([])
  vi.mocked(colors.createProductionDataRecord).mockReset().mockResolvedValue({ data: saved, etag: 'color-v1' })
  vi.spyOn(ElMessage, 'success').mockImplementation(() => ({ close: vi.fn() }))
  vi.spyOn(ElMessage, 'error').mockImplementation(() => ({ close: vi.fn() }))
})
afterEach(() => { wrapper?.unmount(); vi.restoreAllMocks() })

describe('BOM 颜色保存后刷新再选择', () => {
  it('已有同组颜色直接选用，不重复新增，并提醒继续确认产品', async () => {
    const vm = await open()
    vi.mocked(colors.fetchAllProductionDataRecords).mockResolvedValue([saved])
    await vm.createConfirmedColor()
    expect(colors.createProductionDataRecord).not.toHaveBeenCalled()
    expect(applyCreatedColor).toHaveBeenCalledWith(saved)
    expect(vm.productConfirmColorCreateVisible).toBe(false)
    expect(ElMessage.success).toHaveBeenCalledWith('已选用已有颜色，请继续确认产品信息。')
  })
  it('没有相同组合时正常新增，不把同名不同色卡合并', async () => {
    const vm = await open()
    vi.mocked(colors.fetchAllProductionDataRecords).mockResolvedValue([{ ...saved, id: 'other', color_card: 'B' }])
    await vm.createConfirmedColor()
    expect(colors.createProductionDataRecord).toHaveBeenCalledWith('product-colors', {
      color_card: 'A', color_code: '001', color_name: '西瓜红', status: 'ACTIVE', sort_order: 0, description: '',
    })
    expect(applyCreatedColor).toHaveBeenCalledWith(saved)
  })
  it('查询后被其他人新增的同组颜色可以重新读取并选用', async () => {
    const vm = await open()
    vi.mocked(colors.fetchAllProductionDataRecords).mockResolvedValueOnce([]).mockResolvedValueOnce([saved])
    vi.mocked(colors.createProductionDataRecord).mockRejectedValue(new AxiosError('重复', undefined, undefined, undefined, { status: 400, data: {} } as never))
    await vm.createConfirmedColor()
    expect(applyCreatedColor).toHaveBeenCalledWith(saved)
    expect(ElMessage.error).not.toHaveBeenCalled()
  })
  it('权限错误保留输入，不当作成功', async () => {
    const vm = await open()
    vi.mocked(colors.createProductionDataRecord).mockRejectedValue(new AxiosError('禁止', undefined, undefined, undefined, { status: 403 } as never))
    await vm.createConfirmedColor()
    expect(applyCreatedColor).not.toHaveBeenCalled()
    expect(vm.productConfirmColorCreateVisible).toBe(true)
    expect(vm.productColorDraft.color_name).toBe('西瓜红')
    expect(vm.productConfirmLoading).toBe(false)
    expect(ElMessage.error).toHaveBeenCalled()
  })
  it('已停用或归档的颜色不能自动选用，失败后仍保留输入', async () => {
    const vm = await open()
    vi.mocked(colors.fetchAllProductionDataRecords).mockResolvedValue([{ ...saved, status: 'INACTIVE', archived_at: '2026-10-28' }])
    vi.mocked(colors.createProductionDataRecord).mockRejectedValue(new AxiosError('重复', undefined, undefined, undefined, { status: 400, data: {} } as never))
    await vm.createConfirmedColor()
    expect(applyCreatedColor).not.toHaveBeenCalled()
    expect(vm.productConfirmColorCreateVisible).toBe(true)
    expect(ElMessage.error).toHaveBeenCalled()
  })
})
