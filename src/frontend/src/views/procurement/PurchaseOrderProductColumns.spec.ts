import { flushPromises, shallowMount, type VueWrapper } from '@vue/test-utils'
import ElementPlus, { ElSelect } from 'element-plus'
import { afterEach, assert, beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '@/api/purchaseOrders'
import type { PurchaseOrderOptions, PurchaseOrderProductSource, PurchaseOrderSource } from '@/types/purchaseOrder'
import PurchaseOrderFormView from './PurchaseOrderFormView.vue'

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
  useRoute: () => ({ name: 'purchase-order-create', params: {}, query: {} }),
}))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: () => true }) }))
vi.mock('@/api/purchaseOrders', () => ({
  fetchPurchaseOrderOptions: vi.fn(),
  fetchPurchaseOrderSource: vi.fn(),
  fetchSamplePurchaseOrderSource: vi.fn(),
  createPurchaseOrder: vi.fn(),
}))

const task = {
  id: 'task-1', task_number: 'HT26002', order_number: 'HT26002', customer_name: '测试客户',
  product_count: 1, delivery_date: '2026-10-31', status: 'BOM_VERIFIED', status_display: 'BOM已确认',
  can_create: true, blockers: [],
}
const options: PurchaseOrderOptions = {
  production_tasks: [task], suppliers: [], currencies: [], default_currency_id: null,
}

function sourceWithProduct(overrides: Partial<PurchaseOrderProductSource> = {}): PurchaseOrderSource {
  const product = {
    id: 'product-line-1', line_number: 1, product_number: 'INTERNAL-0099', product_code: 'HTB-007',
    item_number: 'XY-212', product_name: '三折床-不带棚',
    specification: '47*55*79；颜色：酒红色；材质：PE', specification_display: '47*55*79', material: 'PE',
    color_card: '潘通', color_name: '酒红色', color_code: '19-1629',
    order_quantity: '1000', unit_code: 'PIECE', unit_name: '张', ...overrides,
  }
  return {
    can_create: true, has_creatable_bom: true, requires_bom_selection: false, selected_bom_id: 'bom-1',
    source_revision: 'revision-1', blockers: [], production_task: { ...task, products: [product] },
    bom_options: [{
      product_line_id: product.id, product_line_number: 1, product_number: product.product_number,
      product_code: product.product_code, product_name: product.product_name, product_color: product.color_name,
      order_quantity: product.order_quantity, unit_name: product.unit_name,
      bom_id: 'bom-1', bom_number: 'BOM0000775', bom_status: 'VERIFIED', bom_status_display: '已确认',
      line_count: 1, can_create: true, blockers: [],
    }],
    lines: [], preview_lines: [], default_currency_id: null,
  }
}

let wrapper: VueWrapper | undefined

async function selectOrder(overrides: Partial<PurchaseOrderProductSource> = {}) {
  vi.mocked(api.fetchPurchaseOrderSource).mockResolvedValue(sourceWithProduct(overrides))
  wrapper = shallowMount(PurchaseOrderFormView, {
    global: { plugins: [ElementPlus], renderStubDefaultSlot: true },
  })
  await flushPromises()
  const select = wrapper.findAllComponents(ElSelect).find(component => component.attributes('data-testid') === 'production-task-select')
  assert(select, '找不到采购来源选择器')
  select.vm.$emit('update:modelValue', task.id)
  select.vm.$emit('change', task.id)
  await flushPromises()
  return wrapper
}

describe('采购来源产品列', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(api.fetchPurchaseOrderOptions).mockResolvedValue(options)
  })
  afterEach(() => {
    wrapper?.unmount()
    wrapper = undefined
  })

  it('保留产品编码，移除重复的产品编号，保持九列顺序', async () => {
    const page = await selectOrder()
    expect(page.get('.selected-product-row--heading').findAll('span').map(cell => cell.text())).toEqual([
      '选择', '产品编码', '货号', '产品名称', '规格', '颜色', '材质', '订单数量', 'BOM状态',
    ])
    const row = page.get('.selected-product-row--option')
    expect(row.text()).toContain('HTB-007')
    expect(row.text()).not.toContain('INTERNAL-0099')
  })

  it('规格、颜色、材质各自显示，悬停可查看完整颜色和产品信息', async () => {
    const page = await selectOrder()
    const cells = Array.from(page.get('.selected-product-row--option').element.children)
    expect(cells.map(cell => cell.textContent?.trim())).toEqual([
      '', 'HTB-007', 'XY-212', '三折床-不带棚', '47*55*79', '酒红色', 'PE', '1000 张', '已确认',
    ])
    expect(cells[1]?.getAttribute('title')).toBe('HTB-007')
    expect(cells[2]?.getAttribute('title')).toBe('XY-212')
    expect(cells[3]?.getAttribute('title')).toBe('三折床-不带棚')
    expect(cells[4]?.getAttribute('title')).toBe('47*55*79')
    expect(cells[5]?.getAttribute('title')).toBe('潘通 · 酒红色 · 19-1629')
    expect(cells[6]?.getAttribute('title')).toBe('PE')
    expect(api.fetchPurchaseOrderSource).toHaveBeenCalledWith(task.id)
    expect(api.createPurchaseOrder).not.toHaveBeenCalled()
  })

  it.each([undefined, ''])('材质缺失（%s）时显示占位符', async material => {
    const page = await selectOrder({ material })
    const cells = Array.from(page.get('.selected-product-row--option').element.children)
    expect(cells[6]?.textContent?.trim()).toBe('—')
  })

  it('旧接口没有规格展示字段时仍显示原规格', async () => {
    const page = await selectOrder({ specification_display: undefined, specification: '47*55*79' })
    const cells = Array.from(page.get('.selected-product-row--option').element.children)
    expect(cells[4]?.textContent?.trim()).toBe('47*55*79')
  })

  it('规格展示字段明确为空时不回退到混合了颜色和材质的旧规格', async () => {
    const page = await selectOrder({ specification_display: '' })
    const cells = Array.from(page.get('.selected-product-row--option').element.children)
    expect(cells[4]?.textContent?.trim()).toBe('—')
  })
})
