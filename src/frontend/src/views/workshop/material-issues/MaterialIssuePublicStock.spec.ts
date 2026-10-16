import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import MaterialIssueFormView from './MaterialIssueFormView.vue'
import MaterialIssueDetailView from './MaterialIssueDetailView.vue'
import MaterialIssueListView from './MaterialIssueListView.vue'
import MaterialIssuePartitions from '@/components/workshop/MaterialIssuePartitions.vue'
import type { MaterialIssueProduct, MaterialRequirement } from '@/types/materialIssue'

const route = vi.hoisted(() => ({ params: {} as Record<string, string>, query: {} as Record<string, string> }))
const api = vi.hoisted(() => ({ list: vi.fn(), options: vi.fn(), products: vi.fn(), requirements: vi.fn(), detail: vi.fn(),
  create: vi.fn(), update: vi.fn(), submit: vi.fn(), preview: vi.fn(), confirm: vi.fn(), returned: vi.fn() }))
vi.mock('vue-router', () => ({ useRoute: () => route }))
vi.mock('@/router', () => ({ router: { push: vi.fn(), replace: vi.fn(), back: vi.fn() } }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ user: { is_superuser: true }, hasPermission: () => true }) }))
vi.mock('@/api/materialIssues', async importOriginal => ({
  ...await importOriginal<typeof import('@/api/materialIssues')>(),
  fetchMaterialIssues: api.list,
  fetchMaterialIssueOptions: api.options, fetchEligibleMaterialIssueProducts: api.products,
  fetchMaterialRequirements: api.requirements, fetchMaterialIssue: api.detail,
  createMaterialIssue: api.create, updateMaterialIssue: api.update, submitMaterialIssue: api.submit,
  previewMaterialIssue: api.preview, confirmMaterialIssue: api.confirm, returnMaterialIssue: api.returned,
}))

const semi: MaterialRequirement = {
  stock_mode: 'PUBLIC_V2', requirement_id: 'receiving-bom-line', stock_item_id: 'pool-1', line_type: 'SEMI',
  section_code: 'SEMI', material_number: 'SEMI-1', material_name: '前脚管', material: '铁', specification: '20mm', color: '黑色', unit: '支',
  required_quantity: '100', internal_issued_quantity: '20', outsourcing_issued_quantity: '0', pending_issue_quantity: '10',
  order_remaining: '70', available_stock: '200', max_issue_quantity: '70', bom_version: 1, validation_errors: [],
  completed_craft: '喷塑', warehouse_zone: '半成品仓 / 一楼',
}
const product: MaterialIssueProduct = { id: 'product-1', product_number: 'P001', product_name: '折叠椅', specification: '', color: '黑色', quantity: '100', unit: '套', image_file_id: null }
function detail(stockMode: 'PUBLIC_V2' | null = 'PUBLIC_V2') {
  return { id: 'issue-1', stock_mode: stockMode || undefined, issue_number: '领料-001', status: 'DRAFT', status_display: '草稿',
    production_task: { id: 'task-1', task_number: '生产001', customer_name: '客户' }, product,
    workshop: { id: 'workshop-1', name: '装配车间' }, recipient: { id: 'recipient-1', name: '领料人' },
    issue_at: '2026-09-28T09:00:00+08:00', remark: '', line_count: 1,
    created_by: { id: 'employee-1', name: '制单人' }, audit_events: [],
    lines: [{ ...semi, stock_mode: stockMode || undefined, id: 'line-1', requested_quantity: '5', issued_quantity: null }],
  }
}
const wrappers: ReturnType<typeof mount>[] = []
const dialogStub = { template: '<section><slot/><slot name="footer"/></section>' }
async function formView() {
  const wrapper = mount(MaterialIssueFormView, { global: { plugins: [ElementPlus], stubs: { MaterialIssuePartitions: true } } })
  wrappers.push(wrapper); await flushPromises(); return wrapper
}
async function detailView(value = detail()) {
  route.params = { issueId: 'issue-1' }
  api.detail.mockResolvedValue({ data: value, etag: '"issue-1"' })
  const wrapper = mount(MaterialIssueDetailView, { global: { plugins: [ElementPlus], stubs: { AppWindowDialog: dialogStub } } })
  wrappers.push(wrapper); await flushPromises(); return wrapper
}
function tableValue(wrapper: ReturnType<typeof mount>, label: string): string {
  const table = wrapper.findAll('section.detail-table')[1]!
  const index = table.findAll('thead th').findIndex(cell => cell.text() === label)
  expect(index).toBeGreaterThanOrEqual(0)
  return table.findAll('tbody tr')[0]!.findAll('td')[index]!.text()
}
beforeEach(() => {
  vi.resetAllMocks()
  route.params = {}
  route.query = { production_task_id: 'task-1', product_line_id: 'product-1', schedule_product_id: 'schedule-product-1', plan_category: 'ASSEMBLY' }
  api.options.mockResolvedValue({ production_tasks: [{ id: 'task-1', task_number: '生产001', customer_name: '客户' }],
    workshops: [{ id: 'workshop-1', name: '装配车间' }], recipients: [{ id: 'recipient-1', name: '领料人', workshop_id: 'workshop-1' }] })
  api.products.mockResolvedValue([product])
  api.requirements.mockResolvedValue({ items: [structuredClone(semi)], blockers: [] })
})
afterEach(() => wrappers.splice(0).forEach(wrapper => wrapper.unmount()))

describe('领料产品展示', () => {
  it.each([
    { specification_display: '47*55*79', color: '酒红色', material: 'PE', expected: ['47*55*79', '酒红色', 'PE'] },
    { specification_display: '', color: '', material: '', expected: ['—', '—', '—'] },
  ])('列表规格颜色材质分别显示，空值不回退拼接属性', async ({ expected, ...fields }) => {
    route.query = {}
    api.list.mockResolvedValue({ data: [{ ...detail(), product: { ...product, specification: '47*55*79；颜色：酒红色；材质：PE', ...fields } }], meta: { total: 1 } })
    const wrapper = mount(MaterialIssueListView, { global: { plugins: [ElementPlus] } })
    wrappers.push(wrapper)
    await flushPromises()
    const headers = wrapper.findAll('thead th').map(cell => cell.text())
    const cells = wrapper.findAll('tbody tr')[0]!.findAll('td')
    expect(headers.slice(headers.indexOf('产品'), headers.indexOf('车间') + 1)).toEqual(['产品', '规格', '颜色', '材质', '车间'])
    expect(['规格', '颜色', '材质'].map(label => cells[headers.indexOf(label)]!.text())).toEqual(expected)
  })

  it('新增和详情使用领料图片接口，不依赖排产查看权限', async () => {
    const imageProduct = { ...product, image_file_id: 'image-1' }
    api.products.mockResolvedValue([imageProduct])
    const form = await formView()
    const detailPage = await detailView({ ...detail(), product: imageProduct })
    for (const wrapper of [form, detailPage]) {
      const image = wrapper.find('.product-preview img')
      expect(image.attributes('src')).toContain('/api/v1/material-issues/product-images/task-1/image-1/')
      expect(image.classes()).not.toContain('is-placeholder')
    }
  })
})

describe('公共库存领料按接收订单提交', () => {
  it.each([
    { section: 'SEMI', allowed: true, title: '仅半成品属性缺漏仍允许合格原材料提交' },
    { section: 'ACCESSORY', allowed: false, title: '原材料未解析继续阻止原材料提交' },
  ])('$title', async ({ section, allowed }) => {
    api.requirements.mockResolvedValue({
      items: [{ ...semi, requirement_id: 'raw-accessory', line_type: 'RAW', section_code: 'ACCESSORY', unit: '件' }],
      blockers: [{ code: 'INVALID_BOM', section_code: section, detail: 'BOM 属性缺漏' }],
    })
    const wrapper = await formView()
    const vm = wrapper.vm as any
    vm.form.recipient_workshop_employee_id = 'recipient-1'
    vm.selected['raw-accessory'] = '5'
    if (allowed) expect(vm.validate()).toBe('')
    else expect(vm.validate()).toContain('未解析原材料')
  })

  it('PUBLIC_V2半成品只提交接收BOM需求行，不拆来源余额', async () => {
    api.requirements.mockResolvedValue({ items: [{ ...semi, semi_balance_allocations: [
      { balance_id: 'other-order-source-a', max_issue_quantity: '2' },
      { balance_id: 'other-order-source-b', max_issue_quantity: '3' },
    ] }], blockers: [] })
    const wrapper = await formView()
    const vm = wrapper.vm as any
    vm.selected['receiving-bom-line'] = '5'
    expect(vm.payload().lines).toEqual([{ requirement_id: 'receiving-bom-line', requested_quantity: '5' }])
    expect(api.requirements).toHaveBeenCalledWith('task-1', 'product-1', 'workshop-1', undefined, 'ASSEMBLY')
    expect(api.create).not.toHaveBeenCalled()
  })

  it('申请数量为零或空白时保留选择但不生成领料明细', async () => {
    api.requirements.mockResolvedValue({ items: [
      structuredClone(semi),
      { ...structuredClone(semi), requirement_id: 'receiving-bom-line-2', material_name: '后脚管' },
      { ...structuredClone(semi), requirement_id: 'receiving-bom-line-3', material_name: '连接管' },
    ], blockers: [] })
    const wrapper = await formView()
    const vm = wrapper.vm as any
    vm.form.recipient_workshop_employee_id = 'recipient-1'
    vm.selected['receiving-bom-line'] = '0'
    vm.selected['receiving-bom-line-2'] = ''
    vm.selected['receiving-bom-line-3'] = '5'

    expect(vm.payload().lines).toEqual([{ requirement_id: 'receiving-bom-line-3', requested_quantity: '5' }])
    expect(vm.validate()).toBe('')

    vm.selected['receiving-bom-line-3'] = '0'
    expect(vm.payload().lines).toEqual([])
    expect(vm.validate()).toContain('至少填写一项大于 0 的领料数量')
  })

  it('缺少stock_mode的旧候选仍按既有余额分配提交', async () => {
    api.requirements.mockResolvedValue({ items: [{ ...semi, stock_mode: undefined, semi_balance_allocations: [
      { balance_id: 'legacy-a', max_issue_quantity: '2' }, { balance_id: 'legacy-b', max_issue_quantity: '8' },
    ] }], blockers: [] })
    const wrapper = await formView()
    const vm = wrapper.vm as any
    vm.selected['receiving-bom-line'] = '5'
    expect(vm.payload().lines).toEqual([{ requirement_id: 'legacy-a', requested_quantity: '2' }, { requirement_id: 'legacy-b', requested_quantity: '3' }])
  })

  it('编辑公共库存单加载需求携带已读取的issue_id并按接收行回填', async () => {
    route.params = { issueId: 'issue-1' }
    api.detail.mockResolvedValue({ data: detail(), etag: '"issue-1"' })
    const wrapper = await formView()
    const vm = wrapper.vm as any
    expect(api.requirements).toHaveBeenCalledWith('task-1', 'product-1', 'workshop-1', 'issue-1', 'ASSEMBLY')
    expect(vm.selected['receiving-bom-line']).toBe('5')
    expect(vm.editLoadComplete).toBe(true)
  })

  it('旧单编辑仍按旧余额映射回聚合行，不转换为公共领料', async () => {
    route.params = { issueId: 'issue-1' }
    const old = detail(null)
    old.lines[0]!.requirement_id = 'legacy-a'
    api.detail.mockResolvedValue({ data: old, etag: '"issue-1"' })
    api.requirements.mockResolvedValue({ items: [{ ...semi, stock_mode: undefined,
      semi_balance_allocations: [{ balance_id: 'legacy-a', max_issue_quantity: '8' }] }], blockers: [] })
    const wrapper = await formView()
    const vm = wrapper.vm as any
    expect(vm.selected['receiving-bom-line']).toBe('5')
    expect(vm.payload().lines).toEqual([{ requirement_id: 'legacy-a', requested_quantity: '5' }])
    expect(api.requirements).toHaveBeenCalledWith('task-1', 'product-1', 'workshop-1', 'issue-1', 'ASSEMBLY')
  })
})

describe('公共库存领料数量展示与实时预检', () => {
  it('审核详情将材质、规格、颜色单列展示且不显示已完成工艺列', async () => {
    const value = detail()
    value.status = 'PENDING_REVIEW'
    const wrapper = await detailView(value)
    const table = wrapper.findAll('section.detail-table')[1]!
    const headers = table.findAll('thead th').map(cell => cell.text())
    expect(headers).toContain('材质')
    expect(headers).toContain('规格')
    expect(headers).toContain('颜色')
    expect(headers).not.toContain('已完成工艺 / 库区')
    expect(table.find('tbody tr').text()).toContain('铁')
  })

  it('领料选择区不展示本订单剩余和公共可用量，空白数量仍保留已选物料', async () => {
    const wrapper = mount(MaterialIssuePartitions, { props: { requirements: [semi], selected: { 'receiving-bom-line': '5' }, allocations: {} },
      global: { plugins: [ElementPlus], stubs: { AppWindowDialog: dialogStub } } })
    wrappers.push(wrapper); await flushPromises()
    const partition = wrapper.get('[data-testid="semi-partition"]')
    expect(partition.text()).toContain('本订单需求')
    expect(partition.text()).toContain('本订单已领取')
    expect(partition.text()).toContain('本订单待审核')
    expect(partition.text()).not.toContain('本订单剩余')
    expect(partition.text()).not.toContain('公共可用量')
    expect(partition.text()).toContain('195 支')
    expect(partition.text()).toContain('不受来源订单限制')
    expect(partition.text()).not.toContain('批次')

    await wrapper.setProps({ selected: { 'receiving-bom-line': '' } })
    expect(wrapper.get('[data-testid="semi-partition"]').text()).toContain('前脚管')
  })

  it('公共半成品出库后订单剩余与库存快照独立显示', async () => {
    const value = detail()
    value.status = 'ISSUED'
    Object.assign(value.lines[0]!, { issued_quantity: '5', stock_before: '200', stock_after: '195' })
    const wrapper = await detailView(value)
    expect(tableValue(wrapper, '本订单需求')).toBe('100')
    expect(tableValue(wrapper, '本订单剩余')).toBe('70')
    expect(tableValue(wrapper, '本单出库前库存')).toBe('200')
    expect(tableValue(wrapper, '出库后结余')).toBe('195')
  })

  it('旧半成品出库记录继续使用历史库存字段，不把库存误称订单需求', async () => {
    const value = detail(null)
    value.status = 'ISSUED'
    Object.assign(value.lines[0]!, { required_quantity: '12', order_remaining: '7', issued_quantity: '5' })
    const wrapper = await detailView(value)
    expect(tableValue(wrapper, '本单出库前库存')).toBe('12')
    expect(tableValue(wrapper, '出库后结余')).toBe('7')
    expect(wrapper.findAll('section.detail-table')[1]!.text()).not.toContain('本订单需求')
    expect(wrapper.get('.detail-footer').text()).not.toContain('从公共库存扣减')
  })

  it('重新核对使用最新公共库存与订单额度，预检不完整阻止确认', async () => {
    const value = detail()
    value.status = 'PENDING_REVIEW'
    api.preview.mockResolvedValueOnce({ can_confirm: true, lines: [{ line_id: 'line-1', available_stock: '9', order_remaining: '6', max_issue_quantity: '6' }] })
    const wrapper = await detailView(value)
    const vm = wrapper.vm as any
    await vm.openConfirmation()
    expect(vm.confirmationRows[0].available_stock).toBe('9')
    expect(vm.confirmationRows[0].order_remaining).toBe('6')
    expect(vm.previewReady).toBe(true)
    api.preview.mockResolvedValueOnce({ can_confirm: true, lines: [] })
    await vm.openConfirmation()
    expect(vm.confirmationRows[0].available_stock).toBeUndefined()
    expect(vm.previewReady).toBe(false)
    await vm.confirmIssue()
    expect(api.confirm).not.toHaveBeenCalled()
    expect(vm.previewError).toContain('预检明细不完整')
  })

  it('公共管材确认采用预检根米，明细仅展示实际库区不展示来源UUID', async () => {
    const value = detail()
    value.status = 'PENDING_REVIEW'
    Object.assign(value.lines[0]!, { line_type: 'RAW', section_code: 'PROFILE', requested_quantity: '12', bar_count: '99', meters: '999.99',
      conversion_snapshot: { kind: 'PIPE', pieces_per_bar: 6, raw_bar_length_m: '3.05' } })
    api.preview.mockResolvedValue({ can_confirm: true, lines: [{ line_id: 'line-1', available_stock: '60', order_remaining: '30', max_issue_quantity: '30', bar_count: '2', meters: '6.10' }] })
    const wrapper = await detailView(value)
    const vm = wrapper.vm as any
    await vm.openConfirmation()
    expect(vm.confirmationRows[0].bar_count).toBe('2')
    expect(vm.confirmationRows[0].meters).toBe('6.10')
    expect(wrapper.get('[data-testid="issue-live-preview"]').text()).not.toContain('999.99')
    Object.assign(vm.issue, { status: 'ISSUED' })
    vm.issue.lines[0].public_stock_allocations = [{ id: 'private-allocation-id', balance_id: 'private-source-id', warehouse_zone: '管材仓 / 一楼', requested_quantity: '12', stock_quantity: '2', stock_unit: '根', meter_quantity: '6.10', before_quantity: '10', after_quantity: '8' }]
    await flushPromises()
    const deductions = wrapper.get('[data-testid="public-stock-deductions"]')
    expect(deductions.text()).toContain('管材仓 / 一楼')
    expect(deductions.text()).toContain('2 根 / 6.1 米')
    expect(deductions.text()).not.toContain('private-source-id')
    expect(deductions.text()).not.toContain('批次')
  })
})
