import { flushPromises, shallowMount, type VueWrapper } from '@vue/test-utils'
import ElementPlus, { ElMessage } from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '@/api/boms'
import * as colors from '@/api/productionData'
import type { InquiryItem } from '@/types/inquiry'
import { emptyProductEntry } from '@/utils/productEntryDraft'
import BomEditorView from './BomEditorView.vue'
vi.mock('vue-router', () => ({ useRoute: () => ({ params: { bomId: 'b1' } }), useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: () => true, moduleCan: () => true }) }))
vi.mock('@/api/boms', async original => ({ ...await original<typeof import('@/api/boms')>(), fetchBomForEdit: vi.fn(), confirmBomProduct: vi.fn() }))
vi.mock('@/api/productionData', async original => ({ ...await original<typeof import('@/api/productionData')>(), fetchAllProductionDataRecords: vi.fn(), createProductionDataRecord: vi.fn() }))
const savedBom = { id: 'b1', status: 'PENDING_CONFIRMATION', sections: [], product_information_confirmed: true, order_quantity: '10', current_order_quantity: '10', configured_field_labels: {} }
const item: InquiryItem = { product_id: null, product_catalog_id: null, product_description: '定制椅', specification: '50*60', unit_code: '', color: '酒红', material: '铝', quantity: '10', target_unit_price: null, target_currency_code: '', expected_date: null, product_match_status: 'PENDING', notes: '', product_selection: { draft: { ...emptyProductEntry(), category_name: '椅类', name: '定制椅', item_number: 'I1', product_code: 'C1', specification: '50*60', color_name: '酒红', material: '铝', unit_name: '新单位' } } }
interface Editor { productConfirmVisible: boolean; productConfirmError: string; productConfirmLoading: boolean; sections: unknown[]; confirmProductInformation: (payload: { item: InquiryItem }) => Promise<void> }
let wrapper: VueWrapper
async function open() { wrapper = shallowMount(BomEditorView, { global: { plugins: [ElementPlus], stubs: { BomProductConfirmationDialogs: true } } }); await flushPromises(); return wrapper.vm as unknown as Editor }
beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(api.fetchBomForEdit).mockResolvedValue({ data: savedBom, etag: 'v1' } as never)
  vi.mocked(api.confirmBomProduct).mockResolvedValue({ data: savedBom, etag: 'v2' } as never)
  vi.mocked(colors.fetchAllProductionDataRecords).mockResolvedValue([])
  vi.spyOn(ElMessage, 'success').mockImplementation(() => ({ close: vi.fn() }))
})
afterEach(() => { wrapper?.unmount(); vi.restoreAllMocks() })
describe('BOM 产品核对只保存草稿', () => {
  it('新产品与新颜色仅发送草稿，不提前创建公共颜色，未保存的物料保持', async () => {
    const vm = await open(); const sections = vm.sections
    await vm.confirmProductInformation({ item })
    expect(api.confirmBomProduct).toHaveBeenCalledWith('b1', { product_catalog_id: null, product_selection: item.product_selection, color_code: '', material: '铝' }, 'v1')
    expect(colors.createProductionDataRecord).not.toHaveBeenCalled(); expect(vm.sections).toBe(sections)
    expect(vm.productConfirmVisible).toBe(false)
  })
  it('已有产品补新属性仍发送原关联及草稿，旧主库创建入口不存在', async () => {
    const vm = await open()
    await vm.confirmProductInformation({ item: { ...item, product_catalog_id: 'catalog1', product_selection: { ...item.product_selection, catalog_version: 'v3' } } })
    expect(api.confirmBomProduct).toHaveBeenCalledWith('b1', expect.objectContaining({ product_catalog_id: 'catalog1', product_selection: expect.objectContaining({ draft: expect.objectContaining({ color_name: '酒红' }) }) }), 'v1')
    expect(wrapper.find('product-create-dialog-stub').exists()).toBe(false); expect(colors.createProductionDataRecord).not.toHaveBeenCalled()
  })
  it('请求失败保留核对窗口和输入，允许重试', async () => {
    const vm = await open(); vm.productConfirmVisible = true
    vi.mocked(api.confirmBomProduct).mockRejectedValueOnce(new Error('网络错误'))
    await vm.confirmProductInformation({ item })
    expect(vm.productConfirmVisible).toBe(true); expect(vm.productConfirmLoading).toBe(false); expect(vm.productConfirmError).toBeTruthy()
    expect(item.product_selection?.draft?.color_name).toBe('酒红')
    await vm.confirmProductInformation({ item }); expect(api.confirmBomProduct).toHaveBeenCalledTimes(2); expect(vm.productConfirmVisible).toBe(false)
  })
})
