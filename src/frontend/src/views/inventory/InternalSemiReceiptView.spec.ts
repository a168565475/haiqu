import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElDatePicker, ElSelect } from 'element-plus'
import { AxiosError } from 'axios'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import InternalSemiReceiptView from './InternalSemiReceiptView.vue'
import type { ReceiptPreview } from '@/types/internalReceipt'

const api = vi.hoisted(() => ({ preview: vi.fn(), confirm: vi.fn() }))
const route = vi.hoisted(() => ({ query: { schedule_product_id: 'plan-1', plan_category: 'SEWING' } }))
vi.mock('vue-router', () => ({
  useRoute: () => route,
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
  route.query = { schedule_product_id: 'plan-1', plan_category: 'SEWING' }
  sessionStorage.clear()
  api.preview.mockResolvedValue(structuredClone(preview))
  api.confirm.mockResolvedValue({ receipt_number: 'RK-001' })
})
afterEach(() => wrappers.splice(0).forEach(wrapper => wrapper.unmount()))

describe('车缝半成品入库', () => {
  it('合法来源首次预览被后端400拦截时展示原因且不能提交', async () => {
    route.query.schedule_product_id = '86e0c84b-a809-4689-845b-806012ad342c'
    const message = '生产订单必须处于生产中。'
    api.preview.mockRejectedValue(Object.assign(new AxiosError(message), { response: { status: 400, data: { error: { message } } } }))
    const wrapper = mount(InternalSemiReceiptView, { global: { plugins: [ElementPlus] } })
    wrappers.push(wrapper)
    await flushPromises()
    expect(api.preview).toHaveBeenCalledExactlyOnceWith(route.query.schedule_product_id, 'SEWING')
    expect(wrapper.text()).toContain(message)
    expect(wrapper.findAll('button').find(button => button.text() === '提交待入库')!.attributes('disabled')).toBeDefined()
    await (wrapper.vm as any).submit()
    expect(api.confirm).not.toHaveBeenCalled()
  })
  it.each([400, undefined])('刷新失败（状态 %s）保留草稿但不新提交，恢复后按新额度填写', async status => {
    const wrapper = mount(InternalSemiReceiptView, { global: { plugins: [ElementPlus] } })
    wrappers.push(wrapper)
    await flushPromises()
    const vm = wrapper.vm as any
    await wrapper.get('input[aria-label="椅套本次入库"]').setValue('5')
    await wrapper.get('textarea[aria-label="入库备注"]').setValue('保留草稿')
    const failure = new AxiosError('刷新失败')
    if (status) Object.assign(failure, { response: { status, data: { error: { message: '生产订单必须处于生产中。' } } } })
    api.preview.mockRejectedValueOnce(failure)
    await vm.load()
    await flushPromises()

    expect((wrapper.get('input[aria-label="椅套本次入库"]').element as HTMLInputElement).value).toBe('5')
    expect(vm.remark).toBe('保留草稿')
    expect(vm.receiptDate).toBe('2026-09-29')
    expect(vm.zoneId).toBe('zone-1')
    expect(wrapper.findAll('button').find(button => button.text() === '提交待入库')!.attributes('disabled')).toBeDefined()
    await vm.submit()
    expect(api.confirm).not.toHaveBeenCalled()
    expect(sessionStorage.getItem('internal-receipt-pending:plan-1:SEWING')).toBeNull()

    const refreshed = structuredClone(preview)
    refreshed.etag = '"receipt-2"'
    refreshed.lines[0]!.can_receive = '3'
    api.preview.mockResolvedValueOnce(refreshed)
    await vm.load()
    await flushPromises()
    expect((wrapper.get('input[aria-label="椅套本次入库"]').element as HTMLInputElement).value).toBe('')
    expect(vm.error).toBe('')
    expect(vm.remark).toBe('保留草稿')
    await wrapper.get('input[aria-label="椅套本次入库"]').setValue('4')
    await vm.submit()
    expect(api.confirm).not.toHaveBeenCalled()
    await wrapper.get('input[aria-label="椅套本次入库"]').setValue('3')
    await vm.submit()
    expect(api.confirm).toHaveBeenCalledExactlyOnceWith(expect.objectContaining({
      remark: '保留草稿', lines: [{ bom_line_id: 'line-1', quantity: '3' }],
    }), '"receipt-2"')
  })
  it('刷新等待期间不创建新提交，完成后才允许重新填写', async () => {
    const wrapper = mount(InternalSemiReceiptView, { global: { plugins: [ElementPlus] } })
    wrappers.push(wrapper)
    await flushPromises()
    const vm = wrapper.vm as any
    await wrapper.get('input[aria-label="椅套本次入库"]').setValue('5')
    let complete!: (value: ReceiptPreview) => void
    api.preview.mockImplementationOnce(() => new Promise(resolve => { complete = resolve }))
    const loading = vm.load()
    await flushPromises()
    expect(wrapper.findAll('button').find(button => button.text() === '提交待入库')!.attributes('disabled')).toBeDefined()
    await vm.submit()
    expect(api.confirm).not.toHaveBeenCalled()
    expect(sessionStorage.getItem('internal-receipt-pending:plan-1:SEWING')).toBeNull()
    complete(structuredClone(preview))
    await loading
    await flushPromises()
    expect((wrapper.get('input[aria-label="椅套本次入库"]').element as HTMLInputElement).value).toBe('')
  })
  it('未确认请求重开后预览失败仍能按原编号、内容和版本核对', async () => {
    const saved = { etag: '"original-receipt"', payload: {
      request_id: 'original-request', schedule_product_id: 'plan-1', plan_category: 'SEWING',
      zone_id: 'zone-1', receipt_date: '2026-09-29', remark: '原提交内容',
      lines: [{ bom_line_id: 'line-1', quantity: '5' }],
    } }
    sessionStorage.setItem('internal-receipt-pending:plan-1:SEWING', JSON.stringify(saved))
    api.preview.mockRejectedValue(new AxiosError('预览网络失败'))
    api.confirm.mockRejectedValueOnce(new AxiosError('提交结果仍未确认'))
    const wrapper = mount(InternalSemiReceiptView, { global: { plugins: [ElementPlus] } })
    wrappers.push(wrapper)
    await flushPromises()
    const vm = wrapper.vm as any
    expect(vm.preview).toBeNull()
    expect(wrapper.findAll('button').find(button => button.text() === '核对本次提交')!.attributes('disabled')).toBeUndefined()
    await vm.submit()
    expect(api.confirm).toHaveBeenNthCalledWith(1, saved.payload, saved.etag)
    expect(JSON.parse(sessionStorage.getItem('internal-receipt-pending:plan-1:SEWING')!)).toEqual(saved)
    await vm.submit()
    expect(api.confirm).toHaveBeenNthCalledWith(2, saved.payload, saved.etag)
    expect(sessionStorage.getItem('internal-receipt-pending:plan-1:SEWING')).toBeNull()
  })
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

  it('原请求已删除时展示服务端原因并解锁，主动再提交才使用新编号', async () => {
    const wrapper = mount(InternalSemiReceiptView, { global: { plugins: [ElementPlus] } })
    wrappers.push(wrapper)
    await flushPromises()
    await wrapper.get('input[aria-label="椅套本次入库"]').setValue('5')
    api.confirm.mockRejectedValueOnce(new AxiosError('响应丢失', 'ECONNABORTED'))
    await (wrapper.vm as any).submit()
    const original = api.confirm.mock.calls[0]!
    const message = '本次待入库记录已删除，不能重复提交；如需重新入库，请重新填写。'
    api.confirm.mockRejectedValueOnce(Object.assign(new AxiosError(message), {
      response: { status: 409, data: { error: { code: 'RECEIPT_REQUEST_DELETED', message } } },
    }))
    await flushPromises()
    await wrapper.findAll('button').find(button => button.text() === '核对本次提交')!.trigger('click')
    await flushPromises()

    expect(api.confirm.mock.calls[1]).toEqual(original)
    expect(api.confirm).toHaveBeenCalledTimes(2)
    expect((wrapper.vm as any).pending).toBeNull()
    expect(sessionStorage.getItem('internal-receipt-pending:plan-1:SEWING')).toBeNull()
    expect(wrapper.text()).toContain(message)
    expect(wrapper.get('input[aria-label="椅套本次入库"]').attributes('disabled')).toBeUndefined()
    expect(wrapper.text()).not.toContain('核对本次提交')

    await wrapper.get('input[aria-label="椅套本次入库"]').setValue('3')
    await wrapper.findAll('button').find(button => button.text() === '提交待入库')!.trigger('click')
    await flushPromises()
    expect(api.confirm).toHaveBeenCalledTimes(3)
    expect(api.confirm.mock.calls[2]![0].request_id).not.toBe(original[0].request_id)
    expect(api.confirm.mock.calls[2]![0].lines).toEqual([{ bom_line_id: 'line-1', quantity: '3' }])
  })

  it.each(['CONFLICT', 'RECEIPT_REQUEST_CONFLICT', undefined])('其他409（%s）仍保留原请求和锁定状态', async code => {
    const wrapper = mount(InternalSemiReceiptView, { global: { plugins: [ElementPlus] } })
    wrappers.push(wrapper)
    await flushPromises()
    await wrapper.get('input[aria-label="椅套本次入库"]').setValue('5')
    api.confirm.mockRejectedValueOnce(Object.assign(new AxiosError('请求冲突'), {
      response: { status: 409, data: { error: { code, message: '请求冲突' } } },
    }))
    await (wrapper.vm as any).submit(); await flushPromises()

    expect((wrapper.vm as any).pending?.payload).toEqual(api.confirm.mock.calls[0]![0])
    expect(sessionStorage.getItem('internal-receipt-pending:plan-1:SEWING')).not.toBeNull()
    expect(wrapper.get('input[aria-label="椅套本次入库"]').attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('核对本次提交')
    expect(api.confirm).toHaveBeenCalledTimes(1)
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
    expect(wrapper.findAll('button').find(button => button.text() === '提交待入库')!.attributes('disabled')).toBeDefined()
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
