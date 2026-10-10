import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { reactive } from 'vue'
import { AxiosError } from 'axios'
import { useAuthStore } from '@/stores/auth'
import ElementPlus from 'element-plus'
import { createPinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import SampleLoanDetailView from './SampleLoanDetailView.vue'

enableAutoUnmount(afterEach)
const routeParams = reactive({ loanId: 'loan-1' })
const routerPush = vi.hoisted(() => vi.fn())
const apiMocks = vi.hoisted(() => ({ fetchDetail: vi.fn() }))

vi.mock('vue-router', () => ({
  useRoute: () => ({ params: routeParams }),
  useRouter: () => ({ push: routerPush }),
}))

vi.mock('@/api/samples', () => ({
  fetchSampleLoanDetail: apiMocks.fetchDetail,
}))

const detailFixture = {
  loan_id: 'loan-1',
  loan_number: 'JC-20260901-002',
  document_type: '样品借出',
  submitted_by: '陈方煜',
  submitted_at: '2026-09-01T11:08:00+08:00',
  operation_source: '样品库',
  status: 'ACTIVE',
  status_display: '借出中',
  inventory_status_display: '库存占用中',
  line_count: 2,
  lines: [
    {
      id: 'line-1',
      inventory_line_id: 'inventory-1',
      receipt_id: 'receipt-1',
      receipt_number: 'RK-20260901-001',
      sample_request_id: 'sample-1',
      sample_request_number: 'SYGJ-20260828-016',
      product_name: '铝框休闲椅',
      specification: '620×680',
      color: '岩灰',
      loan_quantity: 1,
      borrower_name: '王立新',
      purpose_note: '客户现场确认材质',
      inventory_impact: '可用库存 -1',
    },
    {
      id: 'line-2',
      inventory_line_id: 'inventory-2',
      receipt_id: 'receipt-2',
      receipt_number: 'RK-20260831-006',
      sample_request_id: 'sample-2',
      sample_request_number: 'SYGJ-20260826-011',
      product_name: '藤编双人椅',
      specification: '1380×720',
      color: '沙棕',
      loan_quantity: 1,
      borrower_name: '赵倩',
      purpose_note: '展厅陈列对比',
      inventory_impact: '可用库存 -1',
    },
  ],
}

describe('SampleLoanDetailView', () => {
  beforeEach(() => {
    routeParams.loanId = 'loan-1'
    routerPush.mockReset()
    apiMocks.fetchDetail.mockReset().mockResolvedValue(detailFixture)
  })
  async function render(permissions = ['samples.view_sampleinventoryloanline', 'samples.view_sampleinventoryline', 'samples.view_samplerequest']) {
    const pinia = createPinia()
    useAuthStore(pinia).user = { id: 1, username: 'qa', display_name: '验收员', is_superuser: false, employee: null, permissions, data_scope: 'ALL' }
    const wrapper = mount(SampleLoanDetailView, { global: { plugins: [pinia, ElementPlus] } })
    await flushPromises(); await flushPromises()
    return wrapper
  }


  it('按 Figma 展示单据概要、八列明细和库存占用状态', async () => {
    const wrapper = await render()

    expect(apiMocks.fetchDetail).toHaveBeenCalledWith('loan-1')
    expect(wrapper.text()).toContain('借出单详情')
    expect(wrapper.text()).toContain('JC-20260901-002')
    expect(wrapper.text()).toContain('借出中')
    expect(wrapper.text()).toContain('库存占用中')
    expect(wrapper.text()).toContain('王立新')
    expect(wrapper.text()).toContain('客户现场确认材质')
    expect(wrapper.text()).toContain('可用库存 -1')
    expect(wrapper.text()).toContain('借出数量持续占用可用库存')

    const headers = wrapper.findAll('.lines-table-head > span').map((item) => item.text())
    expect(headers.slice(0, 8)).toEqual([
      '来源入库批次',
      '样品跟进单号',
      '产品名称',
      '规格 / 颜色',
      '借出数量',
      '借用人',
      '用途 / 备注',
      '库存影响',
    ])

    await wrapper.find('.back-button').trigger('click')
    expect(routerPush).toHaveBeenCalledWith({ name: 'sample-loans' })
  })
  it('空标识不调用接口', async () => {
    routeParams.loanId = ''
    const wrapper = await render()
    expect(apiMocks.fetchDetail).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('借出单标识不能为空')
  })

  it.each([403, 404, 503])('接口%s显示明确错误并可重试', async status => {
    apiMocks.fetchDetail.mockRejectedValueOnce(new AxiosError('失败', undefined, undefined, undefined, { status, data: {} } as never))
    const wrapper = await render()
    expect(wrapper.find('.detail-error').exists()).toBe(true)
    const message = status === 403 ? '没有查看借出单详情的权限' : status === 404 ? '未找到该借出单' : '服务暂时异常'
    expect(wrapper.text()).toContain(message)
    await wrapper.findAll('button').find(button => button.text().includes('重新加载'))!.trigger('click')
    await flushPromises()
    expect(wrapper.find('.overview-card').exists()).toBe(true)
  })

  it('参数变化加载新单据，旧响应不会覆盖新内容', async () => {
    let resolveOld!: (value: unknown) => void
    apiMocks.fetchDetail.mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve }))
    const wrapper = await render()
    routeParams.loanId = 'loan-2'
    apiMocks.fetchDetail.mockResolvedValueOnce({ ...detailFixture, loan_number: 'JC-NEW' })
    await flushPromises()
    resolveOld({ ...detailFixture, loan_number: 'JC-OLD' }); await flushPromises()
    expect(wrapper.text()).toContain('JC-NEW')
    expect(wrapper.text()).not.toContain('JC-OLD')
    expect(apiMocks.fetchDetail).toHaveBeenLastCalledWith('loan-2')
  })

  it('无权限不读取单据，来源链接分别按权限禁用', async () => {
    const denied = await render([])
    expect(apiMocks.fetchDetail).not.toHaveBeenCalled()
    expect(denied.text()).toContain('没有查看借出单详情的权限')
    denied.unmount()
    const wrapper = await render(['samples.view_sampleinventoryloanline'])
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
    routeParams.loanId = 'empty'; await flushPromises()
    expect(wrapper.text()).toContain('暂无借出明细')
    expect(wrapper.text()).toContain('暂无来源样品')
  })
})
