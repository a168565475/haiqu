import ElementPlus, { ElSelect } from 'element-plus'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterAll, afterEach, beforeAll, beforeEach, expect, it, vi } from 'vitest'
import { h } from 'vue'
import { createMemoryHistory, createRouter, RouterView } from 'vue-router'
import * as api from '@/api/purchaseGroups'
import type { PackagingPurchaseSource, PurchaseGroup, PurchaseGroupProgressLine } from '@/types/purchaseGroup'
import { pageInstanceKey } from '@/utils/pageInstanceKey'
import PackagingPurchaseFormView from './PackagingPurchaseFormView.vue'

vi.mock('@/api/purchaseGroups', () => ({
  fetchPackagingPurchaseOptions: vi.fn(), fetchPackagingPurchaseSources: vi.fn(),
  preparePackagingPurchase: vi.fn(), fetchPackagingPurchasePage: vi.fn(), writePackagingPurchasePage: vi.fn(),
}))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({
  user: { is_superuser: false },
  hasPermission: (code: string) => code === 'procurement.manage_packagingpurchase',
}) }))

const session = '7956a29d-8392-45d0-ab6d-d5742c5953df'
const sources: PackagingPurchaseSource[] = [
  ['one', 'a'], ['one', 'b'], ['two', 'c'],
].map(([task, bom]) => ({
  production_task_id: task!, task_number: 'HT-' + task, bom_id: 'bom-' + bom,
  bom_number: 'BOM-' + bom, product_name: '测试折叠椅', source_revision: 'revision-' + bom,
}))
const suppliers = [{ id: 'box-vendor', supplier_number: 'GYS00001', supplier_name: '纸箱供应商', supplier_categories: ['PACKAGING'] as const }]

function group(task: string, saved = false): PurchaseGroup {
  const groupSource = {
    product_line_id_snapshot: 'product-' + task, source_bom_id_snapshot: 'bom-' + task,
  }
  const quantitySource = { source_bom_line_id_snapshot: 'bom-line-' + task, required_quantity: '20', source_unit_text: '个' }
  const source: PurchaseGroupProgressLine = {
    ...quantitySource, id: 'line-' + task, line_number: 1, product_line_id_snapshot: groupSource.product_line_id_snapshot,
    remaining_purchase_quantity: saved ? '0' : '20',
    purchased_quantity: '0', accepted_quantity: '0', progress_percent: '0', is_satisfied: false,
    compatibility_issues: [],
    source_snapshot: {
      ...quantitySource, bom_id: groupSource.source_bom_id_snapshot, bom_line_id: quantitySource.source_bom_line_id_snapshot,
      product_line_id_snapshot: groupSource.product_line_id_snapshot,
      product_name_snapshot: '测试折叠椅', bom_number_snapshot: 'BOM-' + task,
      product_number_snapshot: '', product_code_snapshot: '', product_specification_snapshot: '',
      section_type_snapshot: 'PACKAGING', section_title_snapshot: '包材类', category_snapshot: '包材',
      source_quantity_field: '', source_quantity_text: '20', quantity_parse_status: 'READY', calculation_snapshot: {},
      part_name_snapshot: '纸箱-' + task, material_snapshot: '纸箱', raw_material_snapshot: '',
      specification_snapshot: '20×30', material_attributes_snapshot: {
        fields: [
          { key: 'material', label: '材质', value: '瓦楞纸' },
          { key: 'size', label: '尺寸', value: '20×30' },
          { key: 'color', label: '颜色', value: '白色' },
          { key: 'printing', label: '印刷版本', value: '客户版 A' },
        ],
      },
    },
  }
  return {
    ...groupSource, id: 'group-' + task, group_number: 'CGZD-' + task,
    production_task_id: task, production_task_number_snapshot: 'HT-' + task,
    sales_order_number_snapshot: '', customer_name_snapshot: '', source_revision: 'revision-' + task,
    compatibility_issues: [], created_at: '2026-11-24T01:00:00Z', updated_at: '2026-11-24T01:00:00Z',
    progress: { status: 'PENDING', lines: [source], external_supply_line_ids: [], line_count: 1, satisfied_line_count: 0 },
    batch_page: {
      current_batch_number: saved ? 1 : null, next_batch_number: 2, submitted_line_ids: saved ? [source.id] : [],
      draft_orders: saved ? [{ id: 'draft-1', order_number: 'CGDD-1', suppliers: ['纸箱供应商'], line_count: 1, total_amount: '40' }] : [],
    },
    batches: saved ? [{ id: 'draft-1', batch_session_id: session, batch_number: 1, batch_type: 'SUPPLEMENT', status: 'DRAFT',
      order_number: 'CGDD-1', currency_code_snapshot: 'CNY', total_amount: '40' }] : [],
  }
}

let wrapper: VueWrapper | undefined
beforeAll(() => vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} }))
afterAll(() => vi.unstubAllGlobals())
afterEach(() => { wrapper?.unmount(); wrapper = undefined })

beforeEach(() => {
  vi.resetAllMocks()
  vi.mocked(api.fetchPackagingPurchaseSources).mockResolvedValue(sources)
  vi.mocked(api.fetchPackagingPurchaseOptions).mockResolvedValue({
    suppliers: suppliers.map(supplier => ({ ...supplier, supplier_categories: [...supplier.supplier_categories] })),
    currencies: [{ id: 'cny', code: 'CNY', name: '人民币', symbol: '¥' }],
    default_currency_id: 'cny', production_tasks: [],
  })
  vi.mocked(api.preparePackagingPurchase).mockImplementation(async selected =>
    [...new Set(selected.map(source => source.production_task_id))].map(task => group(task)))
  vi.mocked(api.fetchPackagingPurchasePage).mockImplementation(async ids =>
    ({ groups: ids.map(id => group(id.slice('group-'.length))), etag: '"page-etag"' }))
})

async function open(path = '/packaging-purchases/new') {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { name: 'packaging-purchase-create', path: '/packaging-purchases/new', component: PackagingPurchaseFormView },
      { name: 'packaging-purchase-batch', path: '/packaging-purchases/batch', component: PackagingPurchaseFormView },
      { name: 'packaging-purchases', path: '/packaging-purchases', component: { template: '<div />' } },
    ],
  })
  await router.push(path)
  wrapper = mount({
    setup: () => () => h(RouterView, { key: pageInstanceKey(router.currentRoute.value, 'buyer') }),
  }, { global: { plugins: [router, ElementPlus] } })
  await flushPromises()
  return { router, page: wrapper }
}

async function choose(page: VueWrapper, tasks: string[]) {
  page.getComponent(ElSelect).vm.$emit('change', tasks)
  await flushPromises()
}

it('多选任务后仍然只有一张可填表，同任务两份 BOM 一起加载', async () => {
  const { page, router } = await open()
  expect(page.get('h1').text()).toBe('填写包材采购')
  expect(page.findAll('[data-testid="packaging-material-table"]')).toHaveLength(1)
  expect(page.text()).toContain('选择生产任务单后即可填写包材')
  expect(api.preparePackagingPurchase).not.toHaveBeenCalled()

  await choose(page, ['one'])
  expect(api.preparePackagingPurchase).toHaveBeenLastCalledWith(sources.slice(0, 2))
  expect(page.findAll('[data-testid="packaging-material-table"]')).toHaveLength(1)
  const firstSession = router.currentRoute.value.query.batch_session_id
  const taskRow = (task: string) => page.get('[data-testid="packaging-material-table"]').findAll('tbody tr')
    .find(row => row.text().includes('HT-' + task))!
  const firstQty = () => taskRow('one').get<HTMLInputElement>('input[aria-label="实际采购数量"]')
  expect(page.get('[data-testid="packaging-material-table"] thead th').text()).toBe('生产任务单号')
  expect(firstQty().element.disabled).toBe(false)
  await firstQty().setValue('12')

  await choose(page, ['one', 'two'])
  expect(api.preparePackagingPurchase).toHaveBeenLastCalledWith(sources.slice(2))
  expect(page.findAll('[data-testid="packaging-material-table"]')).toHaveLength(1)
  expect(taskRow('two').text()).toContain('纸箱-two')
  const headings = page.get('[data-testid="packaging-material-table"]').findAll('thead th').map(cell => cell.text())
  const cells = taskRow('two').findAll('td').map(cell => cell.text())
  for (const [field, value] of [['材质', '瓦楞纸'], ['尺寸', '20×30'], ['颜色', '白色'], ['印刷版本', '客户版 A'], ['单位', '个']] as const) {
    expect(cells[headings.indexOf(field)]).toBe(value)
  }
  expect(page.find('[aria-label="单价计价方式"]').exists()).toBe(false)
  expect(taskRow('two').get<HTMLInputElement>('input[aria-label="采购单价"]').element.disabled).toBe(false)
  expect(firstQty().element.value).toBe('12')
  expect(router.currentRoute.value.query.batch_session_id).toBe(firstSession)
  expect(router.currentRoute.value.query.group_ids).toEqual(['group-one', 'group-two'])
  expect(page.text()).not.toContain('分类')
})

it('续填时保留本批草稿和对应任务，满量行收起后仍可统一确认', async () => {
  vi.mocked(api.fetchPackagingPurchasePage).mockResolvedValue({ groups: [group('one', true)], etag: '"saved-etag"' })
  const { page } = await open('/packaging-purchases/batch?batch_session_id=' + session)
  expect(api.fetchPackagingPurchasePage).toHaveBeenCalledWith([], session)
  expect(page.get('[data-testid="packaging-material-table"]').text()).toContain('暂无待采购包材')
  expect(page.text()).toContain('已保存 1 张供应商草稿')
  const confirm = page.findAll('button').find(button => button.text() === '统一确认采购')!
  expect(confirm.element.disabled).toBe(false)
  await choose(page, [])
  expect(page.getComponent(ElSelect).props('modelValue')).toEqual(['one'])
  expect(api.preparePackagingPurchase).not.toHaveBeenCalled()
})
