import { flushPromises, shallowMount } from '@vue/test-utils'
import ElementPlus, { ElButton, ElMessageBox, ElOption, ElSelect } from 'element-plus'
import { AxiosError } from 'axios'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '@/api/internalReceipts'
import type { SemiReceiptRecord } from '@/types/internalReceipt'
import SemiReceiptRecordsView from './SemiReceiptRecordsView.vue'

const route = vi.hoisted(() => ({ name: 'semi-receipt-records', query: {} }))
vi.mock('vue-router', () => ({ useRoute: () => route, useRouter: () => ({ push: vi.fn() }) }))
const confirm = vi.hoisted(() => vi.fn())
const permissions = vi.hoisted(() => new Set<string>())
vi.mock('@/api/internalReceipts', () => ({ fetchSemiReceiptRecords: vi.fn(), fetchSemiReceiptRecord: vi.fn(), confirmInternalReceiptRecord: confirm, deleteInternalReceiptRecord: vi.fn() }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ user: { is_superuser: false }, hasPermission: (permission: string) => permissions.has(permission) }) }))
vi.mock('@/directives/glassSpotlight', () => ({ vGlassSpotlight: {} }))
vi.mock('@/directives/horizontalOverflow', () => ({ vHorizontalOverflow: {} }))

const record: SemiReceiptRecord = {
  id: 'record-1', receipt_number: 'RK-001', source: 'INTERNAL', source_display: '厂内车缝',
  production_order: 'HT-001', product: '折叠椅', stage: '车缝完成', quantity: '20', unit: '套',
  receipt_date: '2026-10-20', status: 'CONFIRMED', warehouse: '半成品仓', zone: '一楼', actor: '仓管员', remark: '',
  attributes: { part_name: '椅套', category: '裁片', material: '涤纶', specification: '600D', color: '黑色', unit_name: '套' },
  source_detail: { required: '100', received_before: '10', received_after: '30', input_quantity: null, input_unit: '米' },
}

beforeEach(() => {
  vi.resetAllMocks()
  route.name = 'semi-receipt-records'
  permissions.clear(); permissions.add('inventory.confirm_internalsemifinishedreceipt')
  vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue('confirm' as Awaited<ReturnType<typeof ElMessageBox.confirm>>)
  vi.mocked(api.fetchSemiReceiptRecords).mockResolvedValue({ items: [record], total: 1 })
})
afterEach(() => vi.restoreAllMocks())

function mountRecords(readOnly = false) {
  return shallowMount(SemiReceiptRecordsView, {
    props: { readOnly },
    global: {
      plugins: [ElementPlus],
      renderStubDefaultSlot: true,
      stubs: {
        ElDropdown: { template: '<div><slot/><slot name="dropdown"/></div>' },
        AppWindowDialog: { props: ['modelValue'], template: '<section v-if="modelValue" role="dialog"><slot/><slot name="footer"/></section>' },
      },
    },
  })
}

it('车间入口以厂内入库记录为来源，只显示查看操作', async () => {
  vi.mocked(api.fetchSemiReceiptRecords).mockResolvedValue({
    items: [{ ...record, status: 'PENDING', can_delete: true }], total: 1,
  })
  const wrapper = mountRecords(true)
  try {
    await flushPromises()
    expect(wrapper.get('h1').text()).toBe('半成品入库记录')
    expect(wrapper.get('tbody').text()).toContain('查看')
    expect(wrapper.find('[data-testid="confirm-semi-receipt"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="delete-semi-receipt"]').exists()).toBe(false)
    expect(api.fetchSemiReceiptRecords).toHaveBeenCalledWith(expect.objectContaining({ direction: 'IN', source: 'INTERNAL' }))
  } finally { wrapper.unmount() }
})

it('车间入库显示原提交人，隐藏标注的列、头部附加项和底栏', async () => {
  vi.mocked(api.fetchSemiReceiptRecords).mockResolvedValue({ items: [{ ...record, submitted_by: '车间提交人' }, { ...record, id: 'legacy' }], total: 2 })
  const wrapper = mountRecords()
  try {
    await flushPromises()
    const headers = wrapper.findAll('thead th').map(cell => cell.text())
    expect(headers.slice(0, 3)).toEqual(['生产任务单号', '入库单号', '入库来源'])
    expect(wrapper.get('tbody td:first-child strong').text()).toBe('HT-001')
    expect(headers).toContain('提交人')
    expect(headers).not.toContain('部位')
    expect(headers).not.toContain('厚度')
    const submitterIndex = headers.indexOf('提交人')
    expect(wrapper.findAll('tbody tr').map(row => row.findAll('td')[submitterIndex]?.text())).toEqual(['车间提交人', '—'])
    expect(wrapper.get('header').text()).toBe('车间入库')
    expect(wrapper.find('footer').exists()).toBe(false)
    expect(wrapper.find('.receipt-page-controls').exists()).toBe(false)
    expect(wrapper.get('tbody .scroll-actions-cell').text()).toContain('更多')
  } finally { wrapper.unmount() }
})

it('车间入库超过一页时可从筛选区翻到第二页', async () => {
  vi.mocked(api.fetchSemiReceiptRecords).mockResolvedValue({ items: [record], total: 21 })
  const wrapper = mountRecords()
  try {
    await flushPromises()
    const pagination = wrapper.getComponent({ name: 'ElPagination' })
    expect(wrapper.get('.erp-list-filter').find('.receipt-page-controls').exists()).toBe(true)
    pagination.vm.$emit('update:current-page', 2)
    pagination.vm.$emit('current-change', 2)
    await flushPromises()
    expect(api.fetchSemiReceiptRecords).toHaveBeenLastCalledWith(expect.objectContaining({ page: 2, page_size: 20 }))
    expect(wrapper.find('footer').exists()).toBe(false)
  } finally { wrapper.unmount() }
})

it('半成品出库沿用原列表与独立查看入口', async () => {
  route.name = 'semi-outbound-records'
  vi.mocked(api.fetchSemiReceiptRecord).mockResolvedValue(record)
  const wrapper = mountRecords()
  try {
    await flushPromises()
    expect(wrapper.get('h1').text()).toBe('半成品出库记录')
    expect(wrapper.findAll('thead th').slice(0, 3).map(cell => cell.text())).toEqual(['生产任务单号', '出库单号', '出库来源'])
    expect(wrapper.findAll('thead th').map(cell => cell.text())).toEqual(expect.arrayContaining(['部位', '厚度']))
    expect(wrapper.get('tbody .receipt-link').text()).toBe('查看')
    expect(wrapper.find('footer').exists()).toBe(true)
    await wrapper.get('tbody .receipt-link').trigger('click')
    await flushPromises()
    expect(wrapper.get('[role="dialog"]').attributes('width')).toBe('1180')
    expect(wrapper.get('.receipt-detail-title h2').text()).toBe('HT-001')
    expect(wrapper.get('.receipt-detail-grid label').text()).toBe('出库单号RK-001')
  } finally { wrapper.unmount() }
})

it('待确认多部位单按单位汇总，并逐行展示各部位而非只展示首行', async () => {
  const pending: SemiReceiptRecord = { ...record, status: 'PENDING', quantity: '', unit: '',
    quantity_totals: [{ quantity: '2', unit: '个' }, { quantity: '3', unit: '件' }], lines: [
      { id: 'p1', bom_line_id: 'b1', quantity: '2', unit: '个', stage: '车缝完成', attributes: { ...record.attributes, part_name: '床面' } },
      { id: 'p2', bom_line_id: 'b2', quantity: '3', unit: '件', stage: '车缝完成', attributes: { ...record.attributes, part_name: '外袋' } },
    ] }
  vi.mocked(api.fetchSemiReceiptRecords).mockResolvedValue({ items: [pending], total: 1 })
  vi.mocked(api.fetchSemiReceiptRecord).mockResolvedValue(pending)
  const wrapper = mountRecords()
  try {
    await flushPromises()
    expect(wrapper.text()).toContain('2 个、3 件')
    await wrapper.get('[data-testid="view-semi-receipt"]').trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('床面'); expect(wrapper.text()).toContain('外袋')
    expect(wrapper.text()).not.toContain('部位入库进度')
  } finally { wrapper.unmount() }
})

it('委外总单入库按本次实收展示支或套，不推算批次少回', async () => {
  const detail: SemiReceiptRecord = { ...record, source: 'EXTERNAL', source_detail: { source_type: 'TUBE_OUTSOURCING_RETURN', is_plan: true, source_number: 'WF-总单', receipt_number: 'RK-批次', received_quantity: '200', output_unit: '套' } }
  vi.mocked(api.fetchSemiReceiptRecord).mockResolvedValue(detail)
  const wrapper = mountRecords()
  try {
    await flushPromises(); await wrapper.get('[data-testid="view-semi-receipt"]').trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('委外总单入库')
    expect(wrapper.text()).toContain('WF-总单')
    expect(wrapper.text()).toContain('本次实收200 套')
    expect(wrapper.text()).not.toContain('少回支数')
    expect(wrapper.text()).not.toContain('实发支数')
  } finally { wrapper.unmount() }
})

it.each(['SEWING', 'PUBLIC_CUTTING'])('非总单裁片回货 %s 沿保存单位展示数量', async sourceKind => {
  const detail: SemiReceiptRecord = { ...record, source: 'EXTERNAL', unit: sourceKind === 'SEWING' ? '支' : '套', source_detail: {
    source_type: 'TUBE_OUTSOURCING_RETURN', is_plan: false, source_kind_label: sourceKind,
    dispatched_quantity: '120', received_quantity: '100', shortage_quantity: '20', output_unit: sourceKind === 'SEWING' ? '套' : undefined,
  } }
  vi.mocked(api.fetchSemiReceiptRecord).mockResolvedValue(detail)
  const wrapper = mountRecords()
  try {
    await flushPromises(); await wrapper.get('[data-testid="view-semi-receipt"]').trigger('click'); await flushPromises()
    const summary = wrapper.get('.receipt-detail-progress').text()
    expect(summary).toContain('实发数量120 套')
    expect(summary).toContain('实收数量100 套')
    expect(summary).toContain('少回数量20 套')
    expect(summary).not.toContain('支')
  } finally { wrapper.unmount() }
})

it('已入库详情按单据的实际属性分列，数量取每条明细', async () => {
  const detail: SemiReceiptRecord = { ...record, lines: [
    { id: 'metal', unit: '支', quantity: '40000', stage: '金工完成',
      attributes: { part_name: '上下管', category: '管材类', material: '铁', color: '', unit_name: '支',
        tube_shape: '圆管', tube_diameter: '17', tube_thickness: '1.5', cutting_length_mm: 530 },
      progress: { required: '50000', received_before: '3000', received_after: '43000', input_quantity: '40000', input_unit: '支' } },
    { id: 'cut', unit: '片', quantity: '20000', stage: '裁剪完成',
      attributes: { ...record.attributes, part_name: '左扶手裁片', specification: '52*52*92', component_attributes: { specification: '60*60*107' } } },
  ] }
  vi.mocked(api.fetchSemiReceiptRecord).mockResolvedValue(detail)
  const wrapper = mountRecords()
  try {
    await flushPromises()
    await wrapper.get('[data-testid="view-semi-receipt"]').trigger('click')
    await flushPromises()
    const dialog = wrapper.get('[role="dialog"]')
    const headers = dialog.findAll('th').map(cell => cell.text())
    const lines = dialog.findAll('tbody tr').map(row => row.findAll('td').map(cell => cell.text()))
    expect(headers).toEqual(expect.arrayContaining(['截面形状', '截面尺寸', '厚度', '下料长度', '部位规格', '数量', '单位']))
    expect(lines[0]?.[headers.indexOf('截面尺寸')]).toBe('17')
    expect(lines[0]?.[headers.indexOf('下料长度')]).toBe('530 mm')
    expect(lines[0]?.[headers.indexOf('数量')]).toBe('40,000')
    expect(lines[1]?.[headers.indexOf('下料长度')]).toBe('—')
    expect(lines[1]?.[headers.indexOf('部位规格')]).toBe('60*60*107')
    expect(headers).not.toContain('硬度')
    expect(dialog.text()).not.toContain('部位入库进度')
    expect(dialog.text()).not.toContain('本次对应原料投入')
  } finally { wrapper.unmount() }
})

it.each(['confirm-semi-receipt', 'view-semi-receipt'])('待入库入口 %s 先读详情，带出旧单库区并用详情版本确认', async entry => {
  const pending: SemiReceiptRecord = { ...record, status: 'PENDING', stock_movement_id: null, etag: '"list-version"' }
  vi.mocked(api.fetchSemiReceiptRecords).mockResolvedValue({ items: [pending], total: 1 })
  vi.mocked(api.fetchSemiReceiptRecord).mockResolvedValue({ ...pending, etag: '"detail-version"', zone_id: 'zone-1',
    zones: [{ id: 'zone-1', warehouse_id: 'warehouse-1', warehouse: '半成品仓', name: '一楼' }] })
  confirm.mockResolvedValue({ receipt_id: pending.id, receipt_number: pending.receipt_number, status: 'CONFIRMED', replayed: false, record_ids: ['movement-1'] })
  const wrapper = mountRecords()
  try {
    await flushPromises()
    expect(wrapper.get('h1').text()).toBe('车间入库')
    expect(wrapper.text()).toContain('待入库')
    await wrapper.get(`[data-testid="${entry}"]`).trigger('click')
    await flushPromises()
    expect(wrapper.get('[role="dialog"]').attributes('width')).toBe('80vw')
    expect(api.fetchSemiReceiptRecord).toHaveBeenCalledWith(pending.id, 'IN')
    expect(confirm).not.toHaveBeenCalled()
    await wrapper.get('[data-testid="confirm-receipt-in-detail"]').trigger('click')
    await flushPromises()
    expect(confirm).toHaveBeenCalledExactlyOnceWith(pending.id, '"detail-version"', 'zone-1')
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
  } finally { wrapper.unmount() }
})

it.each(['METAL', 'SEWING'] as const)('仓管为 %s 待入库单选择半成品仓和库区后，用详情版本确认', async category => {
  const pending: SemiReceiptRecord = { ...record, status: 'PENDING', plan_category: category,
    warehouse: '', zone: '', zone_id: null, etag: '"detail-version"',
    zones: [
      { id: 'zone-a', warehouse_id: 'warehouse-a', warehouse: '一仓', name: '一区' },
      { id: 'zone-b', warehouse_id: 'warehouse-b', warehouse: '二仓', name: '二区' },
    ],
  }
  vi.mocked(api.fetchSemiReceiptRecords).mockResolvedValue({ items: [pending], total: 1 })
  vi.mocked(api.fetchSemiReceiptRecord).mockResolvedValue(pending)
  const wrapper = mountRecords()
  try {
    await flushPromises()
    await wrapper.get('[data-testid="confirm-semi-receipt"]').trigger('click')
    await flushPromises()
    const button = wrapper.findAllComponents(ElButton).find(item => item.attributes('data-testid') === 'confirm-receipt-in-detail')!
    const selects = wrapper.findAllComponents(ElSelect)
    const warehouse = selects.find(select => select.attributes('aria-label') === '半成品仓')!
    const zone = selects.find(select => select.attributes('aria-label') === '库区')!
    expect(button.props('disabled')).toBe(true)
    warehouse.vm.$emit('update:modelValue', 'warehouse-b')
    warehouse.vm.$emit('change', 'warehouse-b')
    await flushPromises()
    expect(zone.findAllComponents(ElOption).map(option => option.props('value'))).toEqual(['zone-b'])
    zone.vm.$emit('update:modelValue', 'zone-b')
    await flushPromises()
    expect(button.props('disabled')).toBe(false)
    await button.trigger('click')
    expect(confirm).toHaveBeenCalledExactlyOnceWith(pending.id, pending.etag, 'zone-b')
  } finally { wrapper.unmount() }
})

it.each([null, 'old-zone'])('裁剪待入库原库区为 %s 时，仓管预选裁剪布面仓唯一的三楼库区', async savedZone => {
  const pending: SemiReceiptRecord = { ...record, status: 'PENDING', plan_category: 'CUTTING',
    zone_id: savedZone, etag: '"detail-version"',
    zones: [{ id: 'cutting-zone', warehouse_id: 'cutting-warehouse', warehouse: '裁剪布面仓', name: '三楼' }],
  }
  vi.mocked(api.fetchSemiReceiptRecords).mockResolvedValue({ items: [pending], total: 1 })
  vi.mocked(api.fetchSemiReceiptRecord).mockResolvedValue(pending)
  const wrapper = mountRecords()
  try {
    await flushPromises()
    await wrapper.get('[data-testid="confirm-semi-receipt"]').trigger('click')
    await flushPromises()
    const selects = wrapper.findAllComponents(ElSelect)
    const warehouse = selects.find(select => select.attributes('aria-label') === '半成品仓')!
    const zone = selects.find(select => select.attributes('aria-label') === '库区')!
    expect(warehouse.props('modelValue')).toBe('cutting-warehouse')
    expect(warehouse.findAllComponents(ElOption).map(option => option.props('label'))).toEqual(['裁剪布面仓'])
    expect(zone.props('modelValue')).toBe('cutting-zone')
    await wrapper.get('[data-testid="confirm-receipt-in-detail"]').trigger('click')
    expect(confirm).toHaveBeenCalledExactlyOnceWith(pending.id, pending.etag, 'cutting-zone')
  } finally { wrapper.unmount() }
})

it('从待入库列表打开已被别人确认的单据时，不再显示确认按钮', async () => {
  vi.mocked(api.fetchSemiReceiptRecords).mockResolvedValue({ items: [{ ...record, status: 'PENDING' }], total: 1 })
  vi.mocked(api.fetchSemiReceiptRecord).mockResolvedValue(record)
  const wrapper = mountRecords()
  try {
    await flushPromises()
    await wrapper.get('[data-testid="confirm-semi-receipt"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[role="dialog"]').text()).toContain('已入库')
    expect(wrapper.find('[data-testid="confirm-receipt-in-detail"]').exists()).toBe(false)
    expect(confirm).not.toHaveBeenCalled()
  } finally { wrapper.unmount() }
})

describe('半成品待入库删除', () => {
  const pending = { ...record, id: 'pending-row', receipt_id: 'receipt-1', status: 'PENDING', can_delete: true, etag: '"v1"' }
  it('普通仓管只有查看与删除权限也可读取记录并操作删除，不依赖计划或新增权限', async () => {
    permissions.clear(); permissions.add('inventory.view_internalsemifinishedreceipt'); permissions.add('inventory.delete_internalsemifinishedreceipt')
    vi.mocked(api.fetchSemiReceiptRecords).mockResolvedValue({ items: [pending], total: 1 })
    const wrapper = mountRecords()
    try {
      await flushPromises()
      expect(api.fetchSemiReceiptRecords).toHaveBeenCalledOnce()
      expect(wrapper.find('[data-testid="delete-semi-receipt"]').exists()).toBe(true)
      expect(wrapper.find('[data-testid="confirm-semi-receipt"]').exists()).toBe(false)
    } finally { wrapper.unmount() }
  })
  it('由后台授权控制删除入口，已入库即使带删除标记也不显示', async () => {
    vi.mocked(api.fetchSemiReceiptRecords).mockResolvedValue({ items: [pending, { ...pending, id: 'forbidden', can_delete: false }, { ...record, can_delete: true }], total: 3 })
    const wrapper = mountRecords()
    try {
      await flushPromises()
      expect(wrapper.findAll('[data-testid="delete-semi-receipt"]')).toHaveLength(1)
    } finally { wrapper.unmount() }
  })
  it('确认后删除整张待入库单，携带版本并刷新列表', async () => {
    vi.mocked(api.fetchSemiReceiptRecords).mockResolvedValueOnce({ items: [pending], total: 1 }).mockResolvedValue({ items: [], total: 0 })
    vi.mocked(api.deleteInternalReceiptRecord).mockResolvedValue()
    const wrapper = mountRecords()
    try {
      await flushPromises()
      await wrapper.get('[data-testid="delete-semi-receipt"]').trigger('click')
      await flushPromises()
      expect(ElMessageBox.confirm).toHaveBeenCalledWith(expect.stringContaining('本单全部明细将删除'), '删除待入库记录', expect.any(Object))
      expect(api.deleteInternalReceiptRecord).toHaveBeenCalledWith('receipt-1', '"v1"')
      expect(api.fetchSemiReceiptRecords).toHaveBeenCalledTimes(2)
      expect(wrapper.find('[data-testid="delete-semi-receipt"]').exists()).toBe(false)
    } finally { wrapper.unmount() }
  })
  it('取消删除不发请求、不刷新记录', async () => {
    vi.mocked(api.fetchSemiReceiptRecords).mockResolvedValue({ items: [pending], total: 1 })
    vi.mocked(ElMessageBox.confirm).mockRejectedValue('cancel')
    const wrapper = mountRecords()
    try {
      await flushPromises()
      await wrapper.get('[data-testid="delete-semi-receipt"]').trigger('click'); await flushPromises()
      expect(api.deleteInternalReceiptRecord).not.toHaveBeenCalled()
      expect(api.fetchSemiReceiptRecords).toHaveBeenCalledTimes(1)
    } finally { wrapper.unmount() }
  })
  it.each([404, 409, 412])('删除返回%s时展示原始错误并重新读取当前状态', async status => {
    vi.mocked(api.fetchSemiReceiptRecords).mockResolvedValueOnce({ items: [pending], total: 1 }).mockResolvedValue({ items: [record], total: 1 })
    const failure = new AxiosError('conflict')
    failure.response = { status, data: { error: { message: '该记录已变化，请重新核对。' } } } as never
    vi.mocked(api.deleteInternalReceiptRecord).mockRejectedValue(failure)
    const wrapper = mountRecords()
    try {
      await flushPromises()
      await wrapper.get('[data-testid="delete-semi-receipt"]').trigger('click'); await flushPromises()
      expect(api.fetchSemiReceiptRecords).toHaveBeenCalledTimes(2)
      expect(wrapper.findComponent({ name: 'ElAlert' }).attributes('title')).toBe('该记录已变化，请重新核对。')
      expect(wrapper.find('[data-testid="delete-semi-receipt"]').exists()).toBe(false)
    } finally { wrapper.unmount() }
  })
})
