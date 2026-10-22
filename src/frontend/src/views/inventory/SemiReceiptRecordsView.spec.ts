import { flushPromises, shallowMount } from '@vue/test-utils'
import ElementPlus, { ElMessageBox } from 'element-plus'
import { AxiosError } from 'axios'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '@/api/internalReceipts'
import type { SemiReceiptRecord } from '@/types/internalReceipt'
import SemiReceiptRecordsView from './SemiReceiptRecordsView.vue'

vi.mock('vue-router', () => ({ useRoute: () => ({ name: 'semi-receipt-records', query: {} }), useRouter: () => ({ push: vi.fn() }) }))
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
  permissions.clear(); permissions.add('inventory.confirm_internalsemifinishedreceipt')
  vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue('confirm' as Awaited<ReturnType<typeof ElMessageBox.confirm>>)
  vi.mocked(api.fetchSemiReceiptRecords).mockResolvedValue({ items: [record], total: 1 })
})
afterEach(() => vi.restoreAllMocks())

describe('半成品入库记录原料投入展示', () => {
  it.each([
    [null, '不核算'],
    ['12.5', '12.5 米'],
    ['0', '0 米'],
    [undefined, '—'],
  ])('原料投入为 %s 时显示 %s，不把缺失核算伪装成零', async (inputQuantity, expected) => {
    const detail = structuredClone(record)
    if (inputQuantity === undefined) delete detail.source_detail!.input_quantity
    else detail.source_detail!.input_quantity = inputQuantity
    vi.mocked(api.fetchSemiReceiptRecord).mockResolvedValue(detail)
    const wrapper = shallowMount(SemiReceiptRecordsView, { global: { plugins: [ElementPlus], renderStubDefaultSlot: true } })
    try {
      await flushPromises()
      await wrapper.get('.receipt-link').trigger('click')
      await flushPromises()
      const input = wrapper.findAll('.receipt-detail-progress label').find(label => label.text().startsWith('本次对应原料投入'))!
      expect(input.find('strong').text()).toBe(expected)
      expect(input.text()).not.toContain('NaN')
      expect(api.fetchSemiReceiptRecord).toHaveBeenCalledWith('record-1', 'IN')
    } finally { wrapper.unmount() }
  })
})

it('待入库记录显示确认操作并调用仓库确认接口', async () => {
  const pending = { ...record, status: 'PENDING', stock_movement_id: null }
  vi.mocked(api.fetchSemiReceiptRecords).mockResolvedValue({ items: [pending], total: 1 } as never)
  confirm.mockResolvedValue({ receipt_id: pending.id, receipt_number: pending.receipt_number, status: 'CONFIRMED', replayed: false, record_ids: ['movement-1'] })
  const wrapper = shallowMount(SemiReceiptRecordsView, { global: { plugins: [ElementPlus], renderStubDefaultSlot: true } })
  try {
    await flushPromises()
    expect(wrapper.text()).toContain('待入库')
    await wrapper.get('[data-testid="confirm-semi-receipt"]').trigger('click')
    await flushPromises()
    expect(confirm).toHaveBeenCalledWith(pending.id, undefined)
  } finally { wrapper.unmount() }
})

describe('半成品待入库删除', () => {
  const pending = { ...record, id: 'pending-row', receipt_id: 'receipt-1', status: 'PENDING', can_delete: true, etag: '"v1"' }
  it('普通仓管只有查看与删除权限也可读取记录并操作删除，不依赖计划或新增权限', async () => {
    permissions.clear(); permissions.add('inventory.view_internalsemifinishedreceipt'); permissions.add('inventory.delete_internalsemifinishedreceipt')
    vi.mocked(api.fetchSemiReceiptRecords).mockResolvedValue({ items: [pending], total: 1 })
    const wrapper = shallowMount(SemiReceiptRecordsView, { global: { plugins: [ElementPlus], renderStubDefaultSlot: true } })
    try {
      await flushPromises()
      expect(api.fetchSemiReceiptRecords).toHaveBeenCalledOnce()
      expect(wrapper.find('[data-testid="delete-semi-receipt"]').exists()).toBe(true)
      expect(wrapper.find('[data-testid="confirm-semi-receipt"]').exists()).toBe(false)
    } finally { wrapper.unmount() }
  })
  it('由后台授权控制删除入口，已入库即使带删除标记也不显示', async () => {
    vi.mocked(api.fetchSemiReceiptRecords).mockResolvedValue({ items: [pending, { ...pending, id: 'forbidden', can_delete: false }, { ...record, can_delete: true }], total: 3 })
    const wrapper = shallowMount(SemiReceiptRecordsView, { global: { plugins: [ElementPlus], renderStubDefaultSlot: true } })
    try {
      await flushPromises()
      expect(wrapper.findAll('[data-testid="delete-semi-receipt"]')).toHaveLength(1)
    } finally { wrapper.unmount() }
  })
  it('确认后删除整张待入库单，携带版本并刷新列表', async () => {
    vi.mocked(api.fetchSemiReceiptRecords).mockResolvedValueOnce({ items: [pending], total: 1 }).mockResolvedValue({ items: [], total: 0 })
    vi.mocked(api.deleteInternalReceiptRecord).mockResolvedValue()
    const wrapper = shallowMount(SemiReceiptRecordsView, { global: { plugins: [ElementPlus], renderStubDefaultSlot: true } })
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
    const wrapper = shallowMount(SemiReceiptRecordsView, { global: { plugins: [ElementPlus], renderStubDefaultSlot: true } })
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
    const wrapper = shallowMount(SemiReceiptRecordsView, { global: { plugins: [ElementPlus], renderStubDefaultSlot: true } })
    try {
      await flushPromises()
      await wrapper.get('[data-testid="delete-semi-receipt"]').trigger('click'); await flushPromises()
      expect(api.fetchSemiReceiptRecords).toHaveBeenCalledTimes(2)
      expect(wrapper.findComponent({ name: 'ElAlert' }).attributes('title')).toBe('该记录已变化，请重新核对。')
      expect(wrapper.find('[data-testid="delete-semi-receipt"]').exists()).toBe(false)
    } finally { wrapper.unmount() }
  })
})
