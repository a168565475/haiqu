import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElSelect } from 'element-plus'
import { createPinia } from 'pinia'
import { AxiosError } from 'axios'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useAuthStore } from '@/stores/auth'
import SampleInventoryReceiptDialog from './SampleInventoryReceiptDialog.vue'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
enableAutoUnmount(afterEach)

const apiMocks = vi.hoisted(() => ({
  fetchEligible: vi.fn(),
  fetchFinishedGoodsOptions: vi.fn(),
  createReceipt: vi.fn(),
}))

vi.mock('@/api/samples', () => ({
  fetchSampleInventoryEligible: apiMocks.fetchEligible,
  fetchSampleFinishedGoodsOptions: apiMocks.fetchFinishedGoodsOptions,
  createSampleInventoryReceipt: apiMocks.createReceipt,
}))

const eligibleRow = {
  sample_item_id: 'sample-item-1',
  sample_request_number: 'SYGJ-20260902-031',
  flow_condition: 'PMC✓ 金工✓ 裁剪✓',
  product_category: '户外桌椅',
  product_name: '铝框单椅',
  specification: '620×680×820',
  color: '岩灰',
  sampling_quantity: 6,
  cumulative_received: 2,
  remaining_quantity: 4,
}

function findButton(label: string): HTMLButtonElement {
  const button = Array.from(document.body.querySelectorAll('button'))
    .find((item) => item.textContent?.trim() === label)
  if (!(button instanceof HTMLButtonElement)) throw new Error(`未找到按钮：${label}`)
  return button
}

async function render(permissions = ['samples.add_sampleinventoryreceipt']) {
  const pinia = createPinia()
  useAuthStore(pinia).user = { id: 1, username: 'tester', display_name: '测试员工', is_superuser: false, employee: null, permissions, data_scope: 'ALL' }
  const wrapper = mount(SampleInventoryReceiptDialog, { attachTo: document.body, props: { modelValue: true }, global: { plugins: [pinia, ElementPlus] } })
  await flushPromises()
  return wrapper
}
function fillQuantity(value: string) {
  const input = document.querySelector('.sample-receipt-dialog .quantity-input input') as HTMLInputElement
  input.value = value
  input.dispatchEvent(new Event('input', { bubbles: true }))
}
function fillAllQuantities(value: string) {
  document.querySelectorAll('.sample-receipt-dialog .quantity-input input').forEach((element) => {
    const input = element as HTMLInputElement
    input.value = value
    input.dispatchEvent(new Event('input', { bubbles: true }))
  })
}
function apiError(status: number) {
  return new AxiosError('失败', undefined, undefined, undefined, { status, data: { error: { message: '服务异常' } } } as never)
}

describe('SampleInventoryReceiptDialog', () => {
  beforeEach(() => {
    apiMocks.fetchEligible.mockReset().mockResolvedValue({
      data: [eligibleRow],
      meta: { page: 1, page_size: 100, total: 1, total_pages: 1 },
    })
    apiMocks.fetchFinishedGoodsOptions.mockReset().mockResolvedValue({
      warehouses: [{ id: 'warehouse-1', warehouse_number: 'CK007', warehouse_name: '成品仓' }],
      zones: [{ id: 'zone-1', warehouse_id: 'warehouse-1', zone_name: '一楼' }],
      locations: [{ id: 'location-1', warehouse_id: 'warehouse-1', zone_id: 'zone-1', location_number: 'A-001' }],
    })
    apiMocks.createReceipt.mockReset().mockResolvedValue({
      receipt_id: 'receipt-1',
      receipt_number: 'RK-202609-000001',
      submitted_by: '陈方煜',
      submitted_at: '2026-09-02T10:00:00+08:00',
      line_count: 1,
    })
  })

  afterEach(() => {
    document.body.innerHTML = ''
  })

  it('加载合资格明细并校验后提交真实入库参数', async () => {
    const pinia = createPinia()
    const authStore = useAuthStore(pinia)
    authStore.user = {
      id: 1,
      username: 'chenfangyu',
      display_name: '陈方煜',
      is_superuser: false,
      employee: null,
      permissions: ['samples.add_sampleinventoryreceipt'],
      data_scope: 'ALL',
    }
    const wrapper = mount(SampleInventoryReceiptDialog, {
      attachTo: document.body,
      props: { modelValue: true },
      global: { plugins: [pinia, ElementPlus] },
    })

    await flushPromises()
    await flushPromises()

    const dialogComponent = wrapper.findComponent(AppWindowDialog)
    expect(dialogComponent.exists()).toBe(true)
    expect(dialogComponent.props('title')).toBe('批量入库样品')

    const dialog = document.body.querySelector('.sample-receipt-dialog')
    expect(dialog?.textContent).toContain('批量入库样品')
    expect(dialog?.textContent).toContain('成品仓入库位置')
    expect(dialog?.querySelector('.batch-dialog-subtitle')).toBeNull()
    expect(dialog?.querySelector('.document-summary')).toBeNull()
    expect(dialog?.querySelector('.rule-alert')).toBeNull()
    expect(dialog?.querySelector('.validation-bar')).toBeNull()
    expect(dialog?.querySelector('.state-note')).toBeNull()
    expect(dialog?.textContent).toContain('SYGJ-20260902-031')
    expect(dialog?.textContent).toContain('PMC✓ 金工✓ 裁剪✓')
    expect(dialog?.textContent).toContain('户外桌椅')
    const headers = Array.from(dialog?.querySelectorAll('.el-table__header th') || []).map((cell) => cell.textContent?.trim())
    expect(headers).toContain('产品类别')
    expect(headers).toContain('产品名称')
    expect(headers).toContain('规格')
    expect(headers).toContain('颜色')
    expect(headers).not.toContain('规格 / 颜色')
    expect(dialog?.querySelector('.el-table__body .el-checkbox')).toBeNull()

    findButton('确认入库').click()
    await flushPromises()
    expect(document.body.textContent).toContain('未填写任何入库数量')
    expect(apiMocks.createReceipt).not.toHaveBeenCalled()

    const quantityInput = document.body.querySelector(
      '.sample-receipt-dialog .quantity-input input',
    ) as HTMLInputElement | null
    expect(quantityInput?.disabled).toBe(false)
    if (!quantityInput) throw new Error('未找到入库数量输入框')
    quantityInput.value = '2'
    quantityInput.dispatchEvent(new Event('input', { bubbles: true }))
    await flushPromises()

    const finishedLocationSelect = wrapper.findAllComponents(ElSelect)[2]
    finishedLocationSelect.vm.$emit('update:modelValue', 'location-1')
    await flushPromises()

    findButton('确认入库').click()
    await flushPromises()

    expect(apiMocks.createReceipt).toHaveBeenCalledWith(
      [
        {
          sample_item_id: 'sample-item-1',
          received_quantity: 2,
          location: '样品库',
          expected_cumulative_received: 2,
        },
      ],
      {
        warehouse_id: 'warehouse-1',
        zone_id: 'zone-1',
        location_id: 'location-1',
      },
    )
    expect(wrapper.emitted('created')?.[0]?.[0]).toMatchObject({
      receipt_number: 'RK-202609-000001',
    })
  })

  it('没有入库权限时不读取候选数据并禁止提交', async () => {
    await render([])
    expect(apiMocks.fetchEligible).not.toHaveBeenCalled()
    expect(apiMocks.fetchFinishedGoodsOptions).not.toHaveBeenCalled()
    expect(document.body.textContent).toContain('当前账号没有样品入库权限')
    expect(findButton('确认入库').disabled).toBe(true)
  })

  it('读取后续候选页并按明细去重', async () => {
    apiMocks.fetchEligible.mockResolvedValueOnce({ data: [eligibleRow], meta: { total_pages: 2 } })
    apiMocks.fetchEligible.mockResolvedValueOnce({ data: [eligibleRow, { ...eligibleRow, sample_item_id: 'item-2', product_name: '第二页产品' }], meta: { total_pages: 2 } })
    await render()
    expect(apiMocks.fetchEligible).toHaveBeenLastCalledWith(2)
    expect(document.body.textContent).toContain('第二页产品')
    expect(document.querySelectorAll('.sample-receipt-dialog .el-table__row')).toHaveLength(2)
  })

  it('后续页失败时不把不完整候选列表当作加载成功', async () => {
    apiMocks.fetchEligible.mockResolvedValueOnce({ data: [eligibleRow], meta: { total_pages: 2 } })
    apiMocks.fetchEligible.mockRejectedValueOnce(apiError(503))
    await render()
    expect(document.body.textContent).toContain('服务异常')
    expect(findButton('确认入库').disabled).toBe(true)
    expect(document.querySelectorAll('.sample-receipt-dialog .el-table__row')).toHaveLength(0)
  })

  it('选择超过接口单次100条限制时提示分批而不发送请求', async () => {
    apiMocks.fetchEligible.mockResolvedValueOnce({ data: Array.from({ length: 101 }, (_, index) => ({ ...eligibleRow, sample_item_id: `item-${index}` })), meta: { total_pages: 1 } })
    await render()
    fillAllQuantities('1')
    await flushPromises(); findButton('确认入库').click(); await flushPromises()
    expect(document.body.textContent).toContain('一次最多提交 100 条')
    expect(apiMocks.createReceipt).not.toHaveBeenCalled()
  })

  it('候选加载失败可重试，空列表禁止提交', async () => {
    apiMocks.fetchEligible.mockRejectedValueOnce(apiError(503))
    await render()
    expect(document.body.textContent).toContain('服务异常')
    expect(findButton('确认入库').disabled).toBe(true)
    apiMocks.fetchEligible.mockResolvedValueOnce({ data: [], meta: { total: 0 } })
    findButton('重新加载').click(); await flushPromises()
    expect(document.body.textContent).toContain('暂无符合入库条件的样品')
    expect(findButton('确认入库').disabled).toBe(true)
  })

  it('关闭重开后旧候选返回不会覆盖新数据', async () => {
    let oldResult!: (value: unknown) => void
    apiMocks.fetchEligible.mockImplementationOnce(() => new Promise(resolve => { oldResult = resolve }))
    const wrapper = await render()
    await wrapper.setProps({ modelValue: false })
    await wrapper.setProps({ modelValue: true }); await flushPromises()
    oldResult({ data: [{ ...eligibleRow, product_name: '过期产品' }], meta: { total: 1 } })
    await flushPromises()
    expect(document.body.textContent).toContain('铝框单椅')
    expect(document.body.textContent).not.toContain('过期产品')
  })

  it('数量越界或位置为空时阻止入库并标记字段', async () => {
    const wrapper = await render()
    wrapper.findAllComponents(ElSelect)[2]!.vm.$emit('update:modelValue', 'location-1')
    fillQuantity('5'); await flushPromises()
    findButton('确认入库').click(); await flushPromises()
    expect(document.body.textContent).toContain('最多可入库 4')
    expect(document.querySelector('.quantity-input.is-invalid')).not.toBeNull()
    fillQuantity('1.5'); await flushPromises()
    findButton('确认入库').click(); await flushPromises()
    expect(document.body.textContent).toContain('须为正整数')
    fillQuantity('2')
    const location = document.querySelector('.location-input input') as HTMLInputElement
    location.value = ' '; location.dispatchEvent(new Event('input', { bubbles: true }))
    await flushPromises(); findButton('确认入库').click(); await flushPromises()
    expect(document.body.textContent).toContain('入库位置不能为空')
    expect(apiMocks.createReceipt).not.toHaveBeenCalled()
  })

  it('拒绝不属于所选仓库库区的库位', async () => {
    const wrapper = await render()
    fillQuantity('2')
    wrapper.findAllComponents(ElSelect)[2]!.vm.$emit('update:modelValue', 'foreign-location')
    await flushPromises(); findButton('确认入库').click(); await flushPromises()
    expect(document.querySelector('.finished-destination.is-invalid')).not.toBeNull()
    expect(apiMocks.createReceipt).not.toHaveBeenCalled()
  })

  it('提交期间锁定位置和关闭操作，重复点击只提交一次', async () => {
    let complete!: (value: unknown) => void
    apiMocks.createReceipt.mockImplementationOnce(() => new Promise(resolve => { complete = resolve }))
    const wrapper = await render()
    fillQuantity('2')
    wrapper.findAllComponents(ElSelect)[2]!.vm.$emit('update:modelValue', 'location-1')
    await flushPromises(); findButton('确认入库').click(); await flushPromises()
    findButton('确认入库').click()
    expect(apiMocks.createReceipt).toHaveBeenCalledTimes(1)
    expect(wrapper.findAllComponents(ElSelect).every(item => item.props('disabled'))).toBe(true)
    expect(findButton('取消').disabled).toBe(true)
    wrapper.findComponent(AppWindowDialog).vm.$emit('update:modelValue', false)
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
    complete({ receipt_id: 'receipt-1', receipt_number: 'RK-1' }); await flushPromises()
    expect(wrapper.emitted('created')).toHaveLength(1)
    expect(wrapper.emitted('update:modelValue')?.[0]).toEqual([false])
  })

  it('库存冲突保留输入并允许重试，不假报成功', async () => {
    apiMocks.createReceipt.mockRejectedValueOnce(apiError(409))
    const wrapper = await render()
    fillQuantity('2')
    wrapper.findAllComponents(ElSelect)[2]!.vm.$emit('update:modelValue', 'location-1')
    await flushPromises(); findButton('确认入库').click(); await flushPromises()
    expect(document.body.textContent).toContain('库存已变化')
    expect((document.querySelector('.quantity-input input') as HTMLInputElement).value).toBe('2')
    expect(wrapper.emitted('created')).toBeUndefined()
    expect(findButton('确认入库').disabled).toBe(true)
    expect(findButton('重新加载')).not.toBeNull()
    apiMocks.fetchEligible.mockResolvedValueOnce({
      data: [{ ...eligibleRow, cumulative_received: 3, remaining_quantity: 3 }],
      meta: { page: 1, page_size: 100, total: 1, total_pages: 1 },
    })
    findButton('重新加载').click(); await flushPromises()
    expect(findButton('确认入库').disabled).toBe(false)
    expect(document.body.textContent).toContain('SYGJ-20260902-031')
    fillQuantity('2')
    wrapper.findAllComponents(ElSelect)[2]!.vm.$emit('update:modelValue', 'location-1')
    await flushPromises(); findButton('确认入库').click(); await flushPromises()
    expect(apiMocks.createReceipt).toHaveBeenCalledTimes(2)
    expect(apiMocks.createReceipt.mock.calls[1]?.[0]?.[0]).toMatchObject({
      sample_item_id: 'sample-item-1',
      received_quantity: 2,
      expected_cumulative_received: 3,
    })
    expect(wrapper.emitted('created')).toHaveLength(1)
  })
})
