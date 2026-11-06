import { reactive } from 'vue'
import { flushPromises, mount, shallowMount, type VueWrapper } from '@vue/test-utils'
import ElementPlus, { ElMessageBox } from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as groupsApi from '@/api/purchaseGroups'
import * as ordersApi from '@/api/purchaseOrders'
import { fetchPurchaseOrderReadDetail } from '@/api/purchaseOrderReadDetail'
import type { PurchaseGroup } from '@/types/purchaseGroup'
import type { PurchaseOrderSource } from '@/types/purchaseOrder'
import { createPageTab } from '@/utils/pageTabs'
import PurchaseGroupList from '@/components/procurement/PurchaseGroupList.vue'
import PurchaseGroupDetailView from './PurchaseGroupDetailView.vue'
import PurchaseOrderFormView from './PurchaseOrderFormView.vue'
import PurchaseOrderListView from './PurchaseOrderListView.vue'
import PurchaseOrderDetailView from './PurchaseOrderDetailView.vue'
import PurchaseOrderConfirmView from './PurchaseOrderConfirmView.vue'

const state = vi.hoisted(() => ({ route: {} as Record<string, any>, push: vi.fn(), replace: vi.fn(), permissions: [] as string[] }))
vi.mock('vue-router', () => ({ useRoute: () => state.route, useRouter: () => ({ push: state.push, replace: state.replace }) }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ user: { id: 'u', is_superuser: false }, hasPermission: (permission: string) => state.permissions.includes(permission), moduleCan: (permission: string) => state.permissions.includes(permission) }) }))
vi.mock('@/stores/pageTabs', () => ({ usePageTabsStore: () => ({ accountId: 'u', setTabTitle: vi.fn() }) }))
vi.mock('@/api/purchaseGroups', () => ({ fetchPurchaseGroups: vi.fn(), fetchPurchaseGroupFilterOptions: vi.fn(), fetchVersionedPurchaseGroup: vi.fn(), createPurchaseGroup: vi.fn(), createPurchaseBatch: vi.fn(), completePurchaseGroup: vi.fn() }))
vi.mock('@/api/purchaseOrderReadDetail', () => ({ fetchPurchaseOrderReadDetail: vi.fn() }))
vi.mock('@/api/purchaseOrders', () => ({ fetchPurchaseOrderOptions: vi.fn(), fetchPurchaseOrderSource: vi.fn(), fetchSamplePurchaseOrderSource: vi.fn(), createPurchaseOrder: vi.fn(), fetchPurchaseOrders: vi.fn(), fetchPurchaseOrderFilterOptions: vi.fn(), fetchVersionedPurchaseOrder: vi.fn(), deletePurchaseOrder: vi.fn(), completePurchaseOrder: vi.fn(), fetchPurchaseOrderSupplierOptions: vi.fn(), updatePurchaseOrder: vi.fn(), confirmVersionedPurchaseOrder: vi.fn() }))

const groupFixture = (): PurchaseGroup => ({
  id: 'group-1', group_number: 'CGZD-1', production_task_id: 'task-1', product_line_id_snapshot: 'product-1', source_bom_id_snapshot: 'bom-1',
  production_task_number_snapshot: 'SC-1', sales_order_number_snapshot: 'XS-1', customer_name_snapshot: '测试客户', source_revision: 'source-v1', compatibility_issues: [], created_at: '', updated_at: '', batches: [],
  product: { product_line_id: 'product-1', product_name: '订单产品', specification: '180×80', material: '铝合金', color_card: '色卡A', color_name: '深蓝', color_code: 'B12', order_quantity: '240.0000', order_unit: '套' }, order_delivery_date: '2026-11-20',
  progress: { status: 'PURCHASING', satisfied_line_count: 0, line_count: 2, lines: [1, 2].map(number => ({
    id: `group-line-${number}`, line_number: number, source_bom_line_id_snapshot: `line-${number}`, product_line_id_snapshot: 'product-1', required_quantity: '100.0000', source_unit_text: '个', purchased_quantity: '150.0000', accepted_quantity: '99.9999', in_progress_quantity: '50.0001', in_progress_bar_count: null, progress_percent: '100.0000', is_satisfied: false, compatibility_issues: [],
    source_snapshot: { bom_id: 'bom-1', bom_line_id: `line-${number}`, source_bom_line_id_snapshot: `line-${number}`, product_line_id_snapshot: 'product-1', bom_number_snapshot: 'BOM-1', product_number_snapshot: 'P-1', product_code_snapshot: 'P-1', product_name_snapshot: '产品', product_specification_snapshot: '', section_type_snapshot: 'ACCESSORY', section_title_snapshot: '辅料', category_snapshot: '辅料', material_snapshot: '辅料', part_name_snapshot: `材料${number}`, specification_snapshot: '规格', raw_material_snapshot: `YL-${number}`, material_attributes_snapshot: {}, required_quantity: '100', source_quantity_field: 'quantity', source_quantity_text: '100', source_unit_text: '个', quantity_parse_status: 'READY', calculation_snapshot: {} },
  })) },
})
const options = () => ({ production_tasks: [], suppliers: [{ id: 'supplier-1', supplier_number: 'S1', supplier_name: '供应商', supplier_categories: ['AUXILIARY'] }], currencies: [{ id: 'cny', code: 'CNY', name: '人民币', symbol: '¥' }], default_currency_id: 'cny' })
const purchase = () => ({ id: 'batch-1', order_number: 'CGDD-1', status: 'DRAFT', purchase_group_id: 'group-1', batch_number: 1, batch_type: 'NORMAL', currency_code: 'CNY', lines: [], product_summary: [], supplier_summary: [], inbounds: [], returns: [], completion: {}, created_at: '' })
let wrapper: VueWrapper | undefined
const mountPage = async (component: any) => { wrapper = shallowMount(component, { props: component === PurchaseGroupList ? { canAdd: false } : {}, global: { plugins: [ElementPlus], stubs: { ElDatePicker: true } } }); await flushPromises(); return wrapper.vm as any }
const mountDetailWithAttributes = async () => {
  wrapper = shallowMount(PurchaseGroupDetailView, { global: { plugins: [ElementPlus], stubs: {
    ElTooltip: { name: 'ElTooltip', props: ['visible'], template: '<div><slot /><slot name="content" /></div>' },
  } } })
  await flushPromises()
}
beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(groupsApi.completePurchaseGroup).mockReset()
  state.permissions = ['procurement.view_purchaseorder', 'procurement.add_purchaseorder', 'procurement.change_purchaseorder', 'procurement.delete_purchaseorder', 'procurement.submit_purchaseorder']
  state.route = reactive({ name: 'purchase-batch-create', fullPath: '/purchase-groups/group-1/batches/new', params: { groupId: 'group-1', id: 'group-1' }, query: {} })
  vi.mocked(groupsApi.fetchVersionedPurchaseGroup).mockResolvedValue({ data: groupFixture(), etag: 'parent-v1' })
  vi.mocked(groupsApi.fetchPurchaseGroups).mockResolvedValue({ data: [groupFixture()], meta: { total: 1 } } as never)
  vi.mocked(groupsApi.fetchPurchaseGroupFilterOptions).mockResolvedValue({ production_tasks: [] })
  vi.mocked(groupsApi.createPurchaseGroup).mockResolvedValue({ data: groupFixture(), etag: 'parent-v1' })
  vi.mocked(groupsApi.createPurchaseBatch).mockResolvedValue({ data: purchase(), etag: 'child-v1' } as never)
  vi.mocked(ordersApi.fetchPurchaseOrderOptions).mockResolvedValue(options() as never)
  vi.mocked(ordersApi.fetchPurchaseOrders).mockResolvedValue({ data: [], meta: { total: 0, total_pages: 0 } } as never)
  vi.mocked(ordersApi.fetchPurchaseOrderFilterOptions).mockResolvedValue({ production_tasks: [], suppliers: [], statuses: [] })
  vi.mocked(ordersApi.fetchVersionedPurchaseOrder).mockResolvedValue({ data: purchase(), etag: 'child-v1' } as never)
  vi.mocked(ordersApi.fetchPurchaseOrderSupplierOptions).mockResolvedValue({ suppliers: [] })
  vi.mocked(ordersApi.updatePurchaseOrder).mockResolvedValue({ data: purchase(), etag: 'child-v2' } as never)
  vi.mocked(fetchPurchaseOrderReadDetail).mockResolvedValue(purchase() as never)
})
afterEach(() => { wrapper?.unmount(); wrapper = undefined; vi.restoreAllMocks() })

const completableGroup = (): PurchaseGroup => {
  const group = groupFixture()
  group.completion = { can_complete: true, blocked_reason: '' }
  group.display_status = 'PURCHASING'
  for (const line of group.progress.lines) Object.assign(line, { accepted_quantity: '50', progress_percent: '50' })
  group.batches = [{ id: 'batch-1', order_number: 'CGDD-1', batch_number: 1, batch_type: 'NORMAL', status: 'PURCHASING', display_status: 'COMPLETED', currency_code_snapshot: 'CNY', total_amount: '100' }]
  return group
}
const manuallyCompletedGroup = (): PurchaseGroup => ({ ...completableGroup(), display_status: 'COMPLETED', manual_completed_at: '2026-11-02T02:30:00Z', manual_completed_by_name: '采购员', manual_completion_remark: '按实际需求结束', completion: { can_complete: false, blocked_reason: '采购总单已手动完成。' } })
const mountCompletionPage = async (group = completableGroup(), permitted = true) => {
  if (permitted) state.permissions.push('access_control.complete_purchaseorder')
  vi.mocked(groupsApi.fetchVersionedPurchaseGroup).mockResolvedValue({ data: group, etag: 'parent-v1' })
  wrapper = shallowMount(PurchaseGroupDetailView, { global: { plugins: [ElementPlus], stubs: {
    ElTooltip: { name: 'ElTooltip', template: '<div><slot /></div>' },
    AppWindowDialog: { props: ['modelValue'], template: '<div v-if="modelValue" data-testid="completion-dialog"><slot /><slot name="footer" /></div>' },
  } } })
  await flushPromises()
  return wrapper.vm as any
}

describe('采购跟踪来源预选', () => {
  const source = (bomId = 'bom-1') => ({ can_create: true, selected_bom_id: bomId, source_revision: 'source-1',
    production_task: { id: 'task-1', products: [] }, bom_options: [{ bom_id: bomId, product_line_id: 'product-1' }],
    lines: [{ bom_line_id: 'line-1', required_quantity: '10' }], preview_lines: [], blockers: [], requires_bom_selection: false,
  })
  function setupTrackingLink() {
    state.route.name = 'purchase-order-create'
    state.route.fullPath = '/purchase-orders/new?production_task_id=task-1&bom_id=bom-1'
    state.route.query = { production_task_id: 'task-1', bom_id: 'bom-1' }
    vi.mocked(ordersApi.fetchPurchaseOrderOptions).mockResolvedValue({ ...options(), production_tasks: [{ id: 'task-1', task_number: 'SC-1', can_create: true }] } as never)
    vi.mocked(ordersApi.fetchPurchaseOrderSource).mockResolvedValue(source() as never)
  }
  it('预选真实任务及指定BOM，只读加载，仍通过原下一步建立总单', async () => {
    setupTrackingLink()
    const vm = await mountPage(PurchaseOrderFormView)
    expect(ordersApi.fetchPurchaseOrderSource).toHaveBeenCalledWith('task-1', 'bom-1')
    expect(vm.selectedTaskId).toBe('task-1')
    expect(vm.selectedBomId).toBe('bom-1')
    expect(groupsApi.createPurchaseGroup).not.toHaveBeenCalled()
    await wrapper!.get('[data-testid="purchase-source-next"]').trigger('click'); await flushPromises()
    expect(groupsApi.createPurchaseGroup).toHaveBeenCalledWith({ production_task_id: 'task-1', bom_id: 'bom-1', source_revision: 'source-1' })
  })
  it('任务不在可选范围时不请求或默认改选其他任务', async () => {
    setupTrackingLink()
    vi.mocked(ordersApi.fetchPurchaseOrderOptions).mockResolvedValue({ ...options(), production_tasks: [{ id: 'other', task_number: 'SC-2', can_create: true }] } as never)
    const vm = await mountPage(PurchaseOrderFormView)
    expect(ordersApi.fetchPurchaseOrderSource).not.toHaveBeenCalled()
    expect(vm.selectedTaskId).toBe('')
    expect(vm.preselectionError).toContain('当前可选范围')
    expect(wrapper!.get('[data-testid="purchase-source-next"]').attributes('disabled')).toBe('true')
  })
  it('指定BOM不可用时不接受接口默认的另一产品', async () => {
    setupTrackingLink()
    vi.mocked(ordersApi.fetchPurchaseOrderSource).mockResolvedValue(source('other-bom') as never)
    const vm = await mountPage(PurchaseOrderFormView)
    expect(vm.selectedBomId).toBe('')
    expect(vm.preselectionError).toContain('指定产品 BOM')
    expect(groupsApi.createPurchaseGroup).not.toHaveBeenCalled()
    expect(vm.canContinueToDetails).toBe(false)
  })
  it('来源读取失败可重试，成功后清除提示且不自动写入', async () => {
    setupTrackingLink()
    vi.mocked(ordersApi.fetchPurchaseOrderSource).mockRejectedValueOnce(new Error('offline'))
    const vm = await mountPage(PurchaseOrderFormView)
    expect(vm.preselectionError).toContain('读取失败')
    await vm.initializePage()
    expect(vm.selectedBomId).toBe('bom-1')
    expect(vm.preselectionError).toBe('')
    expect(groupsApi.createPurchaseGroup).not.toHaveBeenCalled()
  })
})

describe('采购总单手动完成', () => {
  it.each(['no-permission', 'old-response'])('%s不提供完成入口或写入', async mode => {
    const group = mode === 'old-response' ? groupFixture() : completableGroup()
    const vm = await mountCompletionPage(group, mode !== 'no-permission')
    expect(wrapper!.find('[data-testid="purchase-group-complete"]').exists()).toBe(false)
    await vm.openCompletion(); await vm.submitCompletion()
    expect(groupsApi.fetchVersionedPurchaseGroup).toHaveBeenCalledTimes(1)
    expect(groupsApi.completePurchaseGroup).not.toHaveBeenCalled()
  })
  it.each(['暂无已确认到货。', '仍有质检未完成。', '仍有退货未处理完。', '来源待核对。'])('按服务端原因禁用：%s', async reason => {
    const group = completableGroup(); group.completion = { can_complete: false, blocked_reason: reason }
    const vm = await mountCompletionPage(group)
    expect(wrapper!.get('[data-testid="purchase-group-complete"]').attributes('disabled')).toBe('true')
    expect(wrapper!.findComponent({ name: 'ElTooltip' }).attributes('content')).toBe(reason)
    await vm.openCompletion()
    expect(vm.completionVisible).toBe(false); expect(groupsApi.completePurchaseGroup).not.toHaveBeenCalled()
  })
  it('打开前重读条件与版本，取消不会提交', async () => {
    const vm = await mountCompletionPage()
    vi.mocked(groupsApi.fetchVersionedPurchaseGroup).mockResolvedValueOnce({ data: completableGroup(), etag: 'parent-v2' })
    await wrapper!.get('[data-testid="purchase-group-complete"]').trigger('click'); await flushPromises()
    expect(groupsApi.fetchVersionedPurchaseGroup).toHaveBeenCalledTimes(2)
    expect(vm.groupEtag).toBe('parent-v2')
    expect(wrapper!.get('[data-testid="completion-dialog"]').text()).toContain('材料进度保留实际入库情况，完成后仍可新增采购批次')
    vm.closeCompletion(); await flushPromises()
    expect(wrapper!.find('[data-testid="completion-dialog"]').exists()).toBe(false)
    expect(groupsApi.completePurchaseGroup).not.toHaveBeenCalled()
  })
  it('已自动完成仍可打开人工完成弹窗，保留真实进度并按版本提交记录', async () => {
    const group = completableGroup()
    group.display_status = 'COMPLETED'
    group.progress.status = 'COMPLETED'
    group.progress.satisfied_line_count = group.progress.line_count
    for (const line of group.progress.lines) Object.assign(line, { accepted_quantity: '150', progress_percent: '150', is_satisfied: true })
    const vm = await mountCompletionPage(group)
    expect(wrapper!.get('[data-testid="purchase-group-complete"]').attributes('disabled')).toBe('false')
    await vm.openCompletion()
    expect(vm.completionVisible).toBe(true)
    expect(wrapper!.text()).toContain('全部入库自动完成后，也可在此记录完成人、时间和备注')
    const completed = { ...group, manual_completed_at: '2026-11-03T02:30:00Z', manual_completed_by_name: '采购员', manual_completion_remark: '全部到齐', completion: { can_complete: false, blocked_reason: '采购总单已手动完成。' } }
    vi.mocked(groupsApi.completePurchaseGroup).mockResolvedValue({ data: completed, etag: 'parent-v2' })
    vm.completionRemark = '全部到齐'
    await vm.submitCompletion()
    expect(groupsApi.completePurchaseGroup).toHaveBeenCalledWith('group-1', '全部到齐', 'parent-v1')
    expect(vm.group.progress).toEqual(group.progress)
    expect(vm.group.manual_completion_remark).toBe('全部到齐')
    expect(vm.completionVisible).toBe(false)
  })
  it.each(['blocked', 'missing-etag'])('最新条件%s时不开确认弹窗', async mode => {
    const vm = await mountCompletionPage()
    const latest = completableGroup()
    if (mode === 'blocked') latest.completion = { can_complete: false, blocked_reason: '新增质检待处理。' }
    vi.mocked(groupsApi.fetchVersionedPurchaseGroup).mockResolvedValueOnce({ data: latest, etag: mode === 'missing-etag' ? '' : 'parent-v2' })
    await vm.openCompletion()
    expect(vm.completionVisible).toBe(false)
    expect(vm.completionError).toContain(mode === 'blocked' ? '新增质检待处理' : '未取得最新版本')
    expect(groupsApi.completePurchaseGroup).not.toHaveBeenCalled()
  })
  it('打开前读取失败可重试，不提交', async () => {
    const vm = await mountCompletionPage()
    vi.mocked(groupsApi.fetchVersionedPurchaseGroup).mockRejectedValueOnce(new Error('offline'))
    await vm.openCompletion()
    expect(vm.completionError).toContain('读取失败'); expect(vm.completionVisible).toBe(false)
    await vm.openCompletion()
    expect(vm.completionVisible).toBe(true); expect(groupsApi.completePurchaseGroup).not.toHaveBeenCalled()
  })
  it('低于建议量完成只更新展示状态与记录，仍可新增且原进度和批次不变', async () => {
    const vm = await mountCompletionPage()
    vi.mocked(groupsApi.fetchVersionedPurchaseGroup).mockResolvedValueOnce({ data: completableGroup(), etag: 'parent-v2' })
    vi.mocked(groupsApi.completePurchaseGroup).mockResolvedValueOnce({ data: manuallyCompletedGroup(), etag: 'parent-v3' })
    await vm.openCompletion()
    const progressBefore = JSON.stringify(vm.group.progress)
    const batchesBefore = JSON.stringify(vm.group.batches)
    vm.completionRemark = '  按实际需求结束  '
    await wrapper!.get('[data-testid="purchase-group-completion-submit"]').trigger('click'); await flushPromises()
    expect(groupsApi.completePurchaseGroup).toHaveBeenCalledWith('group-1', '按实际需求结束', 'parent-v2')
    expect(vm.groupEtag).toBe('parent-v3'); expect(vm.completionVisible).toBe(false)
    expect(JSON.stringify(vm.group.progress)).toBe(progressBefore); expect(JSON.stringify(vm.group.batches)).toBe(batchesBefore)
    expect(wrapper!.get('.group-summary').text()).toContain('0/2 项 · 采购完成')
    expect(wrapper!.get('.group-completion-record').text()).toContain('采购员 · 2026-11-02 10:30 · 按实际需求结束')
    expect(wrapper!.get('[data-line-id="group-line-1"]').findAll('td').slice(6).map(cell => cell.text())).toEqual(['50.0001 个', '50 个', '50%'])
    expect(wrapper!.get('[data-testid="purchase-group-add-batch"]').attributes('disabled')).toBe('false')
    expect(wrapper!.get('[data-testid="purchase-group-complete"]').attributes('disabled')).toBe('true')
    await vm.openCompletion(); await vm.submitCompletion()
    expect(groupsApi.completePurchaseGroup).toHaveBeenCalledTimes(1)
  })
  it('空备注可提交，2000字以内保留，超过上限不可提交', async () => {
    const vm = await mountCompletionPage(); await vm.openCompletion()
    vm.completionRemark = '文'.repeat(2001); await vm.submitCompletion()
    expect(groupsApi.completePurchaseGroup).not.toHaveBeenCalled(); expect(vm.completionRemarkTooLong).toBe(true)
    vm.completionRemark = '文'.repeat(2000); expect(vm.completionRemarkTooLong).toBe(false)
    vm.completionRemark = '   '
    vi.mocked(groupsApi.completePurchaseGroup).mockResolvedValueOnce({ data: manuallyCompletedGroup(), etag: 'v2' })
    await vm.submitCompletion()
    expect(groupsApi.completePurchaseGroup).toHaveBeenCalledWith('group-1', '', 'parent-v1')
  })
  it('提交中阻止重复点击、关闭和刷新，不自动重发', async () => {
    const vm = await mountCompletionPage(); await vm.openCompletion()
    let resolve!: (value: any) => void
    vi.mocked(groupsApi.completePurchaseGroup).mockReturnValueOnce(new Promise(done => { resolve = done }))
    const pending = vm.submitCompletion(); await flushPromises()
    await vm.submitCompletion(); vm.closeCompletion(); await vm.load()
    expect(groupsApi.completePurchaseGroup).toHaveBeenCalledTimes(1); expect(vm.completionVisible).toBe(true)
    expect(groupsApi.fetchVersionedPurchaseGroup).toHaveBeenCalledTimes(2)
    resolve({ data: manuallyCompletedGroup(), etag: 'v2' }); await pending
    expect(vm.completionSubmitting).toBe(false)
  })
  it('412刷新新ETag并保留备注，只在用户再次确认时提交', async () => {
    const vm = await mountCompletionPage(); await vm.openCompletion(); vm.completionRemark = '人工说明'
    vi.mocked(groupsApi.completePurchaseGroup).mockRejectedValueOnce({ response: { status: 412 } })
    const latest = completableGroup(); latest.progress.lines[0]!.accepted_quantity = '60'; latest.progress.lines[0]!.progress_percent = '60'
    vi.mocked(groupsApi.fetchVersionedPurchaseGroup).mockResolvedValueOnce({ data: latest, etag: 'parent-v2' })
    await vm.submitCompletion()
    expect(groupsApi.completePurchaseGroup).toHaveBeenCalledTimes(1)
    expect(vm.completionVisible).toBe(true); expect(vm.completionRemark).toBe('人工说明'); expect(vm.completionError).toContain('再次确认')
    expect(vm.group.progress.lines[0].accepted_quantity).toBe('60'); expect(vm.groupEtag).toBe('parent-v2')
    vi.mocked(groupsApi.completePurchaseGroup).mockResolvedValueOnce({ data: manuallyCompletedGroup(), etag: 'parent-v3' })
    await vm.submitCompletion()
    expect(groupsApi.completePurchaseGroup).toHaveBeenLastCalledWith('group-1', '人工说明', 'parent-v2')
  })
  it('冲突刷新后不可完成则保留原因和备注，阻止重试', async () => {
    const vm = await mountCompletionPage(); await vm.openCompletion(); vm.completionRemark = '保留说明'
    vi.mocked(groupsApi.completePurchaseGroup).mockRejectedValueOnce({ response: { status: 409 } })
    vi.mocked(groupsApi.fetchVersionedPurchaseGroup).mockResolvedValueOnce({ data: manuallyCompletedGroup(), etag: 'parent-v2' })
    await vm.submitCompletion(); await vm.submitCompletion()
    expect(vm.completionError).toBe('采购总单已手动完成。'); expect(vm.completionRemark).toBe('保留说明')
    expect(groupsApi.completePurchaseGroup).toHaveBeenCalledTimes(1)
  })
  it.each([403, 404, 503, undefined])('写入错误%s不假成功、不自动重试，备注保留', async status => {
    const vm = await mountCompletionPage(); await vm.openCompletion(); vm.completionRemark = '保留说明'
    vi.mocked(groupsApi.completePurchaseGroup).mockRejectedValueOnce({ response: { status, data: { error: { message: '请求未完成。' } } } })
    await vm.submitCompletion(); await vm.submitCompletion()
    expect(vm.completionSuccess).toBe(''); expect(vm.completionRemark).toBe('保留说明'); expect(vm.groupEtag).toBe('')
    expect(vm.completionError).toContain('请求未完成'); expect(vm.group.display_status).toBe('PURCHASING')
    expect(groupsApi.completePurchaseGroup).toHaveBeenCalledTimes(1)
  })
  it('412后刷新失败保留备注并禁止旧版本重试', async () => {
    const vm = await mountCompletionPage(); await vm.openCompletion(); vm.completionRemark = '保留说明'
    vi.mocked(groupsApi.completePurchaseGroup).mockRejectedValueOnce({ response: { status: 412 } })
    vi.mocked(groupsApi.fetchVersionedPurchaseGroup).mockRejectedValueOnce(new Error('offline'))
    await vm.submitCompletion(); await vm.submitCompletion()
    expect(vm.groupEtag).toBe(''); expect(vm.completionError).toContain('最新信息读取失败'); expect(vm.completionRemark).toBe('保留说明')
    expect(groupsApi.completePurchaseGroup).toHaveBeenCalledTimes(1)
  })
  it.each(['open', 'submit'])('%s迟到响应不覆盖切换后的总单', async phase => {
    const vm = await mountCompletionPage()
    let resolve!: (value: any) => void
    let pending: Promise<void>
    if (phase === 'submit') {
      await vm.openCompletion()
      vi.mocked(groupsApi.completePurchaseGroup).mockReturnValueOnce(new Promise(done => { resolve = done }))
      pending = vm.submitCompletion()
    } else {
      vi.mocked(groupsApi.fetchVersionedPurchaseGroup).mockReturnValueOnce(new Promise(done => { resolve = done }))
      pending = vm.openCompletion()
    }
    const other = { ...completableGroup(), id: 'group-2', group_number: 'CGZD-2' }
    vi.mocked(groupsApi.fetchVersionedPurchaseGroup).mockResolvedValue({ data: other, etag: 'other-v1' })
    state.route.params.id = 'group-2'; await flushPromises()
    resolve({ data: manuallyCompletedGroup(), etag: 'stale-v2' }); await pending
    expect(vm.group.id).toBe('group-2'); expect(vm.groupEtag).toBe('other-v1')
    expect(vm.completionVisible).toBe(false); expect(vm.completionSuccess).toBe('')
  })
  it('手动完成列表仍显示真实50%与未达标数，不伪造满进度', async () => {
    vi.mocked(groupsApi.fetchPurchaseGroups).mockResolvedValueOnce({ data: [manuallyCompletedGroup()], meta: { total: 1 } } as never)
    await mountPage(PurchaseGroupList)
    expect(wrapper!.get('[data-testid="purchase-group-total-progress"]').text()).toBe('50%')
    expect(wrapper!.getComponent({ name: 'ElProgress' }).props('status')).toBe('')
    const cells = wrapper!.findAll('.group-table tbody tr:first-child td')
    expect(cells[9]!.text()).toBe('0 / 2 项达标'); expect(cells[11]!.text()).toBe('采购完成')
  })
  it('手动完成后来源UNKNOWN仍警告且禁新增，列表进度仍待核对', async () => {
    const group = manuallyCompletedGroup(); group.progress.status = 'UNKNOWN'; group.progress.lines[0]!.progress_percent = null
    await mountCompletionPage(group)
    expect(wrapper!.get('[data-testid="purchase-group-add-batch"]').attributes('disabled')).toBe('true')
    expect(wrapper!.findAllComponents({ name: 'ElAlert' }).some(alert => String(alert.props('title')).includes('暂不能追加批次'))).toBe(true)
    wrapper!.unmount()
    vi.mocked(groupsApi.fetchPurchaseGroups).mockResolvedValueOnce({ data: [group], meta: { total: 1 } } as never)
    await mountPage(PurchaseGroupList)
    expect(wrapper!.get('[data-testid="purchase-group-total-progress"]').text()).toBe('待核对')
    expect(wrapper!.findAll('.group-table tbody td')[11]!.text()).toBe('采购完成')
  })
})

describe('总单与批次页面契约', () => {
  it('首次总单读取失败后保留输入重试仍初始化材料', async () => {
    vi.mocked(groupsApi.fetchVersionedPurchaseGroup).mockRejectedValueOnce({ response: { status: 503 } })
    const vm = await mountPage(PurchaseOrderFormView)
    expect(vm.lines).toEqual([]); expect(vm.batchConflict).not.toBe('')
    await vm.loadGroup(true)
    expect(vm.lines).toHaveLength(2); expect(vm.canWriteLines).toBe(true)
    vm.lines[0].actual_purchase_quantity = '10'; expect(vm.validateDraft()).toBe('')
  })
  it('初次选项失败通过页面重新加载完成总单初始化', async () => {
    vi.mocked(ordersApi.fetchPurchaseOrderOptions).mockRejectedValueOnce(new Error('options unavailable'))
    const vm = await mountPage(PurchaseOrderFormView)
    expect(vm.loadError).not.toBe(''); expect(groupsApi.fetchVersionedPurchaseGroup).not.toHaveBeenCalled()
    await vm.initializePage()
    expect(vm.loadError).toBe(''); expect(vm.lines).toHaveLength(2)
  })
  it('总单详情每项入库进度只显示单行百分比', async () => {
    const group = groupFixture(); group.progress.lines[1]!.progress_percent = '120.0000'; group.progress.lines[1]!.is_satisfied = true
    vi.mocked(groupsApi.fetchVersionedPurchaseGroup).mockResolvedValue({ data: group, etag: 'v1' })
    await mountPage(PurchaseGroupDetailView)
    expect(wrapper!.get('[data-line-id="group-line-1"] td:last-child').text()).toBe('100%')
    expect(wrapper!.find('[data-line-id="group-line-1"] td:last-child small').exists()).toBe(false)
    expect(wrapper!.get('[data-line-id="group-line-2"] td:last-child').text()).toBe('120%')
  })
  it('总单详情来源未知的入库进度继续显示来源待核对', async () => {
    const group = groupFixture(); group.progress.lines[0]!.progress_percent = null
    vi.mocked(groupsApi.fetchVersionedPurchaseGroup).mockResolvedValue({ data: group, etag: 'v1' })
    await mountPage(PurchaseGroupDetailView)
    expect(wrapper!.get('[data-line-id="group-line-1"] td:last-child').text()).toBe('来源待核对')
  })
  it('总单详情复用冻结目录属性，去说明，行悬停与键盘焦点可查看采购时信息', async () => {
    const group = groupFixture()
    Object.assign(group.progress.lines[0]!.source_snapshot, { section_type_snapshot: 'PROFILE', raw_bar_length_m: '4.2900',
      material_selection_snapshot: { schema_version: 1, name: '冻结方管', template_key: 'TUBE', unit_name: '米',
        attributes: { material: '铁', section_size: '20×20', thickness: '0.8', color: '黑色' }, color_card: '冻结色卡', color_code: 'A01' },
      material_attributes_snapshot: { fields: [{ key: 'material', label: '材质', value: '不应使用的旧材质' }] },
    })
    vi.mocked(groupsApi.fetchVersionedPurchaseGroup).mockResolvedValue({ data: group, etag: 'v1' })
    await mountDetailWithAttributes()
    const row = wrapper!.get('[data-line-id="group-line-1"]')
    const trigger = row.get('.material-detail')
    expect(trigger.text()).toBe('冻结方管')
    expect(trigger.attributes('tabindex')).toBe('0')
    const attributes = row.get('.material-attribute-tooltip').text()
    for (const value of ['冻结方管', '材质铁', '规格20×20', '厚度0.8', '颜色黑色', '冻结色卡', 'A01', '采购原长4.29 米/根']) expect(attributes).toContain(value)
    expect(attributes).not.toContain('不应使用的旧材质')
    expect(wrapper!.text()).not.toContain('合格入库进度按总单保存的 BOM 建议量计算')
    const tooltip = row.getComponent({ name: 'ElTooltip' })
    expect(tooltip.props('visible')).toBe(false)
    await row.trigger('mouseenter'); expect(tooltip.props('visible')).toBe(true)
    await row.trigger('mouseleave'); expect(tooltip.props('visible')).toBe(false)
    await trigger.trigger('focus'); expect(tooltip.props('visible')).toBe(true)
    await trigger.trigger('keydown', { key: 'Escape' }); expect(tooltip.props('visible')).toBe(false)
    await trigger.trigger('blur'); expect(tooltip.props('visible')).toBe(false)
    expect(ordersApi.fetchPurchaseOrderSource).not.toHaveBeenCalled()
  })
  it.each(['saved-fields', 'legacy-fallback', 'empty'])('总单详情属性%s沿已有保存字段和缺失兜底', async mode => {
    const group = groupFixture()
    const source = group.progress.lines[0]!.source_snapshot
    if (mode === 'saved-fields') source.material_attributes_snapshot = { fields: [{ key: 'specification', label: '面料规格', value: '旧单600D' }] } as never
    if (mode === 'empty') Object.assign(source, { part_name_snapshot: '', material_snapshot: '', specification_snapshot: '', raw_material_snapshot: '' })
    vi.mocked(groupsApi.fetchVersionedPurchaseGroup).mockResolvedValue({ data: group, etag: 'v1' })
    await mountDetailWithAttributes()
    const row = wrapper!.get('[data-line-id="group-line-1"]')
    expect(row.get('.material-detail').text()).toBe(mode === 'saved-fields' ? '旧单600D' : mode === 'empty' ? '—' : '材料1')
    expect(row.get('.material-attribute-tooltip').text()).toContain(mode === 'saved-fields' ? '面料规格旧单600D' : mode === 'empty' ? '暂无物料属性' : '材质辅料')
  })
  it('总单管材使用保存建议根数与后端实际累计根数，原米数不重算', async () => {
    const group = groupFixture()
    const line = group.progress.lines[0]!
    Object.assign(line, { source_unit_text: '米', required_quantity: '1000.0000', purchased_quantity: '1716.0000', accepted_quantity: '686.4000', purchased_bar_count: '400', accepted_bar_count: '160', in_progress_quantity: '1029.6000', in_progress_bar_count: '240' })
    Object.assign(line.source_snapshot, { section_type_snapshot: 'PROFILE', raw_bar_length_m: '4.29', suggested_bar_count: 234, suggested_purchase_meters: '1003.86' })
    vi.mocked(groupsApi.fetchVersionedPurchaseGroup).mockResolvedValue({ data: group, etag: 'v1' })
    await mountPage(PurchaseGroupDetailView)
    expect(wrapper!.get('[data-line-id="group-line-1"]').findAll('td').slice(4, 8).map(cell => cell.text())).toEqual(['234 根 / 1000 米', '400 根 / 1716 米', '240 根 / 1029.6 米', '160 根 / 686.4 米'])
  })
  it.each([undefined, null])('总单管材根数缺失%s时待核对，不按米数除原长反推', async missing => {
    const group = groupFixture()
    const line = group.progress.lines[0]!
    Object.assign(line, { source_unit_text: '米', required_quantity: '60', purchased_quantity: '60', accepted_quantity: '30', purchased_bar_count: missing, accepted_bar_count: missing, in_progress_quantity: '30', in_progress_bar_count: missing })
    Object.assign(line.source_snapshot, { section_type_snapshot: 'PROFILE', raw_bar_length_m: '6', suggested_bar_count: missing })
    vi.mocked(groupsApi.fetchVersionedPurchaseGroup).mockResolvedValue({ data: group, etag: 'v1' })
    await mountPage(PurchaseGroupDetailView)
    expect(wrapper!.get('[data-line-id="group-line-1"]').findAll('td').slice(4, 8).map(cell => cell.text())).toEqual(['根数待核对 / 60 米', '根数待核对 / 60 米', '根数待核对 / 30 米', '根数待核对 / 30 米'])
  })
  it('总单根数保留零与大整数字符串，非管材维持原单位', async () => {
    const group = groupFixture()
    const line = group.progress.lines[0]!
    Object.assign(line, { source_unit_text: '米', required_quantity: '0', purchased_quantity: '1', accepted_quantity: '0', purchased_bar_count: '9007199254740993', accepted_bar_count: '0', in_progress_quantity: '1', in_progress_bar_count: '9007199254740993' })
    Object.assign(line.source_snapshot, { section_type_snapshot: 'PROFILE', suggested_bar_count: 0, raw_bar_length_m: null })
    group.progress.lines[1]!.purchased_bar_count = '10'
    vi.mocked(groupsApi.fetchVersionedPurchaseGroup).mockResolvedValue({ data: group, etag: 'v1' })
    await mountDetailWithAttributes()
    expect(wrapper!.get('[data-line-id="group-line-1"]').findAll('td').slice(4, 8).map(cell => cell.text())).toEqual(['0 根 / 0 米', '9007199254740993 根 / 1 米', '9007199254740993 根 / 1 米', '0 根 / 0 米'])
    expect(wrapper!.get('[data-line-id="group-line-1"] .material-attribute-tooltip').text()).toContain('采购原长待核对')
    expect(wrapper!.get('[data-line-id="group-line-2"]').findAll('td').slice(4, 8).map(cell => cell.text())).toEqual(['100 个', '150 个', '50.0001 个', '99.9999 个'])
  })
  it('正在采购置于累计采购与合格入库之间，只显示后端值而不改原进度', async () => {
    const group = groupFixture(); group.progress.lines[0]!.in_progress_quantity = '12.3000'
    vi.mocked(groupsApi.fetchVersionedPurchaseGroup).mockResolvedValue({ data: group, etag: 'parent-v1' })
    await mountPage(PurchaseGroupDetailView)
    expect(wrapper!.findAll('.progress-table th').map(cell => cell.text())).toEqual(['序号', '分类', '物料信息', '规格', 'BOM 建议量', '累计采购', '正在采购', '合格入库', '入库进度'])
    expect(wrapper!.findAll('.progress-table col')).toHaveLength(9)
    expect(wrapper!.get('[data-line-id="group-line-1"]').findAll('td').slice(5).map(cell => cell.text())).toEqual(['150 个', '12.3 个', '99.9999 个', '100%'])
    expect(wrapper!.get('.group-summary').text()).toContain('采购中')
    expect(wrapper!.find('[data-line-id="group-line-1"] td:last-child small').exists()).toBe(false)
  })
  it.each([undefined, null])('正在采购字段缺失或null(%s)显示待核对而非零', async missing => {
    const group = groupFixture()
    for (const line of group.progress.lines) Object.assign(line, { in_progress_quantity: missing, in_progress_bar_count: missing })
    Object.assign(group.progress.lines[1]!, { source_unit_text: '米' })
    Object.assign(group.progress.lines[1]!.source_snapshot, { section_type_snapshot: 'PROFILE', raw_bar_length_m: '6' })
    vi.mocked(groupsApi.fetchVersionedPurchaseGroup).mockResolvedValue({ data: group, etag: 'parent-v1' })
    await mountPage(PurchaseGroupDetailView)
    expect(wrapper!.get('[data-line-id="group-line-1"]').findAll('td')[6]!.text()).toBe('待核对 个')
    expect(wrapper!.get('[data-line-id="group-line-2"]').findAll('td')[6]!.text()).toBe('根数待核对 / 待核对 米')
  })
  it('正在采购零值保留零，管材米数未知时仍保留实际根数', async () => {
    const group = groupFixture()
    group.progress.lines[0]!.in_progress_quantity = '0.0000'
    const pipe = group.progress.lines[1]!
    Object.assign(pipe, { source_unit_text: '米', in_progress_quantity: '0.0000', in_progress_bar_count: '0' })
    pipe.source_snapshot.section_type_snapshot = 'PROFILE'
    vi.mocked(groupsApi.fetchVersionedPurchaseGroup).mockResolvedValue({ data: group, etag: 'parent-v1' })
    const vm = await mountPage(PurchaseGroupDetailView)
    expect(wrapper!.get('[data-line-id="group-line-1"]').findAll('td')[6]!.text()).toBe('0 个')
    expect(wrapper!.get('[data-line-id="group-line-2"]').findAll('td')[6]!.text()).toBe('0 根 / 0 米')
    Object.assign(vm.group.progress.lines[1], { in_progress_quantity: null, in_progress_bar_count: '9' }); await flushPromises()
    expect(wrapper!.get('[data-line-id="group-line-2"]').findAll('td')[6]!.text()).toBe('9 根 / 待核对 米')
  })
  it('材料空表仍覆盖九列', async () => {
    const group = groupFixture(); group.progress.lines = []; group.progress.line_count = 0
    vi.mocked(groupsApi.fetchVersionedPurchaseGroup).mockResolvedValue({ data: group, etag: 'parent-v1' })
    await mountPage(PurchaseGroupDetailView)
    expect(wrapper!.get('.progress-table .empty').attributes('colspan')).toBe('9')
  })
  it('总单详情首卡产品字段与列表同格式，保留其他信息但不显示BOM编号', async () => {
    const group = groupFixture(); group.progress.lines[0]!.source_snapshot.product_name_snapshot = '错误的第一款产品'
    vi.mocked(groupsApi.fetchVersionedPurchaseGroup).mockResolvedValue({ data: group, etag: 'v1' })
    await mountPage(PurchaseGroupDetailView)
    const summary = wrapper!.get('.group-summary')
    expect(summary.findAll('dt').map(item => item.text())).toEqual(['生产订单', '销售订单 / 客户', '产品', '规格', '颜色', '材质', '订单量', '订单交期', '采购批次', '材料达标'])
    expect(summary.findAll('dd').map(item => item.text())).toEqual(['SC-1', 'XS-1 · 测试客户', '订单产品', '180×80', '色卡A / 深蓝 / B12', '铝合金', '240.0000 套', '2026-11-20', '0 批', '0/2 项 · 采购中'])
    expect(summary.text()).not.toContain('BOM'); expect(summary.text()).not.toContain('错误的第一款产品')
  })
  it.each([null, undefined])('总单详情缺失产品%s时不回退首材料行', async product => {
    const group = groupFixture(); group.product = product; group.order_delivery_date = null
    vi.mocked(groupsApi.fetchVersionedPurchaseGroup).mockResolvedValue({ data: group, etag: 'v1' })
    await mountPage(PurchaseGroupDetailView)
    expect(wrapper!.findAll('.group-summary dd').slice(2, 8).map(item => item.text())).toEqual(['来源待核对', '—', '—', '—', '—', '—'])
  })
  it('总单详情历史产品空属性占位，缺数量不单独显示单位', async () => {
    const group = groupFixture()
    Object.assign(group.product!, { product_name: '历史产品', specification: '', material: '', color_card: '', color_name: '', color_code: '', order_quantity: null, order_unit: '套' })
    group.order_delivery_date = null
    vi.mocked(groupsApi.fetchVersionedPurchaseGroup).mockResolvedValue({ data: group, etag: 'v1' })
    await mountPage(PurchaseGroupDetailView)
    expect(wrapper!.findAll('.group-summary dd').slice(2, 8).map(item => item.text())).toEqual(['历史产品', '—', '—', '—', '—', '—'])
  })
  it('总单详情订单量保留大数字十进制原文', async () => {
    const group = groupFixture(); group.product!.order_quantity = '9007199254740993.1234'
    vi.mocked(groupsApi.fetchVersionedPurchaseGroup).mockResolvedValue({ data: group, etag: 'v1' })
    await mountPage(PurchaseGroupDetailView)
    expect(wrapper!.findAll('.group-summary dd')[6]!.text()).toBe('9007199254740993.1234 套')
  })
  it('总单列表操作改为查看明细，仍进入原总单详情', async () => {
    wrapper = mount(PurchaseGroupList, { props: { canAdd: false }, global: { plugins: [ElementPlus] } })
    await flushPromises()
    const button = wrapper.get('.group-table tbody tr:first-child td:last-child button')
    expect(button.text()).toBe('查看明细')
    await button.trigger('click')
    expect(state.push).toHaveBeenLastCalledWith({ name: 'purchase-group-detail', params: { id: 'group-1' } })
  })
  it.each(['COMPLETED', 'UNKNOWN'] as const)('%s使用真实状态控制新增入口', async status => {
    const group = groupFixture(); group.progress.status = status
    vi.mocked(groupsApi.fetchVersionedPurchaseGroup).mockResolvedValue({ data: group, etag: 'v1' })
    await mountPage(PurchaseGroupDetailView)
    const add = wrapper!.findAllComponents({ name: 'ElButton' }).find(item => item.attributes('data-testid') === 'purchase-group-add-batch')!
    expect(add.props('disabled')).toBe(status === 'UNKNOWN')
  })
  it('总单列表只发送任务和分页，加载失败不保留旧结果', async () => {
    const vm = await mountPage(PurchaseGroupList)
    vm.taskId = 'task-2'; vm.search(); await flushPromises()
    expect(groupsApi.fetchPurchaseGroups).toHaveBeenLastCalledWith({ production_task_id: 'task-2', page: 1, page_size: 50 })
    vi.mocked(groupsApi.fetchPurchaseGroups).mockRejectedValueOnce(new Error('网络异常'))
    await vm.load(); expect(vm.rows).toEqual([]); expect(vm.errorMessage).toContain('加载失败')
  })
  it('总单列表按13列展示精确订单产品，不从首条材料行取产品或恢复第二行小字', async () => {
    const group = groupFixture()
    Object.assign(group.progress.lines[0]!.source_snapshot, { product_name_snapshot: '错误的第一款产品', product_specification_snapshot: '材料规格', material_snapshot: '材料材质', material_attributes_snapshot: { color: '材料颜色' } })
    vi.mocked(groupsApi.fetchPurchaseGroups).mockResolvedValue({ data: [group], meta: { total: 1 } } as never)
    await mountPage(PurchaseGroupList)
    expect(wrapper!.findAll('.group-table th').map(cell => cell.text())).toEqual(['采购总单', '来源订单', '产品', '规格', '颜色', '材质', '订单量', '订单交期', '总采购进度', '材料进度', '批次', '状态', '操作'])
    const cells = wrapper!.findAll('.group-table tbody tr:first-child td')
    expect(cells).toHaveLength(13)
    expect(cells.slice(0, 12).map(cell => cell.text())).toEqual(['CGZD-1', 'SC-1', '订单产品', '180×80', '色卡A / 深蓝 / B12', '铝合金', '240.0000 套', '2026-11-20', '99.9%', '0 / 2 项达标', '0', '采购中'])
    expect(wrapper!.find('.group-table small').exists()).toBe(false)
    for (const hidden of ['XS-1', '测试客户', 'BOM-1', '错误的第一款产品', '材料规格', '材料材质', '材料颜色']) expect(wrapper!.get('.group-table').text()).not.toContain(hidden)
  })
  it.each([null, undefined])('总单产品来源缺失%s时占位，不使用材料行猜产品字段', async product => {
    const group = groupFixture(); group.product = product; group.order_delivery_date = null; group.progress.status = 'UNKNOWN'
    vi.mocked(groupsApi.fetchPurchaseGroups).mockResolvedValue({ data: [group], meta: { total: 1 } } as never)
    await mountPage(PurchaseGroupList)
    const cells = wrapper!.findAll('.group-table tbody tr:first-child td')
    expect(cells.slice(2, 8).map(cell => cell.text())).toEqual(['来源待核对', '—', '—', '—', '—', '—'])
    expect(cells[11]!.text()).toBe('来源待核对')
  })
  it('总单保留后端给出的历史产品名称，空属性和缺失数量占位且不单独显示单位', async () => {
    const group = groupFixture()
    Object.assign(group.product!, { product_name: '历史冻结产品', specification: '', material: '', color_card: '', color_name: '', color_code: '', order_quantity: null, order_unit: '套' })
    group.order_delivery_date = null
    vi.mocked(groupsApi.fetchPurchaseGroups).mockResolvedValue({ data: [group], meta: { total: 1 } } as never)
    await mountPage(PurchaseGroupList)
    const cells = wrapper!.findAll('.group-table tbody tr:first-child td')
    expect(cells.slice(2, 8).map(cell => cell.text())).toEqual(['历史冻结产品', '—', '—', '—', '—', '—'])
  })
  it('总单列表空态横跨13列', async () => {
    vi.mocked(groupsApi.fetchPurchaseGroups).mockResolvedValue({ data: [], meta: { total: 0 } } as never)
    await mountPage(PurchaseGroupList)
    expect(wrapper!.get('.group-table .empty').attributes('colspan')).toBe('13')
    expect(wrapper!.get('.group-table .empty').text()).toBe('暂无采购总单')
  })
  it.each([
    { label: '未入库', percentages: ['0', '0'], expected: 0 },
    { label: '部分入库等权平均', percentages: ['20', '80'], expected: 50 },
    { label: '超采先封顶不能抵消未入库材料', percentages: ['150', '0'], expected: 50 },
    { label: '全部实际达标', percentages: ['100', '180'], expected: 100 },
    { label: '当前11项材料', percentages: ['80', '80', '80', '80', '45.4545', '50', '50', '50', '100', '100', '100'], expected: 74.1 },
  ])('总采购进度：$label', async ({ percentages, expected }) => {
    const group = groupFixture()
    group.progress.lines = percentages.map((percent, index) => ({ ...group.progress.lines[0]!, id: `progress-${index}`, progress_percent: percent, is_satisfied: Number(percent) >= 100 }))
    group.progress.line_count = percentages.length
    group.progress.satisfied_line_count = group.progress.lines.filter(line => line.is_satisfied).length
    group.progress.status = group.progress.satisfied_line_count === percentages.length ? 'COMPLETED' : 'PURCHASING'
    vi.mocked(groupsApi.fetchPurchaseGroups).mockResolvedValue({ data: [group], meta: { total: 1 } } as never)
    await mountPage(PurchaseGroupList)
    expect(wrapper!.get('[data-testid="purchase-group-total-progress"]').text()).toBe(`${expected}%`)
    const progress = wrapper!.getComponent({ name: 'ElProgress' })
    expect(progress.props('percentage')).toBe(expected)
    expect(progress.props('status')).toBe(expected === 100 ? 'success' : '')
    expect(wrapper!.findAll('.group-table tbody tr:first-child td')[9]!.text()).toBe(`${group.progress.satisfied_line_count} / ${percentages.length} 项达标`)
  })
  it('总采购进度不把已四舍五入到100的未达标材料显示为完成', async () => {
    vi.mocked(groupsApi.fetchPurchaseGroups).mockResolvedValue({ data: [groupFixture()], meta: { total: 1 } } as never)
    await mountPage(PurchaseGroupList)
    expect(wrapper!.get('[data-testid="purchase-group-total-progress"]').text()).toBe('99.9%')
    expect(wrapper!.getComponent({ name: 'ElProgress' }).props('status')).toBe('')
    expect(wrapper!.findAll('.group-table tbody tr:first-child td')[11]!.text()).toBe('采购中')
  })
  it.each(['UNKNOWN', 'null', 'empty', 'missing-line', 'invalid-number', 'inconsistent-count'])('总采购进度来源异常%s时显示待核对，不绘制假零进度', async issue => {
    const group = groupFixture()
    if (issue === 'UNKNOWN') group.progress.status = 'UNKNOWN'
    if (issue === 'null') group.progress.lines[0]!.progress_percent = null
    if (issue === 'empty') { group.progress.lines = []; group.progress.line_count = 0 }
    if (issue === 'missing-line') group.progress.line_count = 3
    if (issue === 'invalid-number') group.progress.lines[0]!.progress_percent = 'NaN'
    if (issue === 'inconsistent-count') group.progress.satisfied_line_count = 2
    vi.mocked(groupsApi.fetchPurchaseGroups).mockResolvedValue({ data: [group], meta: { total: 1 } } as never)
    await mountPage(PurchaseGroupList)
    expect(wrapper!.get('[data-testid="purchase-group-total-progress"]').text()).toBe('待核对')
    expect(wrapper!.findComponent({ name: 'ElProgress' }).exists()).toBe(false)
  })
  it('只读总单筛选包含未在当前页的空父任务，不调用创建或子单选项', async () => {
    state.permissions = ['procurement.view_purchaseorder']
    const emptyTask = { id: 'empty-task', task_number: 'EMPTY', order_number: 'SAVED' }
    vi.mocked(groupsApi.fetchPurchaseGroupFilterOptions).mockResolvedValue({ production_tasks: [emptyTask] })
    const vm = await mountPage(PurchaseGroupList)
    expect(vm.tasks).toEqual([emptyTask])
    expect(ordersApi.fetchPurchaseOrderFilterOptions).not.toHaveBeenCalled()
    expect(ordersApi.fetchPurchaseOrderOptions).not.toHaveBeenCalled()
    vm.taskId = emptyTask.id; vm.search(); await flushPromises()
    expect(groupsApi.fetchPurchaseGroups).toHaveBeenLastCalledWith({ production_task_id: emptyTask.id, page: 1, page_size: 50 })
    vi.mocked(groupsApi.fetchPurchaseGroupFilterOptions).mockRejectedValueOnce(new Error('options failed'))
    await vm.loadOptions(); expect(vm.optionsError).not.toBe('')
    await vm.loadOptions(); expect(vm.optionsError).toBe(''); expect(vm.tasks).toEqual([emptyTask])
  })
  it.each([
    ['100.0000', '40.0000', '60'], ['100', '0', '100'], ['100', '100', '0'], ['100', '150', '0'],
    ['0', '0', '0'], ['0.3000', '0.2000', '0.1'], ['9007199254740993.0001', '9007199254740993', '0.0001'],
  ])('批次剩余按已采购精确扣减 %s - %s，不用入库量', async (required, purchased, expected) => {
    const group = groupFixture()
    Object.assign(group.progress.lines[0]!, { required_quantity: required, purchased_quantity: purchased, accepted_quantity: '0' })
    vi.mocked(groupsApi.fetchVersionedPurchaseGroup).mockResolvedValue({ data: group, etag: 'parent-v1' })
    const vm = await mountPage(PurchaseOrderFormView)
    expect(vm.batchRemainingQuantities.get('group-line-1')).toEqual({ primary: expected, detail: '个' })
    expect(vm.lines[0].required_quantity).toBe(required)
    expect(vm.lines[0].actual_purchase_quantity).toBe(expected)
  })
  it('批次缺失或非法数量待核对，不能强转为零', async () => {
    const vm = await mountPage(PurchaseOrderFormView)
    const line = vm.group.progress.lines[0]
    for (const value of [null, undefined, '', ' ', '-1', 'abc', '1e2', 20]) {
      Object.assign(line, { required_quantity: '100', purchased_quantity: value })
      expect(vm.batchRemainingQuantities.get(line.id).primary).toBe('待核对')
      Object.assign(line, { required_quantity: value, purchased_quantity: '20' })
      expect(vm.batchRemainingQuantities.get(line.id).primary).toBe('待核对')
    }
  })
  it('首次剩余数量缺失不带入假默认值，用户清空后仍不计入本批', async () => {
    const group = groupFixture()
    group.progress.lines[0]!.purchased_quantity = null
    group.progress.lines[1]!.purchased_quantity = '40'
    vi.mocked(groupsApi.fetchVersionedPurchaseGroup).mockResolvedValue({ data: group, etag: 'parent-v1' })
    const vm = await mountPage(PurchaseOrderFormView)
    expect(vm.lines[0].actual_purchase_quantity).toBe('')
    expect(vm.lines[1].actual_purchase_quantity).toBe('60')
    expect(vm.selectedLines).toHaveLength(1)
    vm.lines[1].actual_purchase_quantity = ''
    expect(vm.effectivePurchaseQuantity(vm.lines[1])).toBe('')
    expect(vm.selectedLines).toEqual([])
  })
  it('批次管材剩余根米分别扣减，米用采购建议米且缺根不反推', async () => {
    const group = groupFixture(); const line = group.progress.lines[0]!
    Object.assign(line, { required_quantity: '100', purchased_quantity: '18', purchased_bar_count: '3', accepted_quantity: '0', source_unit_text: '米' })
    Object.assign(line.source_snapshot, { section_type_snapshot: 'PROFILE', raw_bar_length_m: null, suggested_bar_count: 17, suggested_purchase_meters: '102' })
    vi.mocked(groupsApi.fetchVersionedPurchaseGroup).mockResolvedValue({ data: group, etag: 'parent-v1' })
    wrapper = mount(PurchaseOrderFormView, { global: { plugins: [ElementPlus], stubs: { ElDatePicker: true } } })
    await flushPromises()
    const vm = wrapper.vm as any
    expect(wrapper.get('.quantity-cell').text()).toBe('14 根84 米')
    expect(vm.lines[0].actual_bar_count).toBe('')
    Object.assign(vm.group.progress.lines[0], { purchased_bar_count: '20', purchased_quantity: '90' })
    await flushPromises()
    expect(wrapper.get('.quantity-cell').text()).toBe('0 根12 米')
    for (const value of [null, undefined, '', '-1', '3.5', 'abc']) {
      vm.group.progress.lines[0].purchased_bar_count = value
      expect(vm.batchRemainingQuantities.get(line.id)).toEqual({ primary: '根数待核对', detail: '12 米' })
    }
    Object.assign(vm.group.progress.lines[0], { purchased_bar_count: '3', purchased_quantity: null })
    expect(vm.batchRemainingQuantities.get(line.id)).toEqual({ primary: '14 根', detail: '米数待核对' })
    for (const value of [null, undefined, 1.5, Number.MAX_SAFE_INTEGER + 1]) {
      vm.group.progress.lines[0].source_snapshot.suggested_bar_count = value
      expect(vm.batchRemainingQuantities.get(line.id).primary).toBe('根数待核对')
    }
  })
  it('刷新缺少原材料行时剩余显示待核对，不回退旧建议或清理手填', async () => {
    wrapper = mount(PurchaseOrderFormView, { global: { plugins: [ElementPlus], stubs: { ElDatePicker: true } } })
    await flushPromises()
    const vm = wrapper.vm as any
    vm.lines[0].actual_purchase_quantity = '12'
    const refreshed = groupFixture(); refreshed.progress.lines = []; refreshed.progress.line_count = 0; refreshed.progress.status = 'UNKNOWN'
    vi.mocked(groupsApi.fetchVersionedPurchaseGroup).mockResolvedValue({ data: refreshed, etag: 'parent-v2' })
    await vm.loadGroup(true); await flushPromises()
    expect(wrapper.get('.quantity-cell').text()).toBe('待核对')
    expect(vm.lines).toHaveLength(2); expect(vm.lines[0].actual_purchase_quantity).toBe('12')
  })
  it('非批次生产采购仍显示建议采购量及原始数量', async () => {
    state.route.name = 'purchase-order-create-details'
    wrapper = mount(PurchaseOrderFormView, { global: { plugins: [ElementPlus], stubs: { ElDatePicker: true } } })
    await flushPromises()
    const vm = wrapper.vm as any
    vm.applySource({ can_create: true, selected_bom_id: 'bom-1', bom_options: [], blockers: [], preview_lines: [],
      lines: [{ bom_line_id: 'line-1', section_type: 'ACCESSORY', category: '辅料', part_name: '辅料', material: '辅料', raw_material: '辅料',
        required_quantity: '100.0000', source_quantity_text: '100', source_unit_text: '个', quantity_parse_status: 'READY' }],
    } as unknown as PurchaseOrderSource)
    await flushPromises()
    const headers = wrapper.findAll('.el-table__header th').map(cell => cell.text())
    expect(headers).toContain('建议采购量'); expect(headers).not.toContain('剩余采购量')
    expect(wrapper.get('.quantity-cell').text()).toBe('100个')
    expect(vm.effectivePurchaseQuantity(vm.lines[0])).toBe('100')
  })
  it('剩余为零仍显示整行，超量补料自动计入且不读取最新BOM', async () => {
    wrapper = mount(PurchaseOrderFormView, { global: { plugins: [ElementPlus], stubs: { ElDatePicker: true } } })
    await flushPromises()
    const vm = wrapper.vm as any
    expect(vm.lines.every((line: any) => line.actual_purchase_quantity === '0' && line.actual_bar_count === '')).toBe(true)
    expect(vm.selectedLines).toEqual([])
    const headers = wrapper.findAll('.el-table__header th').map(cell => cell.text())
    expect(headers).toContain('实际采购数量'); expect(headers).toContain('剩余采购量'); expect(headers).not.toContain('建议采购量'); expect(headers).not.toContain('选择')
    expect(wrapper.findAll('.quantity-cell').map(cell => cell.text())).toEqual(['0个', '0个'])
    expect(vm.lines[0].required_quantity).toBe('100.0000')
    expect(wrapper.get('[data-testid="purchase-line-quantity"] input').attributes('disabled')).toBeUndefined()
    expect(wrapper.find('input[type="checkbox"]').exists()).toBe(false)
    vm.lines[0].actual_purchase_quantity = '150.1234'; vm.batchType = 'SUPPLEMENT'
    await vm.createOrder('list')
    expect(groupsApi.createPurchaseBatch).toHaveBeenCalledWith('group-1', expect.objectContaining({ batch_type: 'SUPPLEMENT', lines: [expect.objectContaining({ purchase_group_line_id: 'group-line-1', actual_purchase_quantity: '150.1234' })] }), 'parent-v1')
    expect(ordersApi.fetchPurchaseOrderSource).not.toHaveBeenCalled()
    expect(ordersApi.createPurchaseOrder).not.toHaveBeenCalled()
    expect(state.push).toHaveBeenCalledWith({ name: 'purchase-group-detail', params: { id: 'group-1' } })
  })
  it('根数使用冻结每根长度显示和计价，payload只发送根数', async () => {
    const group = groupFixture(); Object.assign(group.progress.lines[0]!, { purchased_quantity: '18', purchased_bar_count: '3' }); Object.assign(group.progress.lines[0]!.source_snapshot, { section_type_snapshot: 'PROFILE', raw_bar_length_m: '6.00', suggested_bar_count: 17, suggested_purchase_meters: '102.0000' })
    vi.mocked(groupsApi.fetchVersionedPurchaseGroup).mockResolvedValue({ data: group, etag: 'parent-v1' })
    const vm = await mountPage(PurchaseOrderFormView)
    expect(vm.lines[0].actual_bar_count).toBe('14')
    expect(vm.effectivePurchaseQuantity(vm.lines[0])).toBe('84.00')
    vm.lines[0].actual_bar_count = '30'
    expect(vm.isPipePurchaseLine(vm.lines[0])).toBe(false)
    expect(wrapper!.find('[aria-label="采购每根长度（米）"]').exists()).toBe(false)
    expect(vm.effectivePurchaseQuantity(vm.lines[0])).toBe('180.00')
    await vm.createOrder('list')
    const input = vi.mocked(groupsApi.createPurchaseBatch).mock.calls[0]![1].lines[0]!
    expect(input.actual_bar_count).toBe('30'); expect(input).not.toHaveProperty('raw_bar_length_m'); expect(input).not.toHaveProperty('actual_purchase_quantity')
  })
  it('失败后内容改变使用新UUID，409保留输入且不自动重试', async () => {
    const vm = await mountPage(PurchaseOrderFormView)
    vm.lines[0].actual_purchase_quantity = '150'
    vi.mocked(groupsApi.createPurchaseBatch).mockRejectedValueOnce(new Error('timeout'))
    await vm.createOrder('list')
    const firstId = vi.mocked(groupsApi.createPurchaseBatch).mock.calls[0]![1].request_id
    expect(vm.batchConflict).toContain('提交结果尚未确认')
    vm.lines[0].actual_purchase_quantity = '160'
    vi.mocked(groupsApi.createPurchaseBatch).mockRejectedValueOnce({ response: { status: 409, data: { error: { message: '请求冲突' } } } })
    await vm.createOrder('list')
    expect(vi.mocked(groupsApi.createPurchaseBatch).mock.calls[1]![1].request_id).not.toBe(firstId)
    expect(vm.lines[0].actual_purchase_quantity).toBe('160'); expect(vm.batchConflict).toBe('请求冲突')
    expect(groupsApi.createPurchaseBatch).toHaveBeenCalledTimes(2)
  })
  it('提交中冻结批次控件并拒绝重复提交', async () => {
    const vm = await mountPage(PurchaseOrderFormView)
    vm.lines[0].actual_purchase_quantity = '100'
    let resolve: (value: any) => void = () => undefined
    vi.mocked(groupsApi.createPurchaseBatch).mockReturnValue(new Promise(done => { resolve = done }))
    const pending = vm.createOrder('list'); await flushPromises()
    expect(vm.saving).toBe(true); expect(vm.canWriteLines).toBe(false)
    await vm.createOrder('list'); expect(groupsApi.createPurchaseBatch).toHaveBeenCalledTimes(1)
    resolve({ data: purchase(), etag: 'child-v1' }); await pending
  })
  it('空白/零数量不提交；412后输入和UUID保留，刷新同步剩余再重试', async () => {
    const group = groupFixture(); group.progress.lines[0]!.purchased_quantity = '40'
    vi.mocked(groupsApi.fetchVersionedPurchaseGroup).mockResolvedValue({ data: group, etag: 'parent-v1' })
    const vm = await mountPage(PurchaseOrderFormView)
    expect(vm.batchRemainingQuantities.get('group-line-1').primary).toBe('60')
    expect(vm.lines[0].actual_purchase_quantity).toBe('60')
    vm.lines[0].actual_purchase_quantity = ''
    await vm.createOrder('list'); expect(groupsApi.createPurchaseBatch).not.toHaveBeenCalled()
    vm.lines[0].actual_purchase_quantity = '0'
    await vm.createOrder('list'); expect(groupsApi.createPurchaseBatch).not.toHaveBeenCalled()
    Object.assign(vm.lines[0], { actual_purchase_quantity: '150', supplier_id: 'supplier-1', delivery_date: '2026-11-20', unit_price: '2' })
    vm.batchType = 'SUPPLEMENT'
    vi.mocked(groupsApi.createPurchaseBatch).mockRejectedValueOnce({ response: { status: 412 } })
    await vm.createOrder('list')
    const firstId = vi.mocked(groupsApi.createPurchaseBatch).mock.calls[0]![1].request_id
    expect(vm.batchConflict).toContain('输入已保留')
    const refreshed = groupFixture(); refreshed.progress.lines[0]!.purchased_quantity = '80'
    vi.mocked(groupsApi.fetchVersionedPurchaseGroup).mockResolvedValue({ data: refreshed, etag: 'parent-v2' })
    await vm.loadGroup(true)
    expect(vm.lines[0]).toMatchObject({ required_quantity: '100.0000', actual_purchase_quantity: '150', supplier_id: 'supplier-1', delivery_date: '2026-11-20', unit_price: '2' })
    expect(vm.batchRemainingQuantities.get('group-line-1').primary).toBe('20')
    expect(vm.batchType).toBe('SUPPLEMENT'); expect(vm.selectedLines).toHaveLength(1)
    await vm.createOrder('list')
    expect(vi.mocked(groupsApi.createPurchaseBatch).mock.calls[1]![1].request_id).toBe(firstId)
    expect(vi.mocked(groupsApi.createPurchaseBatch).mock.calls[1]![2]).toBe('parent-v2')
    expect(vi.mocked(groupsApi.createPurchaseBatch).mock.calls[1]![1]).toMatchObject({ batch_type: 'SUPPLEMENT', lines: [expect.objectContaining({ actual_purchase_quantity: '150', supplier_id: 'supplier-1', delivery_date: '2026-11-20' })] })
  })
  it('同时按正需求与本次正数量计入，金额和计数只用本批行', async () => {
    const vm = await mountPage(PurchaseOrderFormView)
    expect(vm.effectivePurchaseQuantity(vm.lines[0])).toBe('0')
    Object.assign(vm.lines[0], { actual_purchase_quantity: '12.5', unit_price: '2', supplier_id: 'supplier-1' })
    Object.assign(vm.lines[1], { required_quantity: '0', actual_purchase_quantity: '20', unit_price: '100', supplier_id: 'other' })
    expect(vm.selectedLines).toHaveLength(1); expect(vm.totalAmount).toBe('25.00'); expect(vm.selectedSupplierCount).toBe(1)
    await vm.createOrder('list')
    expect(vi.mocked(groupsApi.createPurchaseBatch).mock.calls[0]![1].lines).toHaveLength(1)
    for (const requirement of ['0', '-1', null]) {
      vm.lines[0].required_quantity = requirement
      expect(vm.selectedLines).toEqual([])
    }
  })
  it.each(['-1', 'abc', '1e3', '1.00001'])('其他行填写非法数量%s时不能静默跳过', async quantity => {
    const vm = await mountPage(PurchaseOrderFormView)
    vm.lines[0].actual_purchase_quantity = '10'; vm.lines[1].actual_purchase_quantity = quantity
    expect(vm.validateDraft()).toContain('第 2 行实际采购数量')
    await vm.createOrder('list'); expect(groupsApi.createPurchaseBatch).not.toHaveBeenCalled()
  })
  it('管材小数根数拒绝，零根不提交；已完成总单仍可超量补批', async () => {
    const group = groupFixture(); group.progress.status = 'COMPLETED'
    Object.assign(group.progress.lines[0]!.source_snapshot, { section_type_snapshot: 'PROFILE', raw_bar_length_m: '6.00', suggested_bar_count: 17 })
    vi.mocked(groupsApi.fetchVersionedPurchaseGroup).mockResolvedValue({ data: group, etag: 'parent-v1' })
    const vm = await mountPage(PurchaseOrderFormView)
    vm.lines[0].actual_bar_count = '1.5'; expect(vm.validateDraft()).toContain('管材根数应为整数')
    vm.lines[0].actual_bar_count = '0'; expect(vm.selectedLines).toEqual([])
    vm.lines[0].actual_bar_count = '30'; await vm.createOrder('list')
    expect(vi.mocked(groupsApi.createPurchaseBatch).mock.calls[0]![1].lines[0]!.actual_bar_count).toBe('30')
  })
  it('正数量缺供应商交期单价仍计入，草稿可保存而确认继续提示', async () => {
    const vm = await mountPage(PurchaseOrderFormView)
    vm.lines[1].actual_purchase_quantity = '10'
    expect(vm.selectedLines).toHaveLength(1); expect(vm.validateDraft()).toBe('')
    expect(vm.validateConfirmation()).toContain('供应商、采购交期、采购单价')
    await vm.createOrder('confirm'); expect(groupsApi.createPurchaseBatch).not.toHaveBeenCalled()
    await vm.createOrder('list'); expect(vi.mocked(groupsApi.createPurchaseBatch).mock.calls[0]![1].lines[0]).toMatchObject({
      purchase_group_line_id: 'group-line-2', actual_purchase_quantity: '10', supplier_id: null, delivery_date: null, unit_price: null,
    })
  })
  it.each([['TUBE', 'TUBE'], ['HARDWARE', 'HARDWARE'], ['PLASTIC', 'PLASTIC_PART'], ['PACKAGING', 'PACKAGING'], ['FABRIC', 'FABRIC'], ['AUXILIARY', 'AUXILIARY']])('冻结目录类别%s优先于名称关键词', async (category, expected) => {
    const group = groupFixture()
    Object.assign(group.progress.lines[0]!.source_snapshot, {
      material_selection_snapshot: { category_key: category }, material_snapshot: '塑料五金件', category_snapshot: '辅料类',
    })
    vi.mocked(groupsApi.fetchVersionedPurchaseGroup).mockResolvedValue({ data: group, etag: 'parent-v1' })
    const vm = await mountPage(PurchaseOrderFormView)
    expect(vm.lines[0].suggested_supplier_category).toBe(expected)
    expect(ordersApi.fetchPurchaseOrderSource).not.toHaveBeenCalled()
  })
  it('无目录类别的历史行按冻结文本兼容，未知目录类别不猜配', async () => {
    const vm = await mountPage(PurchaseOrderFormView)
    const snapshot = groupFixture().progress.lines[0]!.source_snapshot
    expect(vm.groupSupplierCategory(snapshot)).toBe('AUXILIARY')
    expect(vm.groupSupplierCategory({ ...snapshot, section_type_snapshot: 'PROFILE' })).toBe('TUBE')
    expect(vm.groupSupplierCategory({ ...snapshot, part_name_snapshot: '塑料袋' })).toBe('PACKAGING')
    for (const key of ['FUTURE_CATEGORY', '__proto__']) {
      expect(vm.groupSupplierCategory({ ...snapshot, material_selection_snapshot: { category_key: key } })).toBeNull()
    }
    vm.lines[0].suggested_supplier_category = null; vm.bulkSupplierCategory = '辅料'
    expect(vm.bulkSupplierOptions).toEqual([]); expect(vm.bulkSupplierEmptyText).toContain('尚未对应')
    vm.bulkSupplierCategory = '__all__'; expect(vm.bulkSupplierOptions).toHaveLength(1)
  })
  it('未填数量也可按分类统一供应商并同步交期，后填数量仅提交该行', async () => {
    const group = groupFixture()
    Object.assign(group.progress.lines[0]!.source_snapshot, { category_snapshot: '辅料类', material_snapshot: '塑料配件', material_selection_snapshot: { category_key: 'AUXILIARY' } })
    Object.assign(group.progress.lines[1]!.source_snapshot, { category_snapshot: '五金类', material_selection_snapshot: { category_key: 'HARDWARE' } })
    vi.mocked(groupsApi.fetchVersionedPurchaseGroup).mockResolvedValue({ data: group, etag: 'parent-v1' })
    const supplierOptions = options()
    supplierOptions.suppliers.push({ id: 'hardware', supplier_number: 'S2', supplier_name: '五金供应商', supplier_categories: ['HARDWARE'] })
    vi.mocked(ordersApi.fetchPurchaseOrderOptions).mockResolvedValue(supplierOptions as never)
    const vm = await mountPage(PurchaseOrderFormView)
    vm.bulkSupplierCategory = '辅料类'; await flushPromises()
    expect(vm.bulkSupplierOptions.map((supplier: any) => supplier.id)).toEqual(['supplier-1'])
    expect(wrapper!.get('[data-testid="purchase-bulk-supplier"]').getComponent({ name: 'ElSelect' }).props('disabled')).toBe(false)
    vm.applyBulkSupplier('supplier-1'); vm.applyBulkDeliveryDate('2026-11-20')
    expect(vm.lines.map((line: any) => line.supplier_id)).toEqual(['supplier-1', null])
    expect(vm.lines.map((line: any) => line.delivery_date)).toEqual(['2026-11-20', '2026-11-20'])
    vm.bulkSupplierCategory = '五金类'; vm.refreshBulkSupplier(); expect(vm.bulkSupplierId).toBeNull()
    vm.applyBulkSupplier('hardware'); expect(vm.lines.map((line: any) => line.supplier_id)).toEqual(['supplier-1', 'hardware'])
    vm.lines[0].actual_purchase_quantity = '10'; vm.lines[0].unit_price = '2'; await vm.createOrder('list')
    expect(vi.mocked(groupsApi.createPurchaseBatch).mock.calls[0]![1].lines).toEqual([expect.objectContaining({ supplier_id: 'supplier-1', delivery_date: '2026-11-20', actual_purchase_quantity: '10' })])
    vm.bulkSupplierCategory = '__all__'; expect(vm.bulkSupplierOptions).toHaveLength(2)
    vm.applyBulkSupplier('hardware'); expect(vm.lines.map((line: any) => line.supplier_id)).toEqual(['hardware', 'hardware'])
  })
  it('新生产来源创建总单后进入首批，既有总单从blocker进入', async () => {
    state.route.name = 'purchase-order-create'
    const vm = await mountPage(PurchaseOrderFormView)
    vm.selectedTaskId = 'task-1'
    vm.applySource({ can_create: true, selected_bom_id: 'bom-1', source_revision: 'revision', lines: [{ bom_line_id: 'line-1' }], bom_options: [], blockers: [], preview_lines: [] } as unknown as PurchaseOrderSource)
    await vm.goToDetails()
    expect(groupsApi.createPurchaseGroup).toHaveBeenCalledWith({ production_task_id: 'task-1', bom_id: 'bom-1', source_revision: 'revision' })
    expect(state.push).toHaveBeenLastCalledWith({ name: 'purchase-batch-create', params: { groupId: 'group-1' } })
    vm.source.blockers = [{ code: 'PURCHASE_GROUP_EXISTS', existing_purchase_group_id: 'group-2' }]
    await vm.openExistingGroup(); expect(state.push).toHaveBeenLastCalledWith({ name: 'purchase-group-detail', params: { id: 'group-2' } })
  })
  it('默认采购总单且无视图切换，显式旧单入口仍共用全局页签身份', async () => {
    state.route.name = 'purchase-orders'
    state.permissions.push('procurement.view_supplier')
    state.route.query = {}
    await mountPage(PurchaseOrderListView)
    expect(wrapper!.findComponent(PurchaseGroupList).exists()).toBe(true)
    expect(wrapper!.get('h1').text()).toBe('采购总单')
    expect(wrapper!.find('[aria-label="采购视图"]').exists()).toBe(false)
    expect(wrapper!.find('[aria-label="采购订单清单"]').exists()).toBe(false)
    state.route.query = { view: 'orders' }; await flushPromises()
    expect(wrapper!.find('[aria-label="采购订单清单"]').exists()).toBe(true)
    state.route.query = {}; await flushPromises()
    expect(wrapper!.findComponent(PurchaseGroupList).exists()).toBe(true)
    expect(wrapper!.find('.page-heading__actions [data-testid="purchase-suppliers-entry"]').exists()).toBe(true)
    const route = { name: 'purchase-orders', path: '/purchase-orders', fullPath: '/purchase-orders?view=groups', params: {}, query: { view: 'groups' }, meta: { layout: 'erp' } }
    expect(createPageTab(route)!.id).toBe(createPageTab({ ...route, fullPath: '/purchase-orders?view=orders', query: { view: 'orders' } })!.id)
  })
  it('仅采购查看权也能从总单进入跟踪，不依赖供应商查看权', async () => {
    state.route.name = 'purchase-orders'
    state.route.query = {}
    state.permissions = ['procurement.view_purchaseorder']
    await mountPage(PurchaseOrderListView)
    await wrapper!.get('[data-testid="purchase-tracking-entry"]').trigger('click')
    expect(state.push).toHaveBeenLastCalledWith({ name: 'purchase-tracking' })
    expect(wrapper!.find('[data-testid="purchase-suppliers-entry"]').exists()).toBe(false)
  })
  it('没有采购查看权不显示跟踪入口', async () => {
    state.route.name = 'purchase-orders'
    state.permissions = ['procurement.view_supplier']
    await mountPage(PurchaseOrderListView)
    expect(wrapper!.find('[data-testid="purchase-tracking-entry"]').exists()).toBe(false)
    expect(wrapper!.find('[data-testid="purchase-suppliers-entry"]').exists()).toBe(true)
  })
  it('删除已关联批次先读取子单ETag', async () => {
    vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue('confirm' as never)
    state.route.query = { view: 'orders' }
    const vm = await mountPage(PurchaseOrderListView)
    await vm.removeOrder(purchase())
    expect(ordersApi.deletePurchaseOrder).toHaveBeenCalledWith('batch-1', 'child-v1')
  })
  it('批次优先显示后端入库完成状态，旧字段回退且总单进度与草稿操作不变', async () => {
    const group = groupFixture()
    group.batches = ([['PURCHASING', 'COMPLETED'], ['PURCHASING', 'PURCHASING'], ['DRAFT', 'DRAFT'], ['COMPLETED', undefined], ['SUBMITTED', undefined]] as const)
      .map(([status, display_status], index) => ({ id: `batch-${index}`, order_number: `CGDD-${index}`, batch_number: index + 1, batch_type: 'NORMAL', status, display_status, currency_code_snapshot: 'CNY', total_amount: '100' }))
    vi.mocked(groupsApi.fetchVersionedPurchaseGroup).mockResolvedValue({ data: group, etag: 'parent-v1' })
    const vm = await mountPage(PurchaseGroupDetailView)
    const rows = wrapper!.findAll('.batch-table tbody tr')
    expect(rows.map(row => row.findAll('td')[3]!.text())).toEqual(['采购完成', '采购中', '草稿', '采购完成', '已确认'])
    expect(rows.map(row => row.findAllComponents({ name: 'ElButton' }).length)).toEqual([1, 1, 2, 1, 1])
    expect(vm.group.batches[0].status).toBe('PURCHASING')
    expect(wrapper!.get('.group-summary').text()).toContain('0/2 项 · 采购中')
    expect(wrapper!.get('[data-line-id="group-line-1"]').findAll('td')[6]!.text()).toBe('50.0001 个')
    expect(ordersApi.completePurchaseOrder).not.toHaveBeenCalled()
  })
  it('批次详情头部与新显示状态一致，但不编造完成记录', async () => {
    state.route.name = 'purchase-order-detail'
    state.permissions.push('procurement.view_supplierpurchasesheet')
    vi.mocked(fetchPurchaseOrderReadDetail).mockResolvedValue({ ...purchase(), status: 'PURCHASING', status_display: '采购中', display_status: 'COMPLETED', completed_at: null, completed_by_name: '', completion_remark: '' } as never)
    const vm = await mountPage(PurchaseOrderDetailView)
    const status = wrapper!.get('.heading-identity .detail-tag')
    expect(status.text()).toBe('采购完成'); expect(status.classes()).toContain('success')
    expect(vm.order.status).toBe('PURCHASING')
    expect(wrapper!.get('.heading-actions').text()).toContain('查看采购表')
    await wrapper!.get('#purchase-detail-tab-completion').trigger('click')
    expect(wrapper!.get('.completion-record').text()).toBe('暂无完成记录')
    expect(ordersApi.completePurchaseOrder).not.toHaveBeenCalled()
  })
  it('旧批次详情缺少显示状态时沿原采购状态', async () => {
    vi.mocked(fetchPurchaseOrderReadDetail).mockResolvedValue({ ...purchase(), status: 'PURCHASING', status_display: '采购中' } as never)
    await mountPage(PurchaseOrderDetailView)
    const status = wrapper!.get('.heading-identity .detail-tag')
    expect(status.text()).toBe('采购中'); expect(status.classes()).toContain('info')
  })
  it('原手动完成批次仍完成并保留实际完成记录', async () => {
    vi.mocked(fetchPurchaseOrderReadDetail).mockResolvedValue({ ...purchase(), status: 'COMPLETED', status_display: '已完成采购', completed_at: '2026-11-02T02:00:00Z', completed_by_name: '原完成人', completion_remark: '原完成备注' } as never)
    await mountPage(PurchaseOrderDetailView)
    expect(wrapper!.get('.heading-identity .detail-tag').text()).toBe('采购完成')
    await wrapper!.get('#purchase-detail-tab-completion').trigger('click')
    expect(wrapper!.get('.completion-record .detail-tag').text()).toBe('已完成采购')
    expect(wrapper!.get('.completion-record').text()).toContain('原完成人')
    expect(wrapper!.get('.completion-record').text()).toContain('原完成备注')
  })
  it.each(['PRODUCTION', 'SAMPLE'])('非批次%s详情保持原状态文案和样式', async source_type => {
    vi.mocked(fetchPurchaseOrderReadDetail).mockResolvedValue({ ...purchase(), purchase_group_id: null, source_type, status: 'PURCHASING', status_display: '原采购中', display_status: 'COMPLETED' } as never)
    await mountPage(PurchaseOrderDetailView)
    const status = wrapper!.get('.heading-identity .detail-tag')
    expect(status.text()).toBe('原采购中'); expect(status.classes()).toContain('info')
    expect(groupsApi.fetchVersionedPurchaseGroup).not.toHaveBeenCalled()
  })
  it('仓库查看批次不请求无权父单，仍返回采购入库', async () => {
    state.permissions = ['inventory.receive_material']; state.route.name = 'purchase-inbound-detail'
    const vm = await mountPage(PurchaseOrderDetailView)
    expect(fetchPurchaseOrderReadDetail).toHaveBeenCalled()
    expect(groupsApi.fetchVersionedPurchaseGroup).not.toHaveBeenCalled()
    expect(wrapper!.text()).toContain('已关联采购总单')
    vm.backToList(); expect(state.push).toHaveBeenLastCalledWith({ name: 'purchase-inbounds' })
  })
  it.each([403, 404])('父单%s失败返回旧列表，恢复可读后返回父单', async status => {
    vi.mocked(groupsApi.fetchVersionedPurchaseGroup).mockRejectedValue({ response: { status } })
    const vm = await mountPage(PurchaseOrderDetailView)
    expect(vm.order.id).toBe('batch-1'); expect(vm.errorMessage).toBe(''); expect(vm.groupError).toContain('仍可查看')
    expect(wrapper!.get('.heading-actions .erp-list-button--primary').text()).toBe('返回采购订单')
    vm.backToList(); expect(state.push).toHaveBeenLastCalledWith({ name: 'purchase-orders', query: { view: 'orders' } })
    vi.mocked(groupsApi.fetchVersionedPurchaseGroup).mockResolvedValue({ data: groupFixture(), etag: 'parent-v1' })
    await vm.load(); await flushPromises()
    expect(wrapper!.get('.heading-actions .erp-list-button--primary').text()).toBe('返回采购总单')
    vm.backToList(); expect(state.push).toHaveBeenLastCalledWith({ name: 'purchase-group-detail', params: { id: 'group-1' } })
  })
  it('编辑草稿只传原批次行和类型，不提供新增材料集合', async () => {
    const vm = await mountPage(PurchaseOrderConfirmView)
    vm.order.batch_type = 'SUPPLEMENT'; vm.order.lines = [{ id: 'existing-line', supplier_id: null, delivery_date: null, actual_purchase_quantity: '150', unit_price: null }]
    await vm.saveChanges()
    expect(ordersApi.updatePurchaseOrder).toHaveBeenCalledWith('batch-1', expect.objectContaining({ batch_type: 'SUPPLEMENT', lines: [expect.objectContaining({ id: 'existing-line' })] }), 'child-v1')
    expect(groupsApi.fetchVersionedPurchaseGroup).not.toHaveBeenCalled()
    vm.backToList(); expect(state.push).toHaveBeenLastCalledWith({ name: 'purchase-group-detail', params: { id: 'group-1' } })
    vm.order.purchase_group_id = null
    vm.backToList(); expect(state.push).toHaveBeenLastCalledWith({ name: 'purchase-orders', query: { view: 'orders' } })
  })
})
