import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { describe, expect, it, vi } from 'vitest'
import { fetchProcurementInboundOrders } from '@/api/inventory'
import PurchaseInboundListView from './PurchaseInboundListView.vue'

vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }) }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ user: { is_superuser: true }, hasPermission: () => true }) }))
vi.mock('@/api/inventory', () => ({ fetchProcurementInboundOrders: vi.fn() }))

async function renderProgress(percent: string | null | undefined) {
  vi.mocked(fetchProcurementInboundOrders).mockResolvedValue([{
    id: 'order', order_number: 'CGDD-1', supplier_names: [], product_summary: [], supplier_summary: [],
    quantity_unit: 'MIXED', received_quantity: '1020', receipt_progress_percent: percent,
    workflow_status: 'PENDING_QUALITY', workflow_status_display: '待品质确认', updated_at: '2026-11-14T00:00:00Z',
  }] as never)
  const wrapper = mount(PurchaseInboundListView, { global: { plugins: [ElementPlus] } })
  await flushPromises()
  return wrapper
}

describe('采购入库列表显示到货进度', () => {
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
