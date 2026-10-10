import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { reactive } from 'vue'
import { AxiosError } from 'axios'
import { useAuthStore } from '@/stores/auth'
import ElementPlus from 'element-plus'
import { createPinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import SampleOutboundDetailView from './SampleOutboundDetailView.vue'

enableAutoUnmount(afterEach)
const routeParams = reactive({ outboundId: 'outbound-1' })
const routerPush = vi.hoisted(() => vi.fn())
const apiMocks = vi.hoisted(() => ({ fetchDetail: vi.fn() }))

vi.mock('vue-router', () => ({
  useRoute: () => ({ params: routeParams }),
  useRouter: () => ({ push: routerPush }),
}))

vi.mock('@/api/samples', () => ({
  fetchSampleOutboundDetail: apiMocks.fetchDetail,
}))

const detailFixture = {
  outbound_id: 'outbound-1',
  outbound_number: 'CK-20260902-001',
  document_type: '样品出库',
  submitted_by: '陈方煜',
  submitted_at: '2026-09-02T09:28:00+08:00',
  operation_source: '样品库',
  status: 'COMPLETED',
  status_display: '已完成',
  line_count: 2,
  lines: [
    {
      id: 'line-1',
      inventory_line_id: 'inventory-1',
      receipt_id: 'receipt-1',
      receipt_number: 'RK-20260901-001',
      sample_request_id: 'sample-1',
      sample_request_number: 'SYGJ-20260830-021',
      product_name: '铝框单椅',
      specification: '620×680',
      color: '岩灰',
      outbound_quantity: 2,
      outbound_method: 'MERCHANDISER_MAIL',
      outbound_method_display: '跟单员邮寄',
      courier_company: '顺丰速运',
      tracking_number: 'SF1234567890',
      remark: '',
    },
    {
      id: 'line-2',
      inventory_line_id: 'inventory-2',
      receipt_id: 'receipt-2',
      receipt_number: 'RK-20260831-006',
      sample_request_id: 'sample-2',
      sample_request_number: 'SYGJ-20260828-016',
      product_name: '藤编双人椅',
      specification: '1380×720',
      color: '沙棕',
      outbound_quantity: 1,
      outbound_method: 'SALESPERSON_CARRY',
      outbound_method_display: '业务员带走',
      courier_company: '',
      tracking_number: '',
      remark: '业务拜访携带',
    },
  ],
}

describe('SampleOutboundDetailView', () => {
  beforeEach(() => {
    routeParams.outboundId = 'outbound-1'
    routerPush.mockReset()
    apiMocks.fetchDetail.mockReset().mockResolvedValue(detailFixture)
  })
  async function render(permissions = ['samples.view_sampleinventoryoutboundline', 'samples.view_sampleinventoryline', 'samples.view_samplerequest']) {
    const pinia = createPinia()
    useAuthStore(pinia).user = { id: 1, username: 'qa', display_name: '验收员', is_superuser: false, employee: null, permissions, data_scope: 'ALL' }
    const wrapper = mount(SampleOutboundDetailView, { global: { plugins: [pinia, ElementPlus] } })
    await flushPromises(); await flushPromises()
    return wrapper
  }


  it('按 Figma 展示单据概要、九列明细和来源跟进单', async () => {
    const wrapper = await render()

    expect(apiMocks.fetchDetail).toHaveBeenCalledWith('outbound-1')
    expect(wrapper.text()).toContain('出库单详情')
    expect(wrapper.text()).toContain('CK-20260902-001')
    expect(wrapper.text()).toContain('陈方煜')
    expect(wrapper.text()).toContain('2 条明细')
    expect(wrapper.text()).toContain('跟单员邮寄')
    expect(wrapper.text()).toContain('SF1234567890')
    expect(wrapper.text()).toContain('业务拜访携带')
    expect(wrapper.text()).toContain('出库数量 ≤ 可用库存')

    const headers = wrapper.findAll('.lines-table-head > span').map((item) => item.text())
    expect(headers.slice(0, 9)).toEqual([
      '来源入库批次',
      '样品跟进单号',
      '产品名称',
      '规格 / 颜色',
      '出库数量',
      '出库方式',
      '快递公司',
      '快递单号',
      '备注',
    ])

    const secondRowValues = wrapper.findAll('.lines-table-row').at(1)?.findAll('span') || []
    expect(secondRowValues.at(5)?.text()).toBe('—')
    expect(secondRowValues.at(6)?.text()).toBe('—')

    await wrapper.find('.back-button').trigger('click')
    expect(routerPush).toHaveBeenCalledWith({ name: 'sample-outbound' })
  })
  it('空标识不调用接口', async () => {
    routeParams.outboundId = ''
    const wrapper = await render()
    expect(apiMocks.fetchDetail).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('出库单标识不能为空')
  })

  it.each([403, 404, 503])('接口%s显示明确错误并可重试', async status => {
    apiMocks.fetchDetail.mockRejectedValueOnce(new AxiosError('失败', undefined, undefined, undefined, { status, data: {} } as never))
    const wrapper = await render()
    expect(wrapper.find('.detail-error').exists()).toBe(true)
    const message = status === 403 ? '没有查看出库单详情的权限' : status === 404 ? '未找到该出库单' : '服务暂时异常'
    expect(wrapper.text()).toContain(message)
    await wrapper.findAll('button').find(button => button.text().includes('重新加载'))!.trigger('click')
    await flushPromises()
    expect(wrapper.find('.overview-card').exists()).toBe(true)
  })

  it('参数变化加载新单据，旧响应不会覆盖新内容', async () => {
    let resolveOld!: (value: unknown) => void
    apiMocks.fetchDetail.mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve }))
    const wrapper = await render()
    routeParams.outboundId = 'outbound-2'
    apiMocks.fetchDetail.mockResolvedValueOnce({ ...detailFixture, outbound_number: 'CK-NEW' })
    await flushPromises()
    resolveOld({ ...detailFixture, outbound_number: 'CK-OLD' }); await flushPromises()
    expect(wrapper.text()).toContain('CK-NEW')
    expect(wrapper.text()).not.toContain('CK-OLD')
    expect(apiMocks.fetchDetail).toHaveBeenLastCalledWith('outbound-2')
  })

  it('无权限不读取单据，来源链接分别按权限禁用', async () => {
    const denied = await render([])
    expect(apiMocks.fetchDetail).not.toHaveBeenCalled()
    expect(denied.text()).toContain('没有查看出库单详情的权限')
    denied.unmount()
    const wrapper = await render(['samples.view_sampleinventoryoutboundline'])
    for (const link of wrapper.findAll('.source-link')) {
      expect(link.attributes('disabled')).toBeDefined()
      await link.trigger('click')
    }
    expect(routerPush).not.toHaveBeenCalled()
  })

  it('有权限分别打开来源入库单和打样申请', async () => {
    const wrapper = await render()
    await wrapper.find('.lines-table .source-link').trigger('click')
    expect(routerPush).toHaveBeenLastCalledWith({ name: 'sample-inventory-receipt-detail', params: { receiptId: 'receipt-1' } })
    await wrapper.find('.source-list .source-link').trigger('click')
    expect(routerPush).toHaveBeenLastCalledWith({ name: 'sample-detail', params: { sampleId: 'sample-1' } })
  })

  it('缺少来源标识禁用跳转，空明细和无效日期不会误展示', async () => {
    apiMocks.fetchDetail.mockResolvedValueOnce({ ...detailFixture, submitted_at: 'invalid', lines: [{ ...detailFixture.lines[0], receipt_id: '', sample_request_id: '' }] })
    const wrapper = await render()
    expect(wrapper.text()).not.toContain('Invalid Date')
    expect(wrapper.findAll('.source-link').every(link => link.attributes('disabled') !== undefined)).toBe(true)
    apiMocks.fetchDetail.mockResolvedValueOnce({ ...detailFixture, line_count: 0, lines: [] })
    routeParams.outboundId = 'empty'; await flushPromises()
    expect(wrapper.text()).toContain('暂无出库明细')
    expect(wrapper.text()).toContain('暂无来源样品')
  })
})
