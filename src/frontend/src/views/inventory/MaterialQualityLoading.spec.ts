import { flushPromises, shallowMount } from '@vue/test-utils'
import ElementPlus, { ElMessageBox } from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '@/api/inventory'
import MaterialQualityConfirmationView from './MaterialQualityConfirmationView.vue'

vi.mock('@/router', () => ({ router: { push: vi.fn() } }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: () => true }) }))
vi.mock('@/api/inventory', () => ({ fetchMaterialQualityBatches: vi.fn(), fetchMaterialQualityBatch: vi.fn(), confirmMaterialQuality: vi.fn() }))
const line = { id: 'line-1', received_quantity: '3.0000', return_quantity: '0.0000', quality_remark: '', supplier_name_snapshot: '供应商' }
const first = { id: 'batch-1', inbound_number: 'RK01', status: 'PENDING_QUALITY', lines: [line] }
const second = { ...first, id: 'batch-2', inbound_number: 'RK02', lines: [{ ...line, id: 'line-2' }] }
type View = { loading: boolean; loadError: string; canSubmit: boolean; selectedBatchId: string; batch: typeof first | null; rows: Array<{ included: boolean; line: typeof line; returnQuantity: string; qualityRemark: string }>; loadBatches: () => Promise<void>; selectBatch: (preserve?: boolean) => Promise<void>; confirmInbound: () => Promise<void> }
const mount = () => shallowMount(MaterialQualityConfirmationView, { global: { plugins: [ElementPlus] } })
describe('品质确认读取', () => {
  beforeEach(() => {
    vi.resetAllMocks(); localStorage.clear()
    vi.mocked(api.fetchMaterialQualityBatches).mockResolvedValue([first, second] as never)
    vi.mocked(api.fetchMaterialQualityBatch).mockImplementation(async id => (id === second.id ? second : first) as never)
  })
  it('首次和刷新复用刚读取的完整批次，保留输入且不重复读取详情', async () => {
    const wrapper = mount(); await flushPromises(); const vm = wrapper.vm as unknown as View
    expect(vm.rows).toHaveLength(1); expect(vm.canSubmit).toBe(true)
    expect(api.fetchMaterialQualityBatch).not.toHaveBeenCalled()
    vm.rows[0]!.returnQuantity = '0.1234'; vm.rows[0]!.qualityRemark = '保留内容'
    await vm.loadBatches()
    expect(vm.rows[0]).toMatchObject({ returnQuantity: '0.1234', qualityRemark: '保留内容' })
    expect(api.fetchMaterialQualityBatch).not.toHaveBeenCalled(); wrapper.unmount()
  })
  it('切换批次重新取详情，晚到响应不能覆盖新选择', async () => {
    const wrapper = mount(); await flushPromises(); const vm = wrapper.vm as unknown as View
    let finish!: (value: never) => void
    vi.mocked(api.fetchMaterialQualityBatch).mockReturnValueOnce(new Promise(resolve => { finish = resolve }))
    vm.selectedBatchId = second.id; const slow = vm.selectBatch()
    vm.selectedBatchId = first.id; await vm.selectBatch(); finish(second as never); await slow
    expect(vm.batch?.id).toBe(first.id); expect(vm.rows[0]?.line.id).toBe(line.id)
    expect(api.fetchMaterialQualityBatch).toHaveBeenCalledTimes(2); wrapper.unmount()
  })
  it('失败禁止提交，刷新可恢复，空列表清除旧批次和输入', async () => {
    const wrapper = mount(); await flushPromises(); const vm = wrapper.vm as unknown as View
    vi.mocked(api.fetchMaterialQualityBatches).mockRejectedValueOnce(new Error('失败'))
    await vm.loadBatches(); expect(vm.loadError).not.toBe(''); expect(vm.loading).toBe(false); expect(vm.canSubmit).toBe(false)
    await vm.loadBatches(); expect(vm.canSubmit).toBe(true)
    vi.mocked(api.fetchMaterialQualityBatches).mockResolvedValueOnce([])
    await vm.loadBatches(); expect(vm.batch).toBeNull(); expect(vm.rows).toEqual([]); expect(vm.loading).toBe(false); expect(vm.canSubmit).toBe(false)
    wrapper.unmount()
  })
  it('草稿与刷新后的数量精度校验、已确认状态门禁保留', async () => {
    localStorage.setItem('material-quality-draft:v2:batch-1', JSON.stringify({ 'line-1': { returnQuantity: '0.1234', qualityRemark: '草稿' } }))
    const wrapper = mount(); await flushPromises(); const vm = wrapper.vm as unknown as View
    expect(vm.rows[0]).toMatchObject({ returnQuantity: '0.1234', qualityRemark: '草稿' }); expect(vm.canSubmit).toBe(true)
    for (const value of ['-1', '3.0001', '0.12345', 'x']) { vm.rows[0]!.returnQuantity = value; expect(vm.canSubmit).toBe(false) }
    vm.rows[0]!.returnQuantity = '3.0000'; expect(vm.canSubmit).toBe(true)
    vi.mocked(api.fetchMaterialQualityBatch).mockResolvedValueOnce({ ...first, status: 'CONFIRMED' } as never)
    await vm.selectBatch(); expect(vm.canSubmit).toBe(false); expect(vm.loadError).not.toBe(''); wrapper.unmount()
  })
  it('卸载期间回包失效，取消确认不提交', async () => {
    const wrapper = mount(); await flushPromises(); const vm = wrapper.vm as unknown as View
    const confirm = vi.spyOn(ElMessageBox, 'confirm').mockRejectedValueOnce('cancel')
    await vm.confirmInbound(); expect(api.confirmMaterialQuality).not.toHaveBeenCalled(); confirm.mockRestore()
    let finish!: (value: never) => void
    vi.mocked(api.fetchMaterialQualityBatches).mockReturnValueOnce(new Promise(resolve => { finish = resolve }))
    const pending = vm.loadBatches(); wrapper.unmount(); finish([] as never); await pending
    expect(vm.batch?.id).toBe(first.id)
  })
})
