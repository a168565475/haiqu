import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElMessageBox } from 'element-plus'
import { AxiosError } from 'axios'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import FinishedReceiptRecordsPanel from './FinishedReceiptRecordsPanel.vue'

const api = vi.hoisted(() => ({ records: vi.fn(), detail: vi.fn(), options: vi.fn(), placements: vi.fn(), confirm: vi.fn(), remove: vi.fn() }))
const permissions = vi.hoisted(() => new Set<string>())
vi.mock('vue-router', () => ({ useRoute: () => ({ query: {} }), useRouter: () => ({ replace: vi.fn() }) }))
vi.mock('@/api/finishedReceipts', () => ({ fetchFinishedRecords: api.records, fetchFinishedRecord: api.detail, confirmAssemblyReceiptRecord: api.confirm, deleteAssemblyReceiptRecord: api.remove }))
vi.mock('@/api/inventory', () => ({ fetchFinishedGoodsFilterOptions: api.options, fetchInventoryOptions: api.placements }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ user: { is_superuser: false }, hasPermission: (permission: string) => permissions.has(permission) }) }))
vi.mock('@/directives/horizontalOverflow', () => ({ vHorizontalOverflow: {} }))
const wrappers: ReturnType<typeof mount>[] = []
beforeEach(() => {
  vi.resetAllMocks()
  permissions.clear(); permissions.add('inventory.confirm_finishedgoodsreceipt')
  vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue('confirm' as Awaited<ReturnType<typeof ElMessageBox.confirm>>)
  api.records.mockResolvedValue({ items: [], total: 0 })
  api.options.mockResolvedValue({ warehouses: [], zones: [] })
  api.confirm.mockResolvedValue({ id: 'receipt-1', receipt_number: 'CPRK-001', status: 'CONFIRMED', replayed: false })
})
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()); vi.restoreAllMocks() })

describe('成品入库记录排除样品', () => {
  it('车间入口仅查询装配入库，保留查看并隐藏仓库操作', async () => {
    api.records.mockResolvedValue({ items: [{
      id: 'receipt-1', receipt_number: 'CPRK-001', source_type: 'ASSEMBLY', status: 'PENDING',
      can_delete: true, received_quantity: 3, unit_name: '套', task_number_snapshot: 'HT-001',
    }], total: 1 })
    const wrapper = mount(FinishedReceiptRecordsPanel, {
      props: { readOnly: true }, global: { plugins: [ElementPlus] },
    })
    wrappers.push(wrapper)
    await flushPromises()
    expect(wrapper.get('h1').text()).toBe('成品入库记录')
    expect(wrapper.get('tbody').text()).toContain('查看')
    expect(wrapper.find('[data-testid="confirm-finished-receipt"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="delete-finished-receipt"]').exists()).toBe(false)
    expect(api.records).toHaveBeenCalledWith(expect.objectContaining({ source: 'ASSEMBLY' }))
    expect(api.options).not.toHaveBeenCalled()
  })

  it('首次读取和筛选重置都排除样品', async () => {
    const wrapper = mount(FinishedReceiptRecordsPanel, { global: { plugins: [ElementPlus] } })
    wrappers.push(wrapper)
    await flushPromises()
    expect(api.records).toHaveBeenLastCalledWith(expect.objectContaining({ exclude_sample: true, source: '' }))
    const vm = wrapper.vm as any
    vm.source = 'ASSEMBLY'
    vm.search()
    await flushPromises()
    expect(api.records).toHaveBeenLastCalledWith(expect.objectContaining({ exclude_sample: true, source: 'ASSEMBLY' }))
    await wrapper.findAll('button').find(button => button.text() === '重置')!.trigger('click')
    await flushPromises()
    expect(api.records).toHaveBeenLastCalledWith(expect.objectContaining({ exclude_sample: true, source: '' }))
  })
})

describe('成品入库详情数量单位', () => {
  it.each(['张', '个'])('使用记录的%s单位区分数量、整箱和箱位', async unit => {
    api.detail.mockResolvedValue({
      id: 'receipt-1', receipt_number: 'CPRK-1', source_type: 'PRODUCTION_ORDER', task_number_snapshot: 'SC-1',
      unit_name: unit, received_quantity: 2001, quantity_per_box: 4,
      box_count: 500, tail_quantity: 1, occupied_box_slots: 501,
      received_before: 0, received_after: 2001, maximum_receivable: 2100,
    })
    const wrapper = mount(FinishedReceiptRecordsPanel, { global: {
      plugins: [ElementPlus], stubs: { AppWindowDialog: { template: '<div><slot /></div>' } },
    } })
    wrappers.push(wrapper)
    await (wrapper.vm as any).show('receipt-1')
    await flushPromises()
    expect(wrapper.get('.fg-detail-title b').text()).toBe('SC-1')
    expect(wrapper.get('.fg-detail-fields dt').text()).toBe('入库单号')
    expect(wrapper.get('.fg-detail-fields dd').text()).toBe('CPRK-1')
    const summary = wrapper.get('.fg-detail-summary').text()
    expect(summary).toContain(`每箱数量：4 ${unit}/箱`)
    expect(summary).toContain('整箱数：500 箱')
    expect(summary).toContain(`尾数：1 ${unit}`)
    expect(summary).toContain('占用箱位：501 箱位')
    expect(wrapper.get('.fg-helper').text()).toContain(`本单入库前 0 ${unit}，本次 2001 ${unit}`)
  })

  it('没有包装信息时保持未计算', async () => {
    api.detail.mockResolvedValue({
      id: 'receipt-1', source_type: 'PRODUCTION_ORDER', unit_name: '张',
      quantity_per_box: null, box_count: null, tail_quantity: null, occupied_box_slots: null,
    })
    const wrapper = mount(FinishedReceiptRecordsPanel, { global: {
      plugins: [ElementPlus], stubs: { AppWindowDialog: { template: '<div><slot /></div>' } },
    } })
    wrappers.push(wrapper)
    await (wrapper.vm as any).show('receipt-1')
    await flushPromises()
    expect(wrapper.get('.fg-detail-summary').findAll('span').map(span => span.text())).toEqual([
      '每箱数量：未计算', '整箱数：未计算', '尾数：未计算', '占用箱位：未计算',
    ])
  })
})

describe('成品待入库确认', () => {
  it.each([false, true])('打开待入库单后分配位置并确认（已有库位 %s）', async existing => {
    api.records.mockResolvedValueOnce({ items: [{ id: 'receipt-1', receipt_number: 'CPRK-001', source_type: 'ASSEMBLY', source_type_display: '装配入库', received_quantity: 30, unit_name: '件', status: 'PENDING', task_number_snapshot: 'SC-1', item_number_snapshot: 'P-1', product_code_snapshot: 'PC-1', product_name_snapshot: '产品', specification_snapshot: '', actual_color: '', warehouse_id: existing ? 'warehouse' : null, zone_id: existing ? 'zone' : null, location_id: existing ? 'location' : null, location_number: existing ? 'A-01' : null, receipt_date: '2026-10-22', etag: '"v1"' }], total: 1 })
    api.placements.mockResolvedValue({
      warehouses: [{ id: 'warehouse', warehouse_name: '成品仓', warehouse_type: 'FINISHED', status: 'ACTIVE' }],
      zones: [{ id: 'zone', warehouse: 'warehouse', zone_name: 'A区', status: 'ACTIVE' }],
      locations: [{ id: 'location', warehouse_id: 'warehouse', zone: 'zone', location_number: 'A-01', status: 'ACTIVE' }],
    })
    const wrapper = mount(FinishedReceiptRecordsPanel, { global: { plugins: [ElementPlus],
      stubs: { AppWindowDialog: { template: '<div v-if="modelValue"><slot /><slot name="footer" /></div>', props: ['modelValue'] } },
    } })
    wrappers.push(wrapper)
    await flushPromises()
    expect(wrapper.text()).toContain('待入库')
    expect(wrapper.findAll('thead th').slice(0, 3).map(cell => cell.text())).toEqual(['生产任务单号', '入库单号', '入库来源'])
    expect(wrapper.get('tbody td:first-child strong').text()).toBe('SC-1')
    expect(wrapper.get('tbody td:nth-child(2)').text()).toBe('CPRK-001')
    await wrapper.get('[data-testid="confirm-finished-receipt"]').trigger('click')
    await flushPromises()
    expect(api.confirm).not.toHaveBeenCalled()
    expect(wrapper.get('.fg-placement-facts').text()).toContain('30 件')
    const selects = wrapper.findAllComponents({ name: 'ElSelect' }).slice(-3)
    expect(selects.map(select => select.props('modelValue'))).toEqual(existing ? ['warehouse', 'zone', 'location'] : ['', '', ''])
    if (!existing) {
      for (const [index, value] of ['warehouse', 'zone', 'location'].entries()) {
        selects[index]!.vm.$emit('update:modelValue', value)
        await flushPromises()
      }
    }
    await wrapper.get('[aria-label="每箱数量"]').setValue('10')
    await wrapper.findAll('button').filter(button => button.text() === '确认入库').at(-1)!.trigger('click')
    await flushPromises()
    expect(api.confirm).toHaveBeenCalledExactlyOnceWith('receipt-1', { location_id: 'location', quantity_per_box: 10 }, '"v1"')
  })
})

describe('成品待入库删除', () => {
  const pending = { id: 'receipt-1', receipt_number: 'CPRK-001', source_type: 'ASSEMBLY', source_type_display: '装配入库', received_quantity: 10, unit_name: '件', status: 'PENDING', product_name_snapshot: '产品', can_delete: true, etag: '"v1"' }
  it('普通仓管只有查看与删除权限也可读取记录并操作删除，不依赖计划或新增权限', async () => {
    permissions.clear(); permissions.add('inventory.view_finishedgoodsreceipt'); permissions.add('inventory.delete_finishedgoodsreceipt')
    api.records.mockResolvedValue({ items: [pending], total: 1 })
    const wrapper = mount(FinishedReceiptRecordsPanel, { global: { plugins: [ElementPlus] } })
    wrappers.push(wrapper); await flushPromises()
    expect(api.records).toHaveBeenCalledOnce()
    expect(wrapper.find('[data-testid="delete-finished-receipt"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="confirm-finished-receipt"]').exists()).toBe(false)
  })
  it('只有后台授权的待入库记录显示删除，已入库不显示', async () => {
    api.records.mockResolvedValue({ items: [pending, { ...pending, id: 'forbidden', can_delete: false }, { ...pending, id: 'confirmed', status: 'CONFIRMED' }], total: 3 })
    const wrapper = mount(FinishedReceiptRecordsPanel, { global: { plugins: [ElementPlus] } })
    wrappers.push(wrapper); await flushPromises()
    expect(wrapper.findAll('[data-testid="delete-finished-receipt"]')).toHaveLength(1)
  })
  it('确认删除后携带记录版本并重新读取记录', async () => {
    api.records.mockResolvedValueOnce({ items: [pending], total: 1 })
    api.remove.mockResolvedValue(undefined)
    const wrapper = mount(FinishedReceiptRecordsPanel, { global: { plugins: [ElementPlus] } })
    wrappers.push(wrapper); await flushPromises()
    await wrapper.get('[data-testid="delete-finished-receipt"]').trigger('click'); await flushPromises()
    expect(ElMessageBox.confirm).toHaveBeenCalledWith(expect.stringContaining('CPRK-001'), '删除待入库记录', expect.any(Object))
    expect(api.remove).toHaveBeenCalledWith('receipt-1', '"v1"')
    expect(api.records).toHaveBeenCalledTimes(2)
    expect(wrapper.find('[data-testid="delete-finished-receipt"]').exists()).toBe(false)
  })
  it('取消删除时不发删除请求', async () => {
    api.records.mockResolvedValue({ items: [pending], total: 1 })
    vi.mocked(ElMessageBox.confirm).mockRejectedValue('cancel')
    const wrapper = mount(FinishedReceiptRecordsPanel, { global: { plugins: [ElementPlus] } })
    wrappers.push(wrapper); await flushPromises()
    await wrapper.get('[data-testid="delete-finished-receipt"]').trigger('click'); await flushPromises()
    expect(api.remove).not.toHaveBeenCalled()
    expect(api.records).toHaveBeenCalledTimes(1)
  })
  it.each([404, 409, 412])('删除遇到%s保留后端错误并刷新记录', async status => {
    api.records.mockResolvedValueOnce({ items: [pending], total: 1 }).mockResolvedValue({ items: [{ ...pending, status: 'CONFIRMED', can_delete: false }], total: 1 })
    const failure = new AxiosError('conflict')
    failure.response = { status, data: { error: { message: '记录已被确认，不能删除。' } } } as never
    api.remove.mockRejectedValue(failure)
    const wrapper = mount(FinishedReceiptRecordsPanel, { global: { plugins: [ElementPlus] } })
    wrappers.push(wrapper); await flushPromises()
    await wrapper.get('[data-testid="delete-finished-receipt"]').trigger('click'); await flushPromises()
    expect(api.records).toHaveBeenCalledTimes(2)
    expect(wrapper.text()).toContain('记录已被确认，不能删除。')
    expect(wrapper.find('[data-testid="delete-finished-receipt"]').exists()).toBe(false)
  })
})
