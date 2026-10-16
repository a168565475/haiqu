import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import ElementPlus, { ElMessage } from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import SalesOrderEditorView from './SalesOrderEditorView.vue'
import type { InquiryItem } from '@/types/inquiry'

const api = vi.hoisted(() => ({
  rate: vi.fn(), options: vi.fn(), catalog: vi.fn(), context: vi.fn(), order: vi.fn(), update: vi.fn(), upload: vi.fn(),
  route: { params: {} as Record<string, string>, query: {} as Record<string, string> },
}))
vi.mock('vue-router', () => ({ useRoute: () => api.route, useRouter: () => ({ push: vi.fn(), replace: vi.fn() }), onBeforeRouteLeave: vi.fn() }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ user: { employee: { id: 'employee' } }, hasPermission: () => true }) }))
vi.mock('@/api/salesOrders', async (original) => ({
  ...await original<typeof import('@/api/salesOrders')>(), fetchSalesOrderOptions: api.options, fetchSalesOrderExchangeRate: api.rate,
  fetchQuotationOrderContext: api.context, fetchSalesOrder: api.order, updateSalesOrder: api.update,
  uploadSalesOrderLineProductImage: api.upload,
}))
vi.mock('@/api/productionData', () => ({ fetchAllProductionDataRecords: api.catalog }))

const wrappers: VueWrapper[] = []
const item: InquiryItem = {
  product_id: 'product', product_category_id: 'category', product_unit_id: 'unit', product_image_id: null,
  product_description: '折叠椅', specification: '50×50', color: '蓝色', material: '铝合金', quantity: '5',
  unit_code: 'PCS', target_unit_price: '12', target_currency_code: 'USD', expected_date: null,
  product_match_status: 'MATCHED', notes: '',
}
const productDialog = {
  name: 'InquiryProductDialog', props: ['item', 'imageUrl', 'pendingImage', 'pendingRemoval'],
  emits: ['confirm', 'update:modelValue'], template: '<div />',
}
const png = (name: string) => new File(['png'], name, { type: 'image/png' })
async function render() {
  const wrapper = mount(SalesOrderEditorView, { global: {
    plugins: [ElementPlus], stubs: { InquiryProductDialog: productDialog, BuyerMasterDataDialog: true, SellerProfileDialog: true, SellerSubjectCard: true, AppWindowDialog: true, ElInputNumber: { props: ['modelValue'], template: '<input :value="modelValue" />' } },
  } })
  wrappers.push(wrapper)
  await flushPromises()
  await click(wrapper, '订单产品')
  return wrapper
}
async function click(wrapper: VueWrapper, label: string) {
  await wrapper.findAll('button').find(button => button.text() === label)!.trigger('click')
  await flushPromises()
}
async function confirmImage(wrapper: VueWrapper, file: File | null, removeImage = false) {
  const dialog = wrapper.findComponent({ name: 'InquiryProductDialog' })
  dialog.vm.$emit('confirm', { item: dialog.props('item').product_description ? dialog.props('item') : item, imageChanged: true, imageFile: file, removeImage })
  await flushPromises()
}
function tableImage(wrapper: VueWrapper) { return wrapper.find('.product-table .product-image img') }

beforeEach(() => {
  vi.clearAllMocks()
  api.route.params = {}; api.route.query = {}
  api.options.mockResolvedValue({ customers: [], transaction_entities: [], buyer_addresses: [], products: [], employees: [], currencies: [], accepted_quotation_versions: [] })
  api.catalog.mockResolvedValue([])
  api.rate.mockResolvedValue({ exchange_rate_record_id: 'rate', exchange_rate: '7.00000000', exchange_rate_snapshot: { record_id: 'rate', rate: '7.00000000', source_name: '测试系统汇率', effective_date: '2026-10-15' } })
  Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn((file: File) => `blob:${file.name}`) })
  Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() })
  vi.spyOn(ElMessage, 'warning').mockImplementation(() => ({ close: vi.fn() }))
})
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()); vi.restoreAllMocks() })

describe('销售订单产品图片显示', () => {
  it('新建订单选择图片后立即显示，重新打开仍保留待上传文件', async () => {
    const wrapper = await render(), file = png('first.png')
    await click(wrapper, '添加产品')
    await confirmImage(wrapper, file)
    expect(tableImage(wrapper).exists()).toBe(true)
    expect(tableImage(wrapper).attributes('src')).toBe('blob:first.png')
    await click(wrapper, '编辑产品')
    expect(wrapper.findComponent({ name: 'InquiryProductDialog' }).props('pendingImage')).toBe(file)
  })

  it('替换后显示新图并释放旧预览，移除后不再显示旧图', async () => {
    const wrapper = await render()
    await click(wrapper, '添加产品'); await confirmImage(wrapper, png('first.png'))
    await click(wrapper, '编辑产品'); await confirmImage(wrapper, png('second.png'))
    expect(tableImage(wrapper).exists()).toBe(true)
    expect(tableImage(wrapper).attributes('src')).toBe('blob:second.png')
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:first.png')
    await click(wrapper, '编辑产品'); await confirmImage(wrapper, null, true)
    expect(tableImage(wrapper).exists()).toBe(false)
    expect(wrapper.find('.product-table').text()).toContain('无图')
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:second.png')
  })

  it('删除产品和离开页面均释放本地预览', async () => {
    const wrapper = await render()
    await click(wrapper, '添加产品'); await confirmImage(wrapper, png('deleted.png'))
    await click(wrapper, '删除')
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:deleted.png')
    await click(wrapper, '添加产品'); await confirmImage(wrapper, png('unmounted.png'))
    wrapper.unmount()
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:unmounted.png')
  })

  it('报价转订单在保存前使用报价行图片，编辑弹窗使用同一来源', async () => {
    api.route.query = { source: 'QUOTATION', quotationVersionId: 'quote-version' }
    api.options.mockResolvedValue({ customers: [], transaction_entities: [], buyer_addresses: [], products: [], employees: [], currencies: [], accepted_quotation_versions: [{ id: 'quote-version' }] })
    api.context.mockResolvedValue({
      customer_account_id: 'customer', salesperson_id: 'employee', currency_code: 'USD', buyer_snapshot: {}, buyer_address_snapshot: {}, seller_snapshot: {}, terms_snapshot: {}, customer_requirement_snapshot: {},
      lines: [{ id: 'quote-line', product_id: 'product', product_description: '折叠椅', specification: '50×50', product_image_id: 'quote-image', remaining_quantity: '5', quoted_unit_price: '12', unit_code: 'PCS' }],
    })
    const wrapper = await render()
    expect(tableImage(wrapper).exists()).toBe(true)
    expect(tableImage(wrapper).attributes('src')).toMatch(/\/api\/v1\/quotation-lines\/quote-line\/product-image\/\?v=quote-image$/)
    await click(wrapper, '编辑产品')
    expect(wrapper.findComponent({ name: 'InquiryProductDialog' }).props('imageUrl')).toMatch(/\/api\/v1\/quotation-lines\/quote-line\/product-image\/$/)
  })

  it('已保存草稿替换图片上传失败时保留新图和待上传文件', async () => {
    api.route.params = { orderId: 'order' }
    api.options.mockResolvedValue({ customers: [{ id: 'customer', account_code: 'C1' }], transaction_entities: [{ id: 'entity', customer_account_id: 'customer' }], buyer_addresses: [], products: [], employees: [], currencies: [], accepted_quotation_versions: [] })
    const order = {
      id: 'order', status: 'DRAFT', source_type: 'DIRECT', source_quotation_version_id: null, customer_code: 'C1', transaction_entity_id: 'entity', salesperson: { id: 'employee' },
      order_date: '2026-10-15', direct_order_reason: '客户直接下单', currency_code: 'USD', total_amount_cny: '60.0000', exchange_rate: '1', exchange_rate_record_id: 'old-rate', exchange_rate_snapshot: { record_id: 'old-rate', rate: '1', source_name: '旧系统记录', effective_date: '2026-10-01' },
      seller_snapshot: { legal_name: '工厂' }, buyer_snapshot: {}, buyer_address_snapshot: {}, terms_snapshot: {}, customer_requirement_snapshot: {},
      confirmation_method: 'CUSTOMER_PO', customer_confirmer: '客户', customer_confirmed_at: '2026-10-15T00:00:00Z', confirmation_summary: '已确认', evidence: [],
      lines: [{ id: 'line', line_number: 1, product_id: 'product', product_image_id: 'old-image', product_name_snapshot: '折叠椅', specification_snapshot: '50×50', unit_code_snapshot: 'PCS', quantity: '5', unit_price: '12' }],
      delivery_batches: [{ id: 'batch', planned_delivery_date: '2026-10-20', notes: '', lines: [{ sales_order_line_id: 'line', quantity: '5' }] }],
    }
    api.order.mockResolvedValue({ data: order, etag: 'before' })
    api.update.mockResolvedValue({ data: order, etag: 'saved' })
    api.upload.mockRejectedValue(new Error('图片上传失败'))
    const wrapper = await render(), file = png('retry.png')
    expect(tableImage(wrapper).attributes('src')).toMatch(/\/sales-orders\/order\/lines\/line\/product-image\/\?v=old-image$/)
    await click(wrapper, '编辑产品'); await confirmImage(wrapper, file)
    await click(wrapper, '保存草稿')
    expect(ElMessage.warning).toHaveBeenCalledWith(expect.stringContaining('图片上传失败'))
    expect(tableImage(wrapper).attributes('src')).toBe('blob:retry.png')
    expect(URL.revokeObjectURL).not.toHaveBeenCalledWith('blob:retry.png')
    await click(wrapper, '编辑产品')
    expect(wrapper.findComponent({ name: 'InquiryProductDialog' }).props('pendingImage')).toBe(file)
  })
})
