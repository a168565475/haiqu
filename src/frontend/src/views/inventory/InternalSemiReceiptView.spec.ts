import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElDatePicker, ElSelect } from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import InternalSemiReceiptView from './InternalSemiReceiptView.vue'
import type { ReceiptPreview } from '@/types/internalReceipt'

const api = vi.hoisted(() => ({ preview: vi.fn(), confirm: vi.fn() }))
vi.mock('vue-router', () => ({
  useRoute: () => ({ query: { schedule_product_id: 'plan-1', plan_category: 'SEWING' } }),
  useRouter: () => ({ push: vi.fn(), back: vi.fn() }),
}))
vi.mock('@/api/internalReceipts', () => ({
  fetchReceiptPreview: api.preview,
  confirmInternalReceipt: api.confirm,
}))

const preview: ReceiptPreview = {
  schedule_product_id: 'plan-1', plan_category: 'SEWING', etag: '"receipt-1"',
  production_order: 'HT-001', product: '折叠椅', order_quantity: '100', actor: '仓管员',
  receipt_date: '2026-09-29', excluded: [],
  zones: [{ id: 'zone-1', warehouse: '半成品仓', name: '一楼' }],
  lines: [
    { bom_line_id: 'line-1', component_key: 'part-1', usage: '1', stage: '车缝完成', required: '100', received: '0', can_receive: '100', input_remaining: '100', input_supported: '100', attributes: { part_name: '椅套', category: '裁片', material: '涤纶', specification: '600D', color: '黑色', unit_name: '套' } },
    { bom_line_id: 'line-2', component_key: 'part-2', usage: '1', stage: '车缝完成', required: '100', received: '0', can_receive: '100', input_remaining: '100', input_supported: '100', attributes: { part_name: '靠背套', category: '裁片', material: '涤纶', specification: '600D', color: '黑色', unit_name: '套' } },
    { bom_line_id: 'line-3', component_key: 'part-3', usage: '1', stage: '车缝完成', required: '100', received: '0', can_receive: '100', input_remaining: '100', input_supported: '100', attributes: { part_name: '座套', category: '裁片', material: '涤纶', specification: '600D', color: '黑色', unit_name: '套' } },
  ],
}

const wrappers: ReturnType<typeof mount>[] = []

beforeEach(() => {
  vi.resetAllMocks()
  sessionStorage.clear()
  api.preview.mockResolvedValue(structuredClone(preview))
  api.confirm.mockResolvedValue({ receipt_number: 'RK-001' })
})
afterEach(() => wrappers.splice(0).forEach(wrapper => wrapper.unmount()))

describe('车缝半成品入库', () => {
  it('投入不核算时仍按服务端剩余套数提交，并说明累计入库口径', async () => {
    const data = structuredClone(preview)
    data.lines[0] = { ...data.lines[0]!, received: '25', can_receive: '75', input_remaining: null, input_supported: null }
    api.preview.mockResolvedValue(data)
    const wrapper = mount(InternalSemiReceiptView, { global: { plugins: [ElementPlus] } })
    wrappers.push(wrapper)
    await flushPromises()

    expect(wrapper.text()).toContain('按订单与 BOM 套数净需求，扣除累计入库、车缝直发及待发预留')
    expect(wrapper.text()).not.toContain('投入面料按米核算')
    expect(wrapper.find('[title="应入库 100 套，厂内及外发累计已入库 25 套；剩余可入已扣车缝直发及待发预留"]').text()).toBe('75')
    expect(wrapper.findAll('[title]').some(item => /null|NaN|已领投入/.test(item.attributes('title') || ''))).toBe(false)
    await wrapper.get('input[aria-label="椅套本次入库"]').setValue('75')
    await (wrapper.vm as any).submit()
    expect(api.confirm.mock.calls[0]![0].lines).toEqual([{ bom_line_id: 'line-1', quantity: '75' }])
  })

  it('重填只清空入库数量，保留日期、仓库和备注，不提交请求', async () => {
    const wrapper = mount(InternalSemiReceiptView, { global: { plugins: [ElementPlus] } })
    wrappers.push(wrapper)
    await flushPromises()
    await wrapper.get('input[aria-label="椅套本次入库"]').setValue('5')
    await wrapper.get('textarea[aria-label="入库备注"]').setValue('放入一楼')
    await wrapper.findAll('button').find(button => button.text() === '重填')!.trigger('click')

    expect((wrapper.get('input[aria-label="椅套本次入库"]').element as HTMLInputElement).value).toBe('')
    expect((wrapper.vm as any).receiptDate).toBe('2026-09-29')
    expect((wrapper.vm as any).zoneId).toBe('zone-1')
    expect((wrapper.vm as any).remark).toBe('放入一楼')
    expect(api.confirm).not.toHaveBeenCalled()
  })

  it('空明细仍展示空态和禁用确认，不显示金工专属数量列', async () => {
    api.preview.mockResolvedValue({ ...structuredClone(preview), lines: [] })
    const wrapper = mount(InternalSemiReceiptView, { global: { plugins: [ElementPlus] } })
    wrappers.push(wrapper)
    await flushPromises()

    expect(wrapper.text()).toContain('暂无可入库部位')
    expect(wrapper.findAll('th').map(cell => cell.text())).toEqual(['部位', '材质', '规格', '颜色', '加工阶段', '单位', '单个用量', '应入库', '已入库', '剩余可入', '本次入库（套）'])
    expect(wrapper.findAll('button').find(button => button.text() === '确认入库')!.attributes('disabled')).toBeDefined()
  })

  it('共享日期与库区组件仍提交日期字符串，切换仓库时选择对应库区', async () => {
    const data = structuredClone(preview)
    data.zones.push({ id: 'zone-2', warehouse: '二号仓', name: '二楼' })
    api.preview.mockResolvedValue(data)
    const wrapper = mount(InternalSemiReceiptView, { global: { plugins: [ElementPlus] } })
    wrappers.push(wrapper)
    await flushPromises()

    wrapper.getComponent(ElDatePicker).vm.$emit('update:modelValue', '2026-10-20')
    const warehouseSelect = wrapper.findAllComponents(ElSelect)[0]!
    warehouseSelect.vm.$emit('update:modelValue', '二号仓')
    warehouseSelect.vm.$emit('change', '二号仓')
    await wrapper.get('input[aria-label="椅套本次入库"]').setValue('5')
    await (wrapper.vm as any).submit()

    expect(api.confirm.mock.calls[0]![0]).toMatchObject({ receipt_date: '2026-10-20', zone_id: 'zone-2' })
  })

  it('待核对请求时共享日期和下拉仍锁定，避免修改原提交', async () => {
    sessionStorage.setItem('internal-receipt-pending:plan-1:SEWING', JSON.stringify({
      etag: '"receipt-1"', payload: { request_id: 'pending-1', schedule_product_id: 'plan-1',
        plan_category: 'SEWING', zone_id: 'zone-1', receipt_date: '2026-09-29', remark: '',
        lines: [{ bom_line_id: 'line-1', quantity: '5' }] },
    }))
    const wrapper = mount(InternalSemiReceiptView, { global: { plugins: [ElementPlus] } })
    wrappers.push(wrapper)
    await flushPromises()

    expect(wrapper.getComponent(ElDatePicker).props('disabled')).toBe(true)
    expect(wrapper.findAllComponents(ElSelect).every(select => select.props('disabled'))).toBe(true)
    expect(wrapper.get('input[aria-label="椅套本次入库"]').attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('核对本次提交')
    expect(api.confirm).not.toHaveBeenCalled()
  })

  it('不显示勾选框，空白和零忽略，仅提交大于零的数量', async () => {
    const wrapper = mount(InternalSemiReceiptView, { global: { plugins: [ElementPlus] } })
    wrappers.push(wrapper)
    await flushPromises()

    expect(wrapper.find('input[type="checkbox"]').exists()).toBe(false)
    await wrapper.get('input[aria-label="靠背套本次入库"]').setValue('0')
    await wrapper.get('input[aria-label="座套本次入库"]').setValue('5')
    await (wrapper.vm as any).submit()

    expect(api.confirm).toHaveBeenCalledTimes(1)
    expect(api.confirm.mock.calls[0]![0].lines).toEqual([{ bom_line_id: 'line-3', quantity: '5' }])
  })

  it('所有数量为空或零时不提交', async () => {
    const wrapper = mount(InternalSemiReceiptView, { global: { plugins: [ElementPlus] } })
    wrappers.push(wrapper)
    await flushPromises()

    await wrapper.get('input[aria-label="靠背套本次入库"]').setValue('0')
    const vm = wrapper.vm as any
    await vm.submit()

    expect(api.confirm).not.toHaveBeenCalled()
    expect(vm.error).toContain('至少填写一项大于 0')
  })

  it.each(['-1', '0.5', '101', '9007199254740992'])('实际输入 %s 时保留数量校验，不提交入库', async quantity => {
    const wrapper = mount(InternalSemiReceiptView, { global: { plugins: [ElementPlus] } })
    wrappers.push(wrapper)
    await flushPromises()

    await wrapper.get('input[aria-label="椅套本次入库"]').setValue(quantity)
    const vm = wrapper.vm as any
    await vm.submit()

    expect(api.confirm).not.toHaveBeenCalled()
    expect(vm.error).toContain('本次入库须为非负整数，且不能超过剩余可入数量')
  })
})
