import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { reactive } from 'vue'
import { AxiosError } from 'axios'
import ElementPlus from 'element-plus'
import { createPinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useAuthStore } from '@/stores/auth'

import SampleInventoryReceiptDetailView from './SampleInventoryReceiptDetailView.vue'
enableAutoUnmount(afterEach)
const routeParams = reactive({ receiptId: 'receipt-1' })

const routerPush = vi.hoisted(() => vi.fn())
const apiMocks = vi.hoisted(() => ({ fetchDetail: vi.fn() }))

vi.mock('vue-router', () => ({
  useRoute: () => ({ params: routeParams }),
  useRouter: () => ({ push: routerPush }),
}))

vi.mock('@/api/samples', () => ({
  fetchSampleInventoryReceiptDetail: apiMocks.fetchDetail,
}))

const detailFixture = {
  receipt_id: 'receipt-1',
  receipt_number: 'RK-20260901-001',
  document_type: '样品入库',
  submitted_by: '陈方煜',
  submitted_at: '2026-09-01T09:28:00+08:00',
  operation_source: '样品库',
  status: 'COMPLETED',
  status_display: '已完成',
  line_count: 2,
  lines: [
    {
      id: 'line-1',
      sample_item_id: 'item-1',
      sample_request_id: 'sample-1',
      sample_request_number: 'SYGJ-20260830-021',
      product_category: '户外桌椅',
      product_name: '铝框单椅',
      specification: '620×680',
      color: '岩灰',
      sampling_quantity: 6,
      received_quantity: 2,
      cumulative_received: 2,
      location: '样品库',
      finished_goods_receipt_number: 'CPRK-202609-000001',
      finished_goods_warehouse: '成品仓',
      finished_goods_zone: '一楼',
      finished_goods_location: 'A-001',
      flow_condition: 'PMC✓ 金工✓ 裁剪✓',
      source_status: '流程已结束',
    },
    {
      id: 'line-2',
      sample_item_id: 'item-2',
      sample_request_id: 'sample-2',
      sample_request_number: 'SYGJ-20260828-016',
      product_category: '花园家具',
      product_name: '藤编双人椅',
      specification: '1380×720',
      color: '沙棕',
      sampling_quantity: 4,
      received_quantity: 2,
      cumulative_received: 4,
      location: '样品库',
      finished_goods_receipt_number: 'CPRK-202609-000002',
      finished_goods_warehouse: '成品仓',
      finished_goods_zone: '一楼',
      finished_goods_location: 'A-002',
      flow_condition: 'PMC✓ 金工✓ 裁剪✓',
      source_status: '流程已结束',
    },
  ],
}

describe('SampleInventoryReceiptDetailView', () => {
  beforeEach(() => {
    routeParams.receiptId = 'receipt-1'
    routerPush.mockReset()
    apiMocks.fetchDetail.mockReset().mockResolvedValue(detailFixture)
  })
  async function render(permissions = ['samples.view_sampleinventoryline', 'samples.view_samplerequest']) {
    const pinia = createPinia()
    useAuthStore(pinia).user = { id: 1, username: 'qa', display_name: '验收员', is_superuser: false, employee: null, permissions, data_scope: 'ALL' }
    const wrapper = mount(SampleInventoryReceiptDetailView, { global: { plugins: [pinia, ElementPlus] } })
    await flushPromises(); await flushPromises()
    return wrapper
  }

  it('按 Figma 展示单据概要、九列明细和来源跟进单', async () => {
    const wrapper = await render()

    await flushPromises()
    await flushPromises()

    expect(apiMocks.fetchDetail).toHaveBeenCalledWith('receipt-1')
    expect(wrapper.text()).toContain('入库单详情')
    expect(wrapper.text()).toContain('RK-20260901-001')
    expect(wrapper.text()).toContain('陈方煜')
    expect(wrapper.text()).toContain('2 条明细')
    expect(wrapper.text()).toContain('SYGJ-20260830-021')
    expect(wrapper.text()).toContain('藤编双人椅')
    expect(wrapper.text()).toContain('成品仓 / 一楼 / A-001')
    expect(wrapper.text()).toContain('CPRK-202609-000001')
    expect(wrapper.text()).toContain('PMC 审核通过 · 金工参数完成 · 裁剪参数完成')

    const headers = wrapper.findAll('.lines-table-head > span').map((item) => item.text())
    expect(headers.slice(0, 9)).toEqual([
      '样品跟进单号',
      '产品类别',
      '产品名称',
      '规格 / 颜色',
      '打样数量',
      '本次入库',
      '累计入库',
      '样品库 / 成品仓位置',
      '流程条件',
    ])

    await wrapper.find('.back-button').trigger('click')
    expect(routerPush).toHaveBeenCalledWith({ name: 'sample-inventory' })
  })

  it('无查看权限不读取详情，无来源权限不能跳转申请', async () => {
    const denied = await render([])
    expect(apiMocks.fetchDetail).not.toHaveBeenCalled()
    expect(denied.text()).toContain('没有查看入库单详情的权限')
    denied.unmount()
    const wrapper = await render(['samples.view_sampleinventoryline'])
    expect(wrapper.find('button.source-link').attributes('disabled')).toBeDefined()
    await wrapper.find('button.source-link').trigger('click')
    expect(routerPush).not.toHaveBeenCalled()
  })

  it('有权限按来源单号打开打样详情', async () => {
    const wrapper = await render()
    await wrapper.find('button.source-link').trigger('click')
    expect(routerPush).toHaveBeenCalledWith({ name: 'sample-detail', params: { sampleId: 'sample-1' } })
  })

  it('空标识不调用接口', async () => {
    routeParams.receiptId = ''
    const wrapper = await render()
    expect(apiMocks.fetchDetail).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('入库单标识不能为空')
  })

  it.each([403, 404, 503])('接口%s显示明确错误并可重试', async status => {
    apiMocks.fetchDetail.mockRejectedValueOnce(new AxiosError('失败', undefined, undefined, undefined, { status, data: {} } as never))
    const wrapper = await render()
    expect(wrapper.find('.detail-error').exists()).toBe(true)
    const message = status === 403 ? '没有查看入库单详情的权限' : status === 404 ? '未找到该入库单' : '服务暂时异常'
    expect(wrapper.text()).toContain(message)
    await wrapper.findAll('button').find(button => button.text().includes('重新加载'))!.trigger('click')
    await flushPromises()
    expect(wrapper.find('.overview-card').exists()).toBe(true)
  })

  it('参数变化加载新单据，旧响应不会覆盖新内容', async () => {
    let resolveOld!: (value: unknown) => void
    apiMocks.fetchDetail.mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve }))
    const wrapper = await render()
    routeParams.receiptId = 'receipt-2'
    apiMocks.fetchDetail.mockResolvedValueOnce({ ...detailFixture, receipt_number: 'RK-NEW' })
    await flushPromises()
    resolveOld({ ...detailFixture, receipt_number: 'RK-OLD' }); await flushPromises()
    expect(wrapper.text()).toContain('RK-NEW')
    expect(wrapper.text()).not.toContain('RK-OLD')
    expect(apiMocks.fetchDetail).toHaveBeenLastCalledWith('receipt-2')
  })

  it('历史记录不虚构成品库位，缺少明细显示空态', async () => {
    apiMocks.fetchDetail.mockResolvedValueOnce({ ...detailFixture, submitted_at: 'invalid', lines: [{ ...detailFixture.lines[0], finished_goods_warehouse: '', finished_goods_zone: '', finished_goods_location: '' }] })
    const wrapper = await render()
    expect(wrapper.text()).toContain('历史记录未同步')
    expect(wrapper.text()).not.toContain('Invalid Date')
    apiMocks.fetchDetail.mockResolvedValueOnce({ ...detailFixture, line_count: 0, lines: [] })
    routeParams.receiptId = 'empty'; await flushPromises()
    expect(wrapper.text()).toContain('暂无入库明细')
    expect(wrapper.text()).toContain('暂无来源样品')
  })
})
