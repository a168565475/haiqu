import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import SalesOrderDetailView from './SalesOrderDetailView.vue'
import type { SalesOrder } from '@/types/salesOrder'

const api = vi.hoisted(() => ({ fetchSalesOrder: vi.fn(), fetchAllProductionDataRecords: vi.fn(), push: vi.fn() }))
vi.mock('@/api/salesOrders', async (importOriginal) => ({
  ...await importOriginal<typeof import('@/api/salesOrders')>(), fetchSalesOrder: api.fetchSalesOrder,
}))
vi.mock('@/api/productionData', () => ({ fetchAllProductionDataRecords: api.fetchAllProductionDataRecords }))
vi.mock('vue-router', () => ({ useRoute: () => ({ params: { orderId: 'order-1' } }), useRouter: () => ({ push: api.push }) }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ user: { is_superuser: true }, hasPermission: () => true }) }))

function fixture() {
  return {
    id: 'order-1', order_number: 'SO-1', status: 'CONFIRMED', status_display: '已确认', source_type: 'QUOTATION',
    source_quotation_number: 'QUO-1', exchange_rate: '7', currency_code: 'USD', total_amount: '200', total_amount_cny: '1400.0000',
    salesperson: { id: 'person-1', display_name: '业务员' }, merchandiser: null,
    buyer_address_snapshot: {}, seller_snapshot: {}, evidence: [], versions: [], collaboration_events: [],
    lines: [{
      id: 'line-1', line_number: 1, product_id: 'product-1', product_category_id: 'category-1', product_unit_id: 'unit-1',
      product_image_id: 'image-1', customer_product_name_snapshot: '客户定制椅', customer_specification_snapshot: '客户规格 60×40',
      customer_color_snapshot: '宝蓝色', product_name_snapshot: '主档名称', specification_snapshot: '主档规格',
      product_number_snapshot: 'CP001', product_code_snapshot: 'PC001', item_number_snapshot: 'HH001',
      material_snapshot: '铝合金', unit_code_snapshot: 'PCS', quantity: '2', quoted_unit_price: '90', unit_price: '100',
      line_total: '200', unit_price_cny: '700.0000', line_total_cny: '1400.0000', price_difference: '10', quality_requirements: '品质保持', packaging_requirements: '独立包装',
      shipping_mark_requirements: '外箱唛头', lower_price_reason: '议定价格', price_exceptions: [],
    }],
    delivery_batches: [{
      id: 'batch-1', status: 'ACTIVE', batch_number: 'B1', planned_delivery_date: '2026-11-01',
      lines: [{ id: 'batch-line-1', sales_order_line_id: 'line-1', product_name: '客户定制椅', quantity: '2', remaining_quantity: '2' }],
      production_summary: { status_display: '尚未建立' },
    }],
  } as unknown as SalesOrder
}
const wrappers: ReturnType<typeof mount>[] = []
async function render(order = fixture()) {
  api.fetchSalesOrder.mockResolvedValue({ data: order, etag: '"v1"' })
  const wrapper = mount(SalesOrderDetailView, { global: { plugins: [ElementPlus], stubs: { AppWindowDialog: true } } })
  wrappers.push(wrapper)
  await flushPromises()
  return wrapper
}
async function openProducts(wrapper: ReturnType<typeof mount>) {
  await wrapper.findAll('.detail-tabs button').find(button => button.text() === '产品与价格')!.trigger('click')
  await flushPromises()
}

describe('销售订单详情产品信息', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.fetchAllProductionDataRecords.mockImplementation(async (resource: string) => resource === 'product-categories'
      ? [{ id: 'category-1', category_name: '休闲椅' }]
      : [{ id: 'unit-1', unit_code: 'PCS', unit_name: '把' }])
  })
  afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()) })

  it('建单入口进入生产侧表单并预选来源，不从销售跟单员填充生产人员', async () => {
    const order = fixture()
    order.merchandiser = { id: 'sales-follower', employee_code: 'SF', display_name: '销售跟单员' }
    const wrapper = await render(order)
    const create = wrapper.findAll('button').find(button => /建立并提交PMC|创建生产任务单/.test(button.text()))
    expect(create).toBeDefined()
    await create!.trigger('click')
    expect(api.push).toHaveBeenCalledWith({
      name: 'production-task-create', query: { sales_order_id: 'order-1', delivery_batch_id: 'batch-1' },
    })
  })

  it('订单信息和产品页签均显示创建时的客户产品详情及图片', async () => {
    const wrapper = await render()
    for (const tab of ['information', 'products']) {
      if (tab === 'products') await openProducts(wrapper)
      const content = wrapper.find('.detail-content')
      for (const text of ['休闲椅', '客户定制椅', '客户规格 60×40', '宝蓝色', '铝合金', '把', 'CP001', 'PC001', 'HH001', '议定价格', '1,400']) {
        expect(content.text()).toContain(text)
      }
      expect(content.find('img[alt="客户定制椅"]').attributes('src')).toContain('/sales-orders/order-1/lines/line-1/product-image/')
    }
    expect(wrapper.find('.products-panel').text()).toContain('品质保持')
  })

  it('详情人民币金额读取已保存字段，不重新乘头部汇率', async () => {
    const order = fixture()
    order.exchange_rate = '99'
    order.lines[0]!.specification_display = '纯规格'
    const wrapper = await render(order)
    await openProducts(wrapper)
    expect(wrapper.find('.products-panel').text()).toContain('1,400')
    expect(wrapper.find('.products-panel').text()).not.toContain('19,800')
    expect(wrapper.find('.products-panel').text()).toContain('纯规格')
  })

  it('期望日期只按有效且有分配数量的批次计算，多日期显示多批次', async () => {
    const order = fixture()
    order.delivery_batches.push({ ...order.delivery_batches[0]!, id: 'cancelled', status: 'CANCELLED', planned_delivery_date: '2026-12-01' })
    order.delivery_batches.push({ ...order.delivery_batches[0]!, id: 'unallocated', planned_delivery_date: '2026-12-02', lines: [{ ...order.delivery_batches[0]!.lines[0]!, quantity: '0' }] })
    const wrapper = await render(order)
    await openProducts(wrapper)
    expect(wrapper.find('.products-panel').text()).toContain('2026-11-01')
    expect(wrapper.find('.products-panel').text()).not.toContain('多批次')
    order.delivery_batches.push({ ...order.delivery_batches[0]!, id: 'batch-2', planned_delivery_date: '2026-11-02' })
    const multiple = await render(order)
    await openProducts(multiple)
    expect(multiple.find('.products-panel').text()).toContain('多批次')
  })

  it('字典读取失败仍显示订单快照，提示缺失字典且无图明确显示', async () => {
    api.fetchAllProductionDataRecords.mockRejectedValue(new Error('dictionary unavailable'))
    const order = fixture()
    order.lines[0]!.product_image_id = null
    const wrapper = await render(order)
    await openProducts(wrapper)
    expect(wrapper.find('.products-panel').text()).toContain('客户规格 60×40')
    expect(wrapper.find('.products-panel').text()).toContain('PCS')
    expect(wrapper.find('.products-panel').text()).toContain('无图')
    expect(wrapper.find('.products-panel').text()).toContain('类别或单位名称加载失败')
  })

  it('旧订单无客户快照时回退已保存产品名称和规格，未报价不显示虚假价差', async () => {
    const order = fixture()
    Object.assign(order.lines[0]!, { customer_product_name_snapshot: '', customer_specification_snapshot: '', quoted_unit_price: null, price_difference: '0' })
    const wrapper = await render(order)
    await openProducts(wrapper)
    const productTable = wrapper.find('.products-table')
    expect(productTable.text()).toContain('主档名称')
    expect(productTable.text()).toContain('主档规格')
    expect(productTable.findAll('.price-values')[0]!.findAll('dd').map(item => item.text())).toEqual(['—', '100', '—'])
  })

  it('产品为空时显示空状态，不生成空图片或残留产品行', async () => {
    const order = fixture()
    order.lines = []
    order.delivery_batches = []
    const wrapper = await render(order)
    await openProducts(wrapper)
    expect(wrapper.find('.products-table').text()).toContain('暂无产品')
    expect(wrapper.find('.products-table img').exists()).toBe(false)
  })
})
