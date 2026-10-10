import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { AxiosError } from 'axios'
import { createPinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useAuthStore } from '@/stores/auth'
import SampleLoanCreateDialog from './SampleLoanCreateDialog.vue'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
enableAutoUnmount(afterEach)

const apiMocks = vi.hoisted(() => ({
  fetchEligible: vi.fn(),
  createLoan: vi.fn(),
}))

vi.mock('@/api/samples', () => ({
  fetchSampleLoanEligible: apiMocks.fetchEligible,
  createSampleLoan: apiMocks.createLoan,
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

function enterValue(selector: string, value: string) {
  const input = document.body.querySelector(selector) as HTMLInputElement | null
  if (!input) throw new Error(`未找到输入框：${selector}`)
  input.value = value
  input.dispatchEvent(new Event('input', { bubbles: true }))
}

async function render(permissions = ['samples.add_sampleinventoryloan']) {
  const pinia = createPinia()
  useAuthStore(pinia).user = { id: 1, username: 'qa', display_name: '验收员', is_superuser: false, employee: null, permissions, data_scope: 'ALL' }
  const wrapper = mount(SampleLoanCreateDialog, { attachTo: document.body, props: { modelValue: true }, global: { plugins: [pinia, ElementPlus] } })
  await flushPromises(); await flushPromises()
  return wrapper
}

function apiError(status: number) {
  return new AxiosError('服务异常', undefined, undefined, undefined, { status, data: { error: { message: '服务异常' } } } as never)
}

async function fillRow(quantity = '1', borrower = ' 验收员 ', purpose = ' 客户确认 ') {
  const checkbox = document.querySelector('.sample-loan-create-dialog .el-checkbox') as HTMLElement
  checkbox.click(); await flushPromises()
  enterValue('.sample-loan-create-dialog .quantity-input input', quantity)
  enterValue('.sample-loan-create-dialog .borrower-input input', borrower)
  enterValue('.sample-loan-create-dialog .purpose-input input', purpose)
  await flushPromises()
}

describe('SampleLoanCreateDialog', () => {
  beforeEach(() => {
    apiMocks.fetchEligible.mockReset().mockResolvedValue({
      data: [eligibleRow],
      meta: { page: 1, page_size: 100, total: 1, total_pages: 1 },
    })
    apiMocks.createLoan.mockReset().mockResolvedValue({
      loan_id: 'loan-1',
      loan_number: 'JC-202609-000001',
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
    expect(findButton('确认借出').disabled).toBe(true)
  })

  it('候选分页去重，后页失败不保留部分结果', async () => {
    apiMocks.fetchEligible.mockResolvedValueOnce({ data: [eligibleRow], meta: { total_pages: 2 } })
      .mockResolvedValueOnce({ data: [eligibleRow, { ...eligibleRow, inventory_line_id: 'second', product_name: '后页产品' }], meta: { total_pages: 2 } })
    const wrapper = await render()
    expect(apiMocks.fetchEligible).toHaveBeenLastCalledWith(2)
    expect(document.querySelectorAll('.sample-loan-create-dialog .el-table__row')).toHaveLength(2)
    await wrapper.setProps({ modelValue: false })
    apiMocks.fetchEligible.mockResolvedValueOnce({ data: [eligibleRow], meta: { total_pages: 2 } }).mockRejectedValueOnce(apiError(503))
    await wrapper.setProps({ modelValue: true }); await flushPromises()
    expect(findButton('确认借出').disabled).toBe(true)
    expect(document.querySelectorAll('.sample-loan-create-dialog .el-table__row')).toHaveLength(0)
  })

  it('关闭重开后旧请求不能覆盖新候选', async () => {
    let resolveOld!: (value: unknown) => void
    apiMocks.fetchEligible.mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve }))
    const wrapper = await render()
    await wrapper.setProps({ modelValue: false }); await wrapper.setProps({ modelValue: true }); await flushPromises()
    resolveOld({ data: [{ ...eligibleRow, product_name: '旧候选' }], meta: { total_pages: 1 } }); await flushPromises()
    expect(document.body.textContent).not.toContain('旧候选')
    expect(document.body.textContent).toContain(eligibleRow.product_name)
  })

  it('加载失败重试为空态，空态不能借出', async () => {
    apiMocks.fetchEligible.mockRejectedValueOnce(apiError(503))
    await render()
    expect(findButton('确认借出').disabled).toBe(true)
    apiMocks.fetchEligible.mockResolvedValueOnce({ data: [], meta: { total_pages: 1 } })
    findButton('重新加载').click(); await flushPromises()
    expect(document.body.textContent).toContain('暂无可借出样品')
    expect(findButton('确认借出').disabled).toBe(true)
  })

  it('数量越界、小数、空借用人和空用途不能提交', async () => {
    await render(); await fillRow('5', ' ', ' ')
    findButton('确认借出').click(); await flushPromises()
    expect(document.body.textContent).toContain('数量超过可用库存 4')
    expect(document.body.textContent).toContain('借用人必填')
    expect(document.body.textContent).toContain('用途或备注必填')
    expect(document.querySelector('.borrower-input.is-invalid')).not.toBeNull()
    expect(document.querySelector('.purpose-input.is-invalid')).not.toBeNull()
    for (const value of ['0', '1.5', '']) {
      enterValue('.quantity-input input', value); await flushPromises()
      findButton('确认借出').click(); await flushPromises()
      expect(document.querySelector('.quantity-input.is-invalid')).not.toBeNull()
    }
    expect(apiMocks.createLoan).not.toHaveBeenCalled()
  })

  it('单次超过100条提示分批，不发送借出请求', async () => {
    apiMocks.fetchEligible.mockResolvedValueOnce({ data: Array.from({ length: 101 }, (_, index) => ({ ...eligibleRow, inventory_line_id: `row-${index}` })), meta: { total_pages: 1 } })
    const wrapper = await render()
    wrapper.findAllComponents({ name: 'ElCheckbox' }).forEach(item => item.vm.$emit('update:modelValue', true))
    await flushPromises(); findButton('确认借出').click(); await flushPromises()
    expect(document.body.textContent).toContain('一次最多提交 100 条')
    expect(apiMocks.createLoan).not.toHaveBeenCalled()
  }, 15000)

  it('提交期间锁定关闭及输入，防止重复提交并保留去空格参数', async () => {
    let resolveSubmit!: (value: unknown) => void
    apiMocks.createLoan.mockImplementationOnce(() => new Promise(resolve => { resolveSubmit = resolve }))
    const wrapper = await render(); await fillRow()
    findButton('确认借出').click(); findButton('确认借出').click(); await flushPromises()
    expect(apiMocks.createLoan).toHaveBeenCalledTimes(1)
    expect(apiMocks.createLoan).toHaveBeenCalledWith([expect.objectContaining({ borrower_name: '验收员', purpose_note: '客户确认', expected_available_quantity: 4 })])
    expect(findButton('取消').disabled).toBe(true)
    expect([...document.querySelectorAll('.sample-loan-create-dialog .line-input input')].every(input => (input as HTMLInputElement).disabled)).toBe(true)
    wrapper.findComponent(AppWindowDialog).vm.$emit('update:modelValue', false); await flushPromises()
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
    resolveSubmit({ loan_number: 'JC-QA' }); await flushPromises()
    expect(wrapper.emitted('update:modelValue')).toEqual([[false]])
  })

  it('库存冲突保留输入，重新加载后才能重试', async () => {
    apiMocks.createLoan.mockRejectedValueOnce(apiError(409))
    const wrapper = await render(); await fillRow()
    findButton('确认借出').click(); await flushPromises()
    expect(wrapper.emitted('created')).toBeUndefined()
    expect(document.body.textContent).toContain('库存已变化')
    expect((document.querySelector('.quantity-input input') as HTMLInputElement).value).toBe('1')
    expect(findButton('确认借出').disabled).toBe(true)
    apiMocks.fetchEligible.mockResolvedValueOnce({
      data: [{ ...eligibleRow, available_quantity: 3 }],
      meta: { page: 1, page_size: 100, total: 1, total_pages: 1 },
    })
    findButton('重新加载').click(); await flushPromises()
    expect(findButton('确认借出').disabled).toBe(false)
    expect((document.querySelector('.quantity-input input') as HTMLInputElement).value).toBe('')
    await fillRow('1', '验收员', '客户确认')
    findButton('确认借出').click(); await flushPromises()
    expect(apiMocks.createLoan).toHaveBeenCalledTimes(2)
    expect(apiMocks.createLoan.mock.calls[1]?.[0]?.[0]).toMatchObject({
      inventory_line_id: 'inventory-line-1',
      loan_quantity: 1,
      expected_available_quantity: 3,
    })
    expect(wrapper.emitted('created')).toHaveLength(1)
  })

  it('加载可用库存，阻止空提交并提交完整借出参数', async () => {
    const pinia = createPinia()
    const authStore = useAuthStore(pinia)
    authStore.user = {
      id: 1,
      username: 'chenfangyu',
      display_name: '陈方煜',
      is_superuser: false,
      employee: null,
      permissions: ['samples.add_sampleinventoryloan'],
      data_scope: 'ALL',
    }
    const wrapper = mount(SampleLoanCreateDialog, {
      attachTo: document.body,
      props: { modelValue: true },
      global: { plugins: [pinia, ElementPlus] },
    })

    await flushPromises()
    await flushPromises()

    const dialogComponent = wrapper.findComponent(AppWindowDialog)
    expect(dialogComponent.exists()).toBe(true)
    expect(dialogComponent.props('title')).toBe('批量借出样品')

    const dialog = document.body.querySelector('.sample-loan-create-dialog')
    expect(dialog?.textContent).toContain('批量借出样品')
    expect(dialog?.querySelector('.batch-dialog-subtitle')).toBeNull()
    expect(dialog?.querySelector('.document-summary')).toBeNull()
    expect(dialog?.querySelector('.rule-alert')).toBeNull()
    expect(dialog?.querySelector('.validation-bar')).toBeNull()
    expect(dialog?.querySelector('.state-note')).toBeNull()
    expect(dialog?.textContent).toContain('RK-20260901-001')
    expect(dialog?.textContent).toContain('铝框休闲椅 / 620×680 / 岩灰')
    expect(dialog?.textContent).not.toContain('不包含预计归还日、归还按钮和归还状态')

    findButton('确认借出').click()
    await flushPromises()
    expect(document.body.textContent).toContain('未选择任何数据')
    expect(apiMocks.createLoan).not.toHaveBeenCalled()

    const checkbox = document.body.querySelector(
      '.sample-loan-create-dialog .el-table__body-wrapper .el-checkbox',
    ) as HTMLElement | null
    checkbox?.click()
    await flushPromises()

    enterValue('.sample-loan-create-dialog .quantity-input input', '2')
    enterValue('.sample-loan-create-dialog .borrower-input input', '王立新')
    enterValue('.sample-loan-create-dialog .purpose-input input', '客户现场确认材质')
    await flushPromises()

    findButton('确认借出').click()
    await flushPromises()

    expect(apiMocks.createLoan).toHaveBeenCalledWith([
      {
        inventory_line_id: 'inventory-line-1',
        loan_quantity: 2,
        borrower_name: '王立新',
        purpose_note: '客户现场确认材质',
        expected_available_quantity: 4,
      },
    ])
    expect(wrapper.emitted('created')?.[0]?.[0]).toMatchObject({
      loan_number: 'JC-202609-000001',
    })
  })
})
