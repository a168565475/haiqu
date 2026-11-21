import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { describe, expect, it, vi } from 'vitest'
import { fetchProcurementInboundOrders } from '@/api/inventory'
import type { PurchaseReceivingSection } from '@/types/inventory'
import PurchaseInboundListView from './PurchaseInboundListView.vue'

const { push } = vi.hoisted(() => ({ push: vi.fn() }))
vi.mock('vue-router', () => ({ useRouter: () => ({ push }) }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ user: { is_superuser: true }, hasPermission: () => true }) }))
vi.mock('@/api/inventory', () => ({ fetchProcurementInboundOrders: vi.fn() }))

async function renderProgress(percent: string | null | undefined, receivingSections: { id: PurchaseReceivingSection; name: string }[] = [], workflowStatus = 'PENDING_QUALITY') {
  vi.mocked(fetchProcurementInboundOrders).mockResolvedValue([{
    id: 'order', order_number: 'CGDD-1', supplier_names: [], product_summary: [], supplier_summary: [],
    quantity_unit: 'MIXED', received_quantity: '1020', receipt_progress_percent: percent,
    receiving_sections: receivingSections, source_type: 'PRODUCTION', remaining_line_count: 1, return_status: 'NONE',
    workflow_status: workflowStatus, pending_quality_count: workflowStatus === 'PENDING_QUALITY' ? 1 : 0,
    workflow_status_display: workflowStatus === 'COMPLETED' ? '已完成' : '待品质确认', updated_at: '2026-11-14T00:00:00Z',
  }] as never)
  const wrapper = mount(PurchaseInboundListView, { attachTo: document.body, global: { plugins: [ElementPlus] } })
  await flushPromises()
  return wrapper
}

describe('采购入库列表显示到货进度', () => {
  it('采购入库有待质检批次时仍只显示详情和分区收货操作', async () => {
    const wrapper = await renderProgress('25.0', [{ id: 'B', name: '五金件、塑料件、包材' }])
    try {
      const actions = wrapper.get('.more-action')
      expect(actions.findAll('button')).toHaveLength(1)
      expect(wrapper.findAllComponents({ name: 'ElDropdownItem' })).toHaveLength(0)
      await actions.get('button').trigger('click')
      await vi.waitFor(() => expect(wrapper.findAllComponents({ name: 'ElDropdownItem' }).map(item => item.text()))
        .toEqual(['查看详情', '五金件、塑料件、包材入库']))
      wrapper.findAllComponents({ name: 'ElDropdownItem' })[1]!.vm.$emit('click')
      expect(push).toHaveBeenCalledWith({
        name: 'material-purchase-inbound', params: { purchaseOrderId: 'order' }, query: { material_section: 'B' },
      })
    } finally { wrapper.unmount() }
  })
  it('点生产采购单行只打开详情，入库从分区按钮办理', async () => {
    const wrapper = await renderProgress('25.0', [{ id: 'A', name: '管材' }, { id: 'C', name: '面料、辅料' }])
    try {
      push.mockClear()
      await wrapper.get('.el-table__row').trigger('click')
      expect(push).toHaveBeenCalledExactlyOnceWith({ name: 'purchase-inbound-detail', params: { id: 'order' } })
    } finally { wrapper.unmount() }
  })
  it('已完成采购单仍有操作菜单，菜单里只有查看详情', async () => {
    const wrapper = await renderProgress('100.0', [{ id: 'A', name: '管材' }], 'COMPLETED')
    try {
      await wrapper.get('.more-action button').trigger('click')
      await vi.waitFor(() => expect(wrapper.findAllComponents({ name: 'ElDropdownItem' }).map(item => item.text()))
        .toEqual(['查看详情']))
    } finally { wrapper.unmount() }
  })
  it.each(['0.0', '37.5', '99.9', '100.0'])('显示真实百分比 %s，保留独立品质状态', async percent => {
    const wrapper = await renderProgress(percent)
    try {
      const progress = wrapper.findComponent({ name: 'ElProgress' })
      expect(progress.props('percentage')).toBe(Number(percent))
      expect(progress.props('strokeWidth')).toBe(10)
      expect(wrapper.get('[data-testid="receipt-progress"]').text()).toBe(`${Number(percent)}%`)
      expect(wrapper.text()).toContain('待品质确认')
      expect(wrapper.text()).not.toContain('累计到货')
      expect(wrapper.text()).not.toContain('1,020')
      expect(wrapper.text()).not.toContain('多单位，查看明细')
    } finally { wrapper.unmount() }
  })

  it.each([null, undefined, '', 'bad', '-1', '101'])('未知或非法进度 %s 不显示虚假零进度', async percent => {
    const wrapper = await renderProgress(percent)
    try {
      expect(wrapper.findComponent({ name: 'ElProgress' }).exists()).toBe(false)
      expect(wrapper.get('[data-testid="receipt-progress-unknown"]').text()).toBe('待核对')
    } finally { wrapper.unmount() }
  })
})
