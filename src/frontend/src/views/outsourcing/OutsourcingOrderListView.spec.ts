import { flushPromises, mount } from '@vue/test-utils'
import { reactive } from 'vue'
import ElementPlus, { ElMessageBox } from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import OutsourcingOrderListView from './OutsourcingOrderListView.vue'

const api = vi.hoisted(() => ({ list: vi.fn(), options: vi.fn(), fetch: vi.fn(), remove: vi.fn(), revoke: vi.fn(), push: vi.fn(), replace: vi.fn() }))
const permissions = vi.hoisted(() => ({ superuser: true, values: [] as string[] }))
const route = reactive({ query: {} as Record<string, string>, meta: {} as Record<string, string> })
vi.mock('@/api/outsourcing', () => ({
  fetchOutsourcingOrder: api.fetch,
  deleteOutsourcingOrder: api.remove, revokeDispatchedOutsourcingOrder: api.revoke,
}))
vi.mock('@/api/unifiedOutsourcing', async (original) => ({ ...await original<object>(), fetchUnifiedOutsourcingOrders: api.list, fetchUnifiedOutsourcingOptions: api.options }))
vi.mock('./MetalProcessingP4View.vue', () => ({ default: { name: 'MetalProcessingP4View', props: ['mode', 'embedded'], emits: ['updated'], template: '<div data-testid="sources-workspace">来源工作区</div>' } }))
vi.mock('@/components/outsourcing/OutsourcingPrintDialog.vue', () => ({ default: { props: ['record', 'kind'], emits: ['close'], template: '<div data-testid="print-dialog" />' } }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ user: { get is_superuser() { return permissions.superuser } }, hasPermission: (name: string) => permissions.values.includes(name) }) }))
vi.mock('vue-router', () => ({ useRoute: () => route, useRouter: () => ({ push: api.push, replace: api.replace }) }))

const row = {
  id: 'order-1', order_number: 'WW-001', direct_handoff: false, can_delete: false, can_revoke_dispatched: true,
  row_key: 'ORIGINAL:order-1', record_type: 'ORIGINAL', source_kind: 'RAW', source_label: '仓库原料', detail_access: 'REGULAR',
  dispatched_quantities: [{ quantity: '183.75', unit: '米' }], returned_quantities: [{ quantity: '120', unit: '套' }],
  schedule_number: 'PLAN-001', production_task_number: 'HT-001', product: { product_name: '折叠椅', product_number: 'PRODUCT-001', material: 'PE' }, product_count: 1,
  craft: { name: '喷塑' }, factory_names: ['加工厂'], factory_count: 1,
  processing_count: 1, returned_processing_count: 0, delivery_date: '2026-10-01', planned_amount: '12.5000' as string | null,
  status: 'PROCESSING', status_display: '加工中', updated_at: '2026-09-27T00:00:00Z',
}

const wrappers: ReturnType<typeof mount>[] = []

async function createView(initialRow = row) {
  api.list.mockResolvedValue({ data: [initialRow], meta: { total: 1 } })
  api.options.mockResolvedValue({ statuses: [], crafts: [], factories: [] })
  const wrapper = mount(OutsourcingOrderListView, { global: { plugins: [ElementPlus], stubs: { RouterLink: true } } })
  wrappers.push(wrapper)
  await flushPromises()
  return wrapper
}

beforeEach(() => { vi.resetAllMocks(); permissions.superuser = true; permissions.values = []; route.query = {}; route.meta = {} })
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()); vi.restoreAllMocks() })

describe('普通外发单列表删除入口', () => {
  it('已发料单按服务端许可撤销并退料，操作前重新读取详情和版本', async () => {
    route.meta = { outsourcingWorkspace: 'warehouse' }
    const wrapper = await createView()
    api.fetch.mockResolvedValue({ data: { id: row.id, direct_handoff: false, can_delete: false, can_revoke_dispatched: true }, etag: '"fresh"' })
    api.revoke.mockResolvedValue({ data: { id: row.id, status: 'CANCELLED' }, etag: '"new"' })
    vi.spyOn(ElMessageBox, 'prompt').mockResolvedValue({ value: ' 误发退料 ', action: 'confirm' } as never)
    await wrapper.find('[aria-label="WW-001 更多操作"]').trigger('click')
    await flushPromises()
    await vi.waitFor(() => expect([...document.querySelectorAll('.el-dropdown-menu__item')].some(item => item.textContent?.includes('撤销并退料'))).toBe(true))
    const revokeItem = [...document.querySelectorAll('.el-dropdown-menu__item')].find(item => item.textContent?.includes('撤销并退料'))
    expect(revokeItem).toBeDefined()
    revokeItem!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushPromises()
    expect(api.fetch).toHaveBeenCalledWith('order-1', true)
    expect(api.revoke).toHaveBeenCalledWith('order-1', '误发退料', expect.any(String), '"fresh"')
    expect(api.remove).not.toHaveBeenCalled()
    expect(api.list).toHaveBeenCalledTimes(2)
  })

  it('直接交接和服务端未开放撤销的单据不能触发删除', async () => {
    const wrapper = await createView()
    await (wrapper.vm as any).removeRow({ ...row, direct_handoff: true })
    await (wrapper.vm as any).removeRow({ ...row, can_revoke_dispatched: false })
    expect(api.fetch).not.toHaveBeenCalled()
    expect(api.remove).not.toHaveBeenCalled()
    expect(api.revoke).not.toHaveBeenCalled()
  })

  it('直接交接单的操作列显示查看详情并可进入详情', async () => {
    const wrapper = await createView({ ...row, direct_handoff: true, can_revoke_dispatched: false })
    await wrapper.find('[aria-label="WW-001 更多操作"]').trigger('click')
    await flushPromises()
    await vi.waitFor(() => expect(document.querySelectorAll('.el-dropdown-menu__item')).toHaveLength(2))
    const menuItems = [...document.querySelectorAll('.el-dropdown-menu__item')]
    expect(menuItems.map(item => item.textContent?.trim())).toEqual(['查看详情', '加工单打印'])
    menuItems[0]!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushPromises()
    expect(api.push).toHaveBeenCalledExactlyOnceWith('/workshop/outsourcing/order-1')
    expect(api.fetch).not.toHaveBeenCalled()
  })
})

describe('统一外发列表及来源入口', () => {
  it('仓库一个状态列表按服务端动作显示办理入口，隐藏页签和创建入口', async () => {
    route.meta = { outsourcingWorkspace: 'warehouse' }
    permissions.superuser = false
    permissions.values = ['outsourcing.confirm_return_outsourcingorder']
    const wrapper = await createView({ ...row, record_type: 'TUBE', warehouse_actions: ['return'] } as typeof row)
    expect(wrapper.find('[role="tablist"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('委外管理')
    expect(wrapper.text()).not.toContain('新建管材外发单')
    expect(wrapper.text()).not.toContain('加工厂管理')
    expect(api.list).toHaveBeenCalledWith(expect.objectContaining({ warehouse_stage: 'all' }))
    expect(api.options).toHaveBeenCalledWith(true)
    const buttons = wrapper.findAll('.el-table__body-wrapper button')
    expect(buttons.some(button => ['发料', '入库', '详情'].includes(button.text()))).toBe(false)
    await wrapper.get('[aria-label="WW-001 更多操作"]').trigger('click')
    await vi.waitFor(() => expect([...document.querySelectorAll('.el-dropdown-menu__item')].some(item => item.textContent?.trim() === '回货入库')).toBe(true))
    const menuItems = [...document.querySelectorAll('.el-dropdown-menu__item')]
    expect(menuItems.filter(item => item.textContent?.trim() === '查看详情')).toHaveLength(1)
    expect(menuItems.some(item => item.textContent?.trim() === '确认外发')).toBe(false)
    menuItems.find(item => item.textContent?.trim() === '回货入库')!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushPromises()
    expect(api.push).toHaveBeenLastCalledWith('/warehouse/outsourcing/tube/order-1/return')
    await (wrapper.vm as any).openWarehouseAction({ ...row, warehouse_actions: [] }, 'dispatch')
    expect(api.push).toHaveBeenCalledTimes(1)
  })

  it.each(['material_issues.create_metalprocessingoriginalhandoff', 'material_issues.confirm_metalprocessingexternalhandoff'])('仅%s权限也能从仓库更多菜单办理外发', async permission => {
    route.meta = { outsourcingWorkspace: 'warehouse' }
    permissions.superuser = false
    permissions.values = [permission]
    const wrapper = await createView({ ...row, record_type: 'REWORK', detail_access: 'METAL', warehouse_actions: ['dispatch'], can_revoke_dispatched: false } as typeof row)
    expect(api.list).toHaveBeenCalledOnce()
    await wrapper.get('[aria-label="WW-001 更多操作"]').trigger('click')
    await vi.waitFor(() => expect([...document.querySelectorAll('.el-dropdown-menu__item')].some(item => item.textContent?.trim() === '确认外发')).toBe(true))
    document.querySelectorAll('.el-dropdown-menu__item').forEach(item => {
      if (item.textContent?.trim() === '确认外发') item.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    await flushPromises()
    expect(api.push).toHaveBeenLastCalledWith('/warehouse/outsourcing/rework/order-1?action=dispatch')
  })

  it('仓库发料及普通回货按钮进入相应办理表单，原车间列表隐藏退料', async () => {
    route.meta = { outsourcingWorkspace: 'warehouse' }
    const wrapper = await createView()
    const vm = wrapper.vm as any
    vm.openWarehouseAction({ ...row, warehouse_actions: ['dispatch'] }, 'dispatch')
    expect(api.push).toHaveBeenLastCalledWith('/warehouse/outsourcing/order-1?action=dispatch')
    vm.openWarehouseAction({ ...row, detail_access: 'METAL', warehouse_actions: ['return'] }, 'return')
    expect(api.push).toHaveBeenLastCalledWith('/warehouse/outsourcing/order-1?view=metal&action=return')
    route.meta = {}
    await flushPromises()
    expect(vm.canRemoveRow(row)).toBe(false)
    expect(vm.canRemoveRow({ ...row, can_delete: true })).toBe(true)
    vm.openWarehouseAction({ ...row, warehouse_actions: ['dispatch'] }, 'dispatch')
    expect(api.push).toHaveBeenCalledTimes(2)
  })
  it('外发单页只保留管材和裁片新建，并跳转对应专用表单', async () => {
    const wrapper = await createView()
    const buttons = wrapper.findAll('.heading-actions button')
    expect(buttons.some(button => button.text() === '新建外发单')).toBe(false)
    await buttons.find(button => button.text() === '新建管材外发单')!.trigger('click')
    expect(api.push).toHaveBeenLastCalledWith('/workshop/outsourcing/tube/new')
    await buttons.find(button => button.text() === '新建裁片外发单')!.trigger('click')
    expect(api.push).toHaveBeenLastCalledWith('/workshop/outsourcing/tube/new?category=cutting')
  })

  it('管材单通过更多菜单分别打印，打开指定模板不触发行跳转', async () => {
    const wrapper = await createView({ ...row, record_type: 'TUBE', source_kind: 'TUBE_METAL', detail_access: 'TUBE' })
    const vm = wrapper.vm as any
    expect(wrapper.find('[aria-label="WW-001 加工单打印"]').exists()).toBe(false)
    await wrapper.get('[aria-label="WW-001 更多操作"]').trigger('click')
    await vi.waitFor(() => expect(document.querySelector('[aria-label="WW-001 加工单打印"]')).not.toBeNull())
    document.querySelector('[aria-label="WW-001 加工单打印"]')!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushPromises()
    expect(vm.printRequest.kind).toBe('processing')
    expect(vm.printRequest.row.id).toBe(row.id)
    expect(api.push).not.toHaveBeenCalled()
    vm.printRequest = null
    await flushPromises()
    await wrapper.get('[aria-label="WW-001 更多操作"]').trigger('click')
    await vi.waitFor(() => expect(document.querySelector('[aria-label="WW-001 管材喷塑打印"]')).not.toBeNull())
    document.querySelector('[aria-label="WW-001 管材喷塑打印"]')!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushPromises()
    expect(vm.printRequest.kind).toBe('spray')
    expect(api.push).not.toHaveBeenCalled()
  })

  it('裁片和普通单只提供加工单打印，金工投影和重加工不调用不相容接口', async () => {
    const wrapper = await createView({ ...row, record_type: 'TUBE', source_kind: 'SEWING', detail_access: 'TUBE', craft: { name: '丝印' } })
    await wrapper.get('[aria-label="WW-001 更多操作"]').trigger('click')
    await vi.waitFor(() => expect(document.querySelector('[aria-label="WW-001 加工单打印"]')).not.toBeNull())
    expect(document.querySelector('[aria-label="WW-001 管材喷塑打印"]')).toBeNull()
    const vm = wrapper.vm as any
    vm.openPrint({ ...row, record_type: 'TUBE', source_kind: 'SEWING' }, 'spray')
    vm.openPrint({ ...row, record_type: 'REWORK' }, 'processing')
    vm.openPrint({ ...row, detail_access: 'METAL' }, 'processing')
    expect(vm.printRequest).toBeNull()
  })

  it('直接进入待外发材料不读取隐藏列表或筛选项，保留管材和裁片新建入口', async () => {
    route.query = { tab: 'sources' }
    const wrapper = await createView()
    expect(wrapper.find('[data-testid="sources-workspace"]').exists()).toBe(true)
    expect(api.list).not.toHaveBeenCalled()
    expect(api.options).not.toHaveBeenCalled()
    const button = (label: string) => wrapper.findAll('.heading-actions button').find(item => item.text() === label)!
    await button('新建管材外发单').trigger('click')
    expect(api.push).toHaveBeenLastCalledWith('/workshop/outsourcing/tube/new')
    await button('新建裁片外发单').trigger('click')
    expect(api.push).toHaveBeenLastCalledWith('/workshop/outsourcing/tube/new?category=cutting')
    expect(wrapper.findAll('.heading-actions button').some(item => item.text() === '新建外发单')).toBe(false)
    expect(api.list).not.toHaveBeenCalled()
    expect(api.options).not.toHaveBeenCalled()
  })

  it('来源操作更新不读取隐藏外发单，切回外发单重新读取最新列表及筛选项', async () => {
    route.query = { tab: 'sources', issue_id: 'issue-1' }
    api.replace.mockImplementation((target: { query: Record<string, string> }) => { route.query = target.query; return Promise.resolve() })
    const wrapper = await createView()
    wrapper.findComponent({ name: 'MetalProcessingP4View' }).vm.$emit('updated')
    await flushPromises()
    expect(api.list).not.toHaveBeenCalled()
    expect(api.options).not.toHaveBeenCalled()
    await wrapper.get('#outsourcing-orders-tab').trigger('click')
    await flushPromises()
    expect(api.replace).toHaveBeenLastCalledWith({ path: '/workshop/outsourcing', query: { issue_id: 'issue-1' } })
    expect(api.list).toHaveBeenCalledTimes(1)
    expect(api.options).toHaveBeenCalledTimes(1)
    expect(wrapper.find('.el-table__body').text()).toContain('HT-001')
    await wrapper.get('#outsourcing-sources-tab').trigger('click')
    await flushPromises()
    wrapper.findComponent({ name: 'MetalProcessingP4View' }).vm.$emit('updated')
    await flushPromises()
    expect(api.list).toHaveBeenCalledTimes(1)
    expect(api.options).toHaveBeenCalledTimes(1)
    const latestOptions = { statuses: [{ value: 'COMPLETED', label: '已完成' }], crafts: [], factories: [{ id: 'factory-new', name: '新加工厂' }] }
    api.list.mockResolvedValueOnce({ data: [{ ...row, id: 'order-new', row_key: 'ORIGINAL:order-new', order_number: 'WW-NEW', production_task_number: 'HT-NEW' }], meta: { total: 1 } })
    api.options.mockResolvedValueOnce(latestOptions)
    await wrapper.get('#outsourcing-orders-tab').trigger('click')
    await flushPromises()
    expect(api.list).toHaveBeenCalledTimes(2)
    expect(api.options).toHaveBeenCalledTimes(2)
    expect(wrapper.find('.el-table__body').text()).toContain('HT-NEW')
    expect(wrapper.find('.el-table__body').text()).not.toContain('HT-001')
    expect((wrapper.vm as any).options).toEqual(latestOptions)
  })

  it('产品材质替代品号，保留缺值和多款边界', async () => {
    const wrapper = await createView()
    const headers = wrapper.findAll('.el-table__header th').map(cell => cell.text())
    expect(headers).toContain('产品材质')
    expect(headers).not.toContain('品号')
    expect(wrapper.find('.el-table__body .outsourcing-product-material').text()).toBe('PE')
    expect(wrapper.text()).not.toContain('PRODUCT-001')
    for (const [product, productCount, expected] of [[{ product_name: '折叠椅', material: '' }, 1, '—'], [{ product_name: '折叠椅' }, 1, '—'], [{ material: 'PE' }, 2, '多款']] as const) {
      api.list.mockResolvedValue({ data: [{ ...row, product, product_count: productCount }], meta: { total: 1 } })
      await (wrapper.vm as any).load(); await flushPromises()
      expect(wrapper.find('.el-table__body .outsourcing-product-material').text()).toBe(expected)
    }
  })
  it.each(['ORIGINAL', 'TUBE', 'REWORK'])('%s显示真实计划金额，去尾零，缺价与0区分', async recordType => {
    const wrapper = await createView({ ...row, record_type: recordType, planned_amount: '12.5000' })
    expect(wrapper.find('.el-table__body .outsourcing-planned-amount').text()).toBe('12.5')
    api.list.mockResolvedValue({ data: [{ ...row, record_type: recordType, planned_amount: null }], meta: { total: 1 } })
    await (wrapper.vm as any).load(); await flushPromises()
    expect(wrapper.find('.el-table__body .outsourcing-planned-amount').text()).toBe('未录入')
    api.list.mockResolvedValue({ data: [{ ...row, record_type: recordType, planned_amount: '0.00' }], meta: { total: 1 } })
    await (wrapper.vm as any).load(); await flushPromises()
    expect(wrapper.find('.el-table__body .outsourcing-planned-amount').text()).toBe('0')
  })
  it('仅金工详情投影的金额保留不可见状态，不把null显示成0', async () => {
    const wrapper = await createView({ ...row, detail_access: 'METAL', planned_amount: null })
    expect(wrapper.find('.el-table__body .outsourcing-planned-amount').text()).toBe('—')
  })
  it('发出米数与回货套数分别显示，不计算跨单位进度', async () => {
    const wrapper = await createView()
    expect(wrapper.text()).toContain('生产任务单')
    expect(wrapper.text()).toContain('HT-001')
    expect(wrapper.text()).not.toContain('PLAN-001')
    expect(wrapper.find('.table-product .line-art-thumb').exists()).toBe(false)
    expect(wrapper.find('.table-product small').exists()).toBe(false)
    expect(wrapper.text()).toContain('183.75 米')
    expect(wrapper.text()).toContain('120 套')
    expect(wrapper.find('.return-progress').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('管材外发闭环')
    expect(wrapper.text()).toContain('材料来源')
  })

  it('重加工进入独立详情，金工可见投影进入金工原单详情，均禁止普通删除', async () => {
    const wrapper = await createView({ ...row, record_type: 'REWORK', source_kind: 'REWORK', source_label: '重加工件' })
    const vm = wrapper.vm as any
    vm.openDetail({ ...row, record_type: 'REWORK' })
    expect(api.push).toHaveBeenLastCalledWith('/workshop/outsourcing/rework/order-1')
    vm.openDetail({ ...row, detail_access: 'METAL' })
    expect(api.push).toHaveBeenLastCalledWith('/workshop/outsourcing/order-1?view=metal')
    await vm.removeRow({ ...row, record_type: 'REWORK' })
    await vm.removeRow({ ...row, detail_access: 'METAL' })
    expect(api.fetch).not.toHaveBeenCalled()
  })

  it('来源筛选与页码交给统一接口，每次筛选重置页码', async () => {
    const wrapper = await createView()
    const vm = wrapper.vm as any
    vm.page = 3; vm.sourceKind = 'REWORK'; vm.search = ' WF-001 '
    vm.applyFilters()
    await flushPromises()
    expect(api.list).toHaveBeenLastCalledWith(expect.objectContaining({ page: 1, page_size: 50, source_group: 'REWORK', search: 'WF-001' }))
  })

  it('只有金工查看权限只保留来源tab，不加载普通外发列表；不出现普通新建和加工厂管理', async () => {
    permissions.superuser = false
    permissions.values = ['material_issues.view_metalprocessingsource']
    const wrapper = await createView()
    expect(api.list).not.toHaveBeenCalled()
    expect(api.options).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('待外发材料')
    expect(wrapper.text()).not.toContain('新建外发单')
    expect(wrapper.find('[to="/workshop/outsourcing/factories"]').exists()).toBe(false)
    route.query = { tab: 'sources', issue_id: 'issue-1' }
    await flushPromises()
    expect(wrapper.find('[data-testid="sources-workspace"]').exists()).toBe(true)
    wrapper.findComponent({ name: 'MetalProcessingP4View' }).vm.$emit('updated')
    await flushPromises()
    expect(api.list).not.toHaveBeenCalled()
    expect(api.options).not.toHaveBeenCalled()
  })

  it('只有普通权限不显示来源区，无查看权限不请求列表或options', async () => {
    permissions.superuser = false
    permissions.values = ['outsourcing.view_outsourcingorder']
    let wrapper = await createView()
    expect(wrapper.text()).not.toContain('待外发材料')
    expect(wrapper.text()).not.toContain('新建管材外发单')
    expect(wrapper.text()).not.toContain('新建裁片外发单')
    wrapper.unmount()
    api.list.mockClear(); api.options.mockClear()
    permissions.values = []
    wrapper = await createView()
    expect(wrapper.text()).toContain('暂无委外加工查看权限')
    expect(api.list).not.toHaveBeenCalled()
    expect(api.options).not.toHaveBeenCalled()
  })

  it('接口失败清除旧行并可重试，旧请求晚返回不会覆盖最新筛选', async () => {
    const wrapper = await createView()
    const vm = wrapper.vm as any
    let finishOld!: (value: unknown) => void
    api.list.mockReturnValueOnce(new Promise(resolve => { finishOld = resolve }))
    const old = vm.load()
    api.list.mockResolvedValueOnce({ data: [{ ...row, id: 'new-order' }], meta: { total: 1 } })
    await vm.load()
    finishOld({ data: [row], meta: { total: 1 } }); await old
    expect(vm.rows[0].id).toBe('new-order')
    api.list.mockRejectedValueOnce(new Error('offline'))
    await vm.load()
    expect(vm.rows).toEqual([])
    expect(wrapper.text()).toContain('外发单列表加载失败')
    api.list.mockResolvedValueOnce({ data: [row], meta: { total: 1 } })
    await vm.load()
    expect(vm.rows[0].id).toBe(row.id)
  })

  it('空列表保留筛选及两种专用新建入口并展示真实零总数', async () => {
    const wrapper = await createView()
    api.list.mockResolvedValueOnce({ data: [], meta: { total: 0 } })
    await (wrapper.vm as any).load()
    expect(wrapper.text()).toContain('暂无外发单')
    expect(wrapper.text()).toContain('共 0 条')
    expect(wrapper.text()).toContain('新建管材外发单')
    expect(wrapper.text()).toContain('新建裁片外发单')
    expect(wrapper.text()).not.toContain('新建外发单')
  })

})
