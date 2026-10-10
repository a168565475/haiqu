import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElSelect } from 'element-plus'
import { AxiosError } from 'axios'
import { createPinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useAuthStore } from '@/stores/auth'
import SampleOutboundCreateDialog from './SampleOutboundCreateDialog.vue'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
enableAutoUnmount(afterEach)

const apiMocks = vi.hoisted(() => ({
  fetchEligible: vi.fn(),
  createOutbound: vi.fn(),
}))

vi.mock('@/api/samples', () => ({
  fetchSampleOutboundEligible: apiMocks.fetchEligible,
  createSampleOutbound: apiMocks.createOutbound,
}))

const eligibleRow = {
  inventory_line_id: 'inventory-line-1',
  receipt_number: 'RK-20260901-001',
  sample_request_number: 'SYGJ-20260828-016',
  product_category: '户外桌椅',
  product_name: '铝框休闲椅',
  specification: '620×680',
  color: '岩灰',
  available_quantity: 4,
  location: '样品库',
}

function findButton(label: string): HTMLButtonElement {
  const button = Array.from(document.body.querySelectorAll('button'))
    .find((item) => item.textContent?.trim() === label)
  if (!(button instanceof HTMLButtonElement)) throw new Error(`未找到按钮：${label}`)
  return button
}

async function render(permissions = ['samples.add_sampleinventoryoutbound']) {
  const pinia = createPinia()
  useAuthStore(pinia).user = { id: 1, username: 'qa', display_name: '验收员', is_superuser: false, employee: null, permissions, data_scope: 'ALL' }
  const wrapper = mount(SampleOutboundCreateDialog, { attachTo: document.body, props: { modelValue: true }, global: { plugins: [pinia, ElementPlus] } })
  await flushPromises(); await flushPromises()
  return wrapper
}

function apiError(status: number) {
  return new AxiosError('服务异常', undefined, undefined, undefined, { status, data: { error: { message: '服务异常' } } } as never)
}

async function inputValue(selector: string, value: string) {
  const input = document.querySelector(`.sample-outbound-create-dialog ${selector} input`) as HTMLInputElement
  expect(input).not.toBeNull()
  input.value = value; input.dispatchEvent(new Event('input', { bubbles: true })); await flushPromises()
}

async function selectRow() {
  const checkbox = document.querySelector('.sample-outbound-create-dialog .el-checkbox') as HTMLElement
  checkbox.click(); await flushPromises()
}

async function setMethod(wrapper: Awaited<ReturnType<typeof render>>, method: string) {
  const select = wrapper.findComponent(ElSelect)
  select.vm.$emit('update:modelValue', method); select.vm.$emit('change', method); await flushPromises()
}

describe('SampleOutboundCreateDialog', () => {
  beforeEach(() => {
    apiMocks.fetchEligible.mockReset().mockResolvedValue({
      data: [eligibleRow],
      meta: { page: 1, page_size: 100, total: 1, total_pages: 1 },
    })
    apiMocks.createOutbound.mockReset().mockResolvedValue({
      outbound_id: 'outbound-1',
      outbound_number: 'CK-202609-000001',
      operated_by: '陈方煜',
      operated_at: '2026-09-02T10:00:00+08:00',
      line_count: 1,
    })
  })

  afterEach(() => {
    document.body.innerHTML = ''
  })

  it('无权限不读取候选并禁止提交', async () => {
    await render([])
    expect(apiMocks.fetchEligible).not.toHaveBeenCalled()
    expect(findButton('确认出库').disabled).toBe(true)
  })

  it('读取全部候选页去重，后页失败不展示部分结果', async () => {
    apiMocks.fetchEligible.mockResolvedValueOnce({ data: [eligibleRow], meta: { total_pages: 2 } })
      .mockResolvedValueOnce({ data: [eligibleRow, { ...eligibleRow, inventory_line_id: 'second', product_name: '后页产品' }], meta: { total_pages: 2 } })
    const wrapper = await render()
    expect(apiMocks.fetchEligible).toHaveBeenLastCalledWith(2)
    expect(document.querySelectorAll('.sample-outbound-create-dialog .el-table__row')).toHaveLength(2)
    await wrapper.setProps({ modelValue: false })
    apiMocks.fetchEligible.mockResolvedValueOnce({ data: [eligibleRow], meta: { total_pages: 2 } }).mockRejectedValueOnce(apiError(503))
    await wrapper.setProps({ modelValue: true }); await flushPromises()
    expect(findButton('确认出库').disabled).toBe(true)
    expect(document.querySelectorAll('.sample-outbound-create-dialog .el-table__row')).toHaveLength(0)
  })

  it('关闭重开后旧响应不会覆盖新候选', async () => {
    let resolveOld!: (value: unknown) => void
    apiMocks.fetchEligible.mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve }))
    const wrapper = await render()
    await wrapper.setProps({ modelValue: false }); await wrapper.setProps({ modelValue: true }); await flushPromises()
    resolveOld({ data: [{ ...eligibleRow, product_name: '旧候选' }], meta: { total_pages: 1 } }); await flushPromises()
    expect(document.body.textContent).not.toContain('旧候选')
    expect(document.body.textContent).toContain(eligibleRow.product_name)
  })

  it('加载失败可以重试为空态，空态不能出库', async () => {
    apiMocks.fetchEligible.mockRejectedValueOnce(apiError(503))
    await render()
    expect(findButton('确认出库').disabled).toBe(true)
    apiMocks.fetchEligible.mockResolvedValueOnce({ data: [], meta: { total_pages: 1 } })
    findButton('重新加载').click(); await flushPromises()
    expect(document.body.textContent).toContain('暂无可出库样品')
    expect(findButton('确认出库').disabled).toBe(true)
  })

  it('邮寄须填写快递信息，切换方式清除不适用字段，其他须备注', async () => {
    const wrapper = await render(); await selectRow(); await inputValue('.quantity-input', '2')
    await setMethod(wrapper, 'MERCHANDISER_MAIL')
    findButton('确认出库').click(); await flushPromises()
    expect(document.body.textContent).toContain('邮寄需填写快递公司')
    expect(document.body.textContent).toContain('邮寄需填写快递单号')
    expect(document.querySelector('.courier-input.is-invalid')).not.toBeNull()
    expect(document.querySelector('.delivery-input.is-invalid')).not.toBeNull()
    await inputValue('.courier-input', ' 顺丰 '); await inputValue('.delivery-input', ' SF123 ')
    await setMethod(wrapper, 'OTHER')
    expect(document.querySelector('.courier-input')).toBeNull()
    findButton('确认出库').click(); await flushPromises()
    expect(document.body.textContent).toContain('其他方式需填写备注')
    await inputValue('.remark-input', ' 展会使用 ')
    findButton('确认出库').click(); await flushPromises()
    expect(apiMocks.createOutbound).toHaveBeenCalledWith([expect.objectContaining({ outbound_method: 'OTHER', courier_company: '', tracking_number: '', remark: '展会使用', expected_available_quantity: 4 })])
  })

  it('邮寄提交保留去空格的快递公司和单号', async () => {
    const wrapper = await render(); await selectRow(); await inputValue('.quantity-input', '1')
    await setMethod(wrapper, 'MERCHANDISER_MAIL')
    await inputValue('.courier-input', ' 顺丰 '); await inputValue('.delivery-input', ' SF123 ')
    findButton('确认出库').click(); await flushPromises()
    expect(apiMocks.createOutbound).toHaveBeenCalledWith([expect.objectContaining({ outbound_method: 'MERCHANDISER_MAIL', courier_company: '顺丰', tracking_number: 'SF123', remark: '' })])
  })

  it('往返切换出库方式会清空不适用字段', async () => {
    const wrapper = await render(); await selectRow(); await inputValue('.quantity-input', '1')
    await setMethod(wrapper, 'MERCHANDISER_MAIL')
    await inputValue('.courier-input', '顺丰'); await inputValue('.delivery-input', 'SF123')
    await setMethod(wrapper, 'OTHER')
    await setMethod(wrapper, 'MERCHANDISER_MAIL')
    expect((document.querySelector('.courier-input input') as HTMLInputElement).value).toBe('')
    expect((document.querySelector('.delivery-input input') as HTMLInputElement).value).toBe('')

    await setMethod(wrapper, 'OTHER'); await inputValue('.remark-input', '展会使用')
    await setMethod(wrapper, 'MERCHANDISER_MAIL')
    await setMethod(wrapper, 'OTHER')
    expect((document.querySelector('.remark-input input') as HTMLInputElement).value).toBe('')

    await setMethod(wrapper, 'SALESPERSON_CARRY')
    findButton('确认出库').click(); await flushPromises()
    expect(apiMocks.createOutbound).toHaveBeenCalledWith([expect.objectContaining({
      outbound_method: 'SALESPERSON_CARRY',
      courier_company: '',
      tracking_number: '',
      remark: '',
    })])
  })

  it('数量越界、小数和无效方式均不能提交', async () => {
    const wrapper = await render(); await selectRow(); await setMethod(wrapper, 'SALESPERSON_CARRY')
    for (const value of ['5', '0', '1.5', '']) {
      await inputValue('.quantity-input', value); findButton('确认出库').click(); await flushPromises()
      expect(document.querySelector('.quantity-input.is-invalid')).not.toBeNull()
    }
    await inputValue('.quantity-input', '1'); await setMethod(wrapper, 'UNKNOWN')
    findButton('确认出库').click(); await flushPromises()
    expect(document.body.textContent).toContain('请选择出库方式')
    expect(document.querySelector('.method-select.is-invalid')).not.toBeNull()
    expect(apiMocks.createOutbound).not.toHaveBeenCalled()
  })

  it('单次超过100条提示分批，不发送出库请求', async () => {
    apiMocks.fetchEligible.mockResolvedValueOnce({ data: Array.from({ length: 101 }, (_, index) => ({ ...eligibleRow, inventory_line_id: `row-${index}` })), meta: { total_pages: 1 } })
    const wrapper = await render()
    wrapper.findAllComponents({ name: 'ElCheckbox' }).forEach(item => item.vm.$emit('update:modelValue', true))
    await flushPromises(); findButton('确认出库').click(); await flushPromises()
    expect(document.body.textContent).toContain('一次最多提交 100 条')
    expect(apiMocks.createOutbound).not.toHaveBeenCalled()
  }, 15000) // 101 行真实 Select 在 DOM 模拟环境中的挂载时间高于默认 5 秒。

  it('提交中锁定输入、关闭和重复提交；成功后才关闭', async () => {
    let resolveSubmit!: (value: unknown) => void
    apiMocks.createOutbound.mockImplementationOnce(() => new Promise(resolve => { resolveSubmit = resolve }))
    const wrapper = await render(); await selectRow(); await inputValue('.quantity-input', '1'); await setMethod(wrapper, 'SALESPERSON_CARRY')
    findButton('确认出库').click(); findButton('确认出库').click(); await flushPromises()
    expect(apiMocks.createOutbound).toHaveBeenCalledTimes(1)
    expect(findButton('取消').disabled).toBe(true)
    expect((document.querySelector('.quantity-input input') as HTMLInputElement).disabled).toBe(true)
    expect(wrapper.findComponent(ElSelect).props('disabled')).toBe(true)
    wrapper.findComponent(AppWindowDialog).vm.$emit('update:modelValue', false); await flushPromises()
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
    resolveSubmit({ outbound_number: 'CK-QA' }); await flushPromises()
    expect(wrapper.emitted('update:modelValue')).toEqual([[false]])
  })

  it('库存冲突保留输入，重新加载后才能再次提交', async () => {
    apiMocks.createOutbound.mockRejectedValueOnce(apiError(409))
    const wrapper = await render(); await selectRow(); await inputValue('.quantity-input', '1'); await setMethod(wrapper, 'SALESPERSON_CARRY')
    findButton('确认出库').click(); await flushPromises()
    expect(wrapper.emitted('created')).toBeUndefined()
    expect(document.body.textContent).toContain('库存已变化')
    expect((document.querySelector('.quantity-input input') as HTMLInputElement).value).toBe('1')
    expect(findButton('确认出库').disabled).toBe(true)
    apiMocks.fetchEligible.mockResolvedValueOnce({
      data: [{ ...eligibleRow, available_quantity: 3 }],
      meta: { page: 1, page_size: 100, total: 1, total_pages: 1 },
    })
    findButton('重新加载').click(); await flushPromises()
    expect(findButton('确认出库').disabled).toBe(false)
    expect((document.querySelector('.quantity-input input') as HTMLInputElement).value).toBe('')
    await selectRow(); await inputValue('.quantity-input', '1'); await setMethod(wrapper, 'SALESPERSON_CARRY')
    findButton('确认出库').click(); await flushPromises()
    expect(apiMocks.createOutbound).toHaveBeenCalledTimes(2)
    expect(apiMocks.createOutbound.mock.calls[1]?.[0]?.[0]).toMatchObject({
      inventory_line_id: 'inventory-line-1',
      outbound_quantity: 1,
      expected_available_quantity: 3,
    })
    expect(wrapper.emitted('created')).toHaveLength(1)
  })

  it('加载可用库存并按业务员带走方式提交出库参数', async () => {
    const pinia = createPinia()
    const authStore = useAuthStore(pinia)
    authStore.user = {
      id: 1,
      username: 'chenfangyu',
      display_name: '陈方煜',
      is_superuser: false,
      employee: null,
      permissions: ['samples.add_sampleinventoryoutbound'],
      data_scope: 'ALL',
    }
    const wrapper = mount(SampleOutboundCreateDialog, {
      attachTo: document.body,
      props: { modelValue: true },
      global: { plugins: [pinia, ElementPlus] },
    })

    await flushPromises()
    await flushPromises()

    const dialogComponent = wrapper.findComponent(AppWindowDialog)
    expect(dialogComponent.exists()).toBe(true)
    expect(dialogComponent.props('title')).toBe('批量出库样品')

    const dialog = document.body.querySelector('.sample-outbound-create-dialog')
    expect(dialog?.textContent).toContain('批量出库样品')
    expect(dialog?.querySelector('.batch-dialog-subtitle')).toBeNull()
    expect(dialog?.querySelector('.document-summary')).toBeNull()
    expect(dialog?.querySelector('.rule-alert')).toBeNull()
    expect(dialog?.querySelector('.validation-bar')).toBeNull()
    expect(dialog?.querySelector('.state-note')).toBeNull()
    expect(dialog?.textContent).toContain('RK-20260901-001')
    expect(dialog?.textContent).toContain('铝框休闲椅 / 620×680 / 岩灰')

    findButton('确认出库').click()
    await flushPromises()
    expect(document.body.textContent).toContain('未选择任何数据')
    expect(apiMocks.createOutbound).not.toHaveBeenCalled()

    const checkbox = document.body.querySelector(
      '.sample-outbound-create-dialog .el-table__body-wrapper .el-checkbox',
    ) as HTMLElement | null
    checkbox?.click()
    await flushPromises()

    const quantityInput = document.body.querySelector(
      '.sample-outbound-create-dialog .quantity-input input',
    ) as HTMLInputElement | null
    if (!quantityInput) throw new Error('未找到出库数量输入框')
    quantityInput.value = '1'
    quantityInput.dispatchEvent(new Event('input', { bubbles: true }))

    const methodTrigger = document.body.querySelector(
      '.sample-outbound-create-dialog .method-select .el-select__wrapper',
    ) as HTMLElement | null
    methodTrigger?.click()
    await flushPromises()
    const carryOption = Array.from(document.body.querySelectorAll('.el-select-dropdown__item'))
      .find((item) => item.textContent?.trim() === '业务员带走') as HTMLElement | undefined
    carryOption?.click()
    await flushPromises()

    findButton('确认出库').click()
    await flushPromises()

    expect(apiMocks.createOutbound).toHaveBeenCalledWith([
      {
        inventory_line_id: 'inventory-line-1',
        outbound_quantity: 1,
        outbound_method: 'SALESPERSON_CARRY',
        courier_company: '',
        tracking_number: '',
        remark: '',
        expected_available_quantity: 4,
      },
    ])
    expect(wrapper.emitted('created')?.[0]?.[0]).toMatchObject({
      outbound_number: 'CK-202609-000001',
    })
  })
})
