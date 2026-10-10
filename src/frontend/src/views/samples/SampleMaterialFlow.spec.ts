import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElMessageBox } from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import MaterialPage from './SampleMaterialRequestView.vue'
import WarehousePage from './SampleWarehouseReviewView.vue'

const api = vi.hoisted(() => ({ sample: vi.fn(), material: vi.fn(), units: vi.fn(), noMaterials: vi.fn(), saveMaterial: vi.fn(), warehouse: vi.fn(), saveWarehouse: vi.fn(), push: vi.fn() }))
vi.mock('@/api/samples', () => ({ fetchSample: api.sample }))
vi.mock('@/api/sampleMaterials', () => ({ fetchSampleMaterials: api.material, fetchSampleMaterialUnits: api.units, saveSampleMaterials: api.saveMaterial, confirmSampleNoMaterials: api.noMaterials, fetchSampleMaterialReferences: vi.fn(async () => ({ tube: {}, fabric: {}, accessory: {}, accessories: [] })), fetchSampleMaterialCandidates: vi.fn() }))
vi.mock('@/api/sampleWarehouse', () => ({ fetchSampleWarehouseReview: api.warehouse, saveSampleWarehouseReview: api.saveWarehouse }))
vi.mock('vue-router', () => ({ useRoute: () => ({ params: { sampleId: 'sample' } }), useRouter: () => ({ push: api.push }) }))
vi.mock('@/composables/useSampleUnsavedChanges', () => ({ useSampleUnsavedChanges: vi.fn() }))
vi.mock('@/composables/useSampleFullscreen', () => ({ useSampleFullscreen: () => ({ fullscreen: false, toggleFullscreen: vi.fn() }) }))
const wrappers: ReturnType<typeof mount>[] = []
const line = { key: 'k', category: 'tube', rawMaterialId: 'raw', cuttingLengthMm: '500', piecesPerBar: '6', name: '圆管', specification: '25mm', material: '铝', color: '黑', quantity: '12', unitId: 'u', unitLabel: '米', notes: '', supplyQuantity: '2' }
const state = () => ({ available: true, canEdit: true, etag: 'v1', status: 'WAREHOUSE_PENDING', statusLabel: '待仓库核对', draft: { lines: [{ ...line }], notes: '' }, submittedAt: '2026-09-10T01:00:00Z', inventoryUpdatedAt: null, reviewedAt: null })
async function render(component: typeof MaterialPage | typeof WarehousePage) {
  const wrapper = mount(component, { global: { plugins: [ElementPlus], stubs: { SampleMaterialApplicationInfo: true, SampleInventoryLookup: true } } })
  wrappers.push(wrapper)
  await flushPromises()
  return wrapper
}
beforeEach(() => {
  vi.clearAllMocks()
  api.sample.mockResolvedValue({ data: { id: 'sample', request_number: 'SRQ-1', status: 'MATERIALS_PENDING', status_display: '待打样部填写', customer_name: '客户', products: [], item_summary: { text: '椅子', count: 1 } }, etag: 'v1' })
  api.material.mockResolvedValue({ ...state(), status: 'MATERIALS_PENDING', statusLabel: '待打样部填写' })
  api.warehouse.mockResolvedValue(state())
  api.units.mockResolvedValue([{ id: 'u', label: '米', decimalPlaces: 4 }])
})
afterEach(() => { wrappers.splice(0).forEach(w => w.unmount()) })

describe('材料交接页面的真实保存与并发边界', () => {
  it('材料提交失败保留内容，提交期间禁用操作防止重复发送', async () => {
    let reject!: (error: Error) => void
    api.saveMaterial.mockImplementationOnce(() => new Promise((_resolve, fail) => { reject = fail }))
    const w = await render(MaterialPage)
    await w.find('#material-notes').setValue('需要保留')
    await w.find('.submit-action').trigger('click')
    await w.find('.submit-action').trigger('click')
    expect(api.saveMaterial).toHaveBeenCalledTimes(1)
    expect(w.find('.submit-action').attributes('disabled')).toBeDefined()
    reject(new Error('网络失败'))
    await flushPromises()
    expect((w.find('#material-notes').element as HTMLInputElement).value).toBe('需要保留')
    expect(w.text()).toContain('网络失败')
  })
  it('材料提交应用服务端冻结状态并进入仓库页', async () => {
    api.saveMaterial.mockResolvedValue({ ...state(), canEdit: false })
    const w = await render(MaterialPage)
    await w.find('.submit-action').trigger('click')
    await flushPromises()
    expect(api.push).toHaveBeenCalledWith({ name: 'sample-warehouse-review', params: { sampleId: 'sample' } })
    expect(w.find('.save-action').exists()).toBe(false)
  })
  it('仓库只提交人工可供数量，不展示系统库存参考', async () => {
    const w = await render(WarehousePage)
    await w.find('input[aria-label="圆管本次可供数量"]').setValue('5')
    expect(w.text()).not.toContain('系统库存')
    expect(w.text()).toContain('刷新库存')
    api.saveWarehouse.mockResolvedValue({ ...state(), draft: { ...state().draft, lines: [{ ...line, supplyQuantity: '5' }] } })
    await w.find('.submit-action').trigger('click')
    await flushPromises()
    expect(api.saveWarehouse).toHaveBeenCalledWith(expect.objectContaining({ etag: 'v1', draft: expect.objectContaining({ lines: [expect.objectContaining({ supplyQuantity: '5' })] }) }))
  })
  it('仓库加载失败时保持不可操作，已提交记录只读', async () => {
    api.warehouse.mockRejectedValueOnce(new Error('failure'))
    const failed = await render(WarehousePage)
    expect(failed.find('.submit-action').attributes('disabled')).toBeDefined()
    api.warehouse.mockResolvedValue({ ...state(), canEdit: false, status: 'PROCUREMENT_PENDING', statusLabel: '待采购处理' })
    const readonly = await render(WarehousePage)
    expect(readonly.find('.submit-action').attributes('disabled')).toBeDefined()
    expect(readonly.find('input[aria-label="圆管本次可供数量"]').exists()).toBe(false)
    expect(readonly.find('.sample-material-progress').exists()).toBe(true)
  })
})

it('无需用料为明确操作，携带版本并跳转生产详情', async () => {
  const confirm = vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue('confirm' as never)
  api.noMaterials.mockResolvedValue({ ...state(), status: 'METALWORK_PENDING', statusLabel: '待上传金工参数', canEdit: false, noMaterials: true })
  const w = await render(MaterialPage)
  await w.findAll('button').find(b => b.text() === '无需用料')!.trigger('click')
  await flushPromises()
  expect(confirm).toHaveBeenCalled()
  expect(api.noMaterials).toHaveBeenCalledWith('sample', 'v1')
  expect(api.push).toHaveBeenCalledWith({ name: 'sample-detail', params: { sampleId: 'sample' } })
  confirm.mockRestore()
})
