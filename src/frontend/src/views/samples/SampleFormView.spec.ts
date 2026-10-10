import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElMessage, ElMessageBox } from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import SampleFormView from './SampleFormView.vue'

const state = vi.hoisted(() => ({
  fetch: vi.fn(), options: vi.fn(), patch: vi.fn(), replace: vi.fn(),
  permissions: new Set<string>(), leave: null as null | (() => Promise<boolean>),
}))
vi.mock('vue-router', () => ({
  useRoute: () => ({ params: { sampleId: 'sample-1' }, query: {} }),
  useRouter: () => ({ replace: state.replace, push: vi.fn() }),
  onBeforeRouteLeave: (callback: () => Promise<boolean>) => { state.leave = callback },
  onBeforeRouteUpdate: vi.fn(),
}))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: (name: string) => state.permissions.has(name), moduleCan: (name: string, legacy = name) => state.permissions.has(legacy) }) }))
vi.mock('@/api/samples', () => ({ fetchSample: state.fetch, fetchSampleFormOptions: state.options, patchSampleForm: state.patch, submitSampleForm: vi.fn() }))

function result() {
  return { etag: '"version-4"', data: {
    id: 'sample-1', request_number: 'HTS-123', status: 'PMC_REVIEW', status_display: 'PMC 审核', manual_request_number: '123',
    customer_account: 'customer', customer_contact: null, owner: { id: 'owner', display_name: '业务员' },
    shipping_method: 'MAIL', order_date: '2026-09-01', sample_due_date: '2026-09-18', delivery_batch: 'SINGLE',
    sample_type: 'PRE_SALE', is_repeat_order: false, submitted_on: '2026-09-01', purpose: '',
    edit_capabilities: { mode: 'REPORT_ONLY', can_report_edit: true, can_full_edit: false },
    products: [{
      id: 'product', source_inquiry_item_id: 'source-row', source_quotation_line_id: null,
      category_id: 'category', product_name: '折叠椅', specification: '', task_sheet_file_name: '任务.jpg',
      length_cm: '60.00', armrest_width_cm: null, seat_width_cm: null, back_height_cm: null, seat_height_cm: null,
      details: [{ id: 'detail', product_color_id: 'color', color_card: '', color_code: '', sample_quantity: 4,
        tolerance: 'NONE', notes: '', cutting_reported_quantity: 0, metalwork_reported_quantity: 0,
        cutting_completed: false, metalwork_completed: false }],
      sampling_details: [],
    }],
  } }
}
const wrappers: ReturnType<typeof mount>[] = []
async function render() {
  const wrapper = mount(SampleFormView, { global: { plugins: [ElementPlus] } })
  wrappers.push(wrapper)
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  vi.clearAllMocks()
  state.permissions.clear()
  state.permissions.add('samples.change_samplerequest')
  state.fetch.mockResolvedValue(result())
  state.options.mockResolvedValue({ current_maker: { id: 'maker', display_name: '制单人' }, customers: [], salespeople: [],
    shipping_methods: [], delivery_batches: [], sample_types: [], repeat_options: [], categories: [], colors: [], color_cards: [], tolerances: [], sampling_detail_template: [] })
  state.patch.mockResolvedValue(result())
  state.replace.mockResolvedValue(undefined)
  vi.spyOn(ElMessage, 'success').mockImplementation(() => ({ close: vi.fn() }))
  vi.spyOn(ElMessage, 'error').mockImplementation(() => ({ close: vi.fn() }))
})
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()); vi.restoreAllMocks() })

describe('真实样品编辑页的报工保存入口', () => {
  it('完整编辑时任务单和明细图片可连续替换，保留最后一次选择并触发离开保护', async () => {
    const data = result()
    Object.assign(data.data, { status: 'PENDING', edit_capabilities: { mode: 'FULL', can_full_edit: true, can_report_edit: true } })
    Object.assign(data.data.products[0]!, { sampling_details: [{ id: 'sampling-1', template_key: 'tube', detail_type: '管材', category_label: '圆管', is_selected: true, description: '', image_file_name: '原图.png' }] })
    data.data.products[0]!.specification = '60×50cm'
    data.data.products[0]!.details[0]!.color_card = '潘通'
    data.data.products[0]!.details[0]!.color_code = '2322C'
    state.permissions.add('samples.complete_sample_requirements')
    state.fetch.mockResolvedValue(data)
    const wrapper = await render()
    expect(wrapper.attributes('data-visual-reference')).toBe('676:9438')
    for (const selector of ['.task-upload', '.sampling-image-upload']) {
      const input = wrapper.find(`${selector} input[type=file]`)
      for (const name of ['第一次.png', '替换后.png']) {
        Object.defineProperty(input.element, 'files', { value: [new File(['image'], name, { type: 'image/png' })], configurable: true })
        await input.trigger('change')
        await flushPromises()
      }
      expect(wrapper.find(`${selector} button`).text()).toContain('替换后.png')
      expect(wrapper.find(`${selector} button`).text()).not.toContain('第一次.png')
    }
    vi.spyOn(ElMessageBox, 'confirm').mockRejectedValue('cancel')
    expect(await state.leave!()).toBe(false)
    expect(state.patch).not.toHaveBeenCalled()
    await wrapper.find('.form-actions .el-button--primary').trigger('click')
    await flushPromises()
    expect(state.patch).toHaveBeenCalledWith('sample-1', expect.any(Object),
      { product: expect.objectContaining({ name: '替换后.png' }) },
      { 'sampling-1': expect.objectContaining({ name: '替换后.png' }) }, '"version-4"')
  })

  it.each([false, true])('完善页不增加原型外的明细，历史明细保留：%s', async (hasHistory) => {
    const data = result()
    Object.assign(data.data, { status: 'PENDING_COMPLETION', edit_capabilities: { mode: 'COMPLETE', can_full_edit: true, can_report_edit: true } })
    const product = data.data.products[0]!
    product.specification = '60×50cm'
    product.details[0]!.color_card = '潘通'
    product.details[0]!.color_code = '2322C'
    if (hasHistory) Object.assign(product, { sampling_details: [{ id: 'legacy', template_key: 'tube', detail_type: '管材', category_label: '圆管', is_selected: false, description: '历史说明', image_file_name: '旧图.png' }] })
    state.permissions.add('samples.complete_sample_requirements')
    state.fetch.mockResolvedValue(data)
    state.options.mockResolvedValue({ current_maker: { id: 'maker', display_name: '制单人' }, customers: [], salespeople: [], categories: [], colors: [],
      sampling_detail_template: [{ key: 'tube', type: '材料', category: '管材' }] })
    const wrapper = await render()
    expect(wrapper.attributes('data-visual-reference')).toBe('724:8929')
    expect(wrapper.find('h1').text()).toBe('完善样品需求')
    expect(wrapper.find('.sampling-detail-panel').exists()).toBe(false)
    expect(wrapper.find('.form-state').exists()).toBe(false)
    const owner = wrapper.findAll('.edit-basic-section .el-form-item').find(item => item.text().includes('业务员'))!
    expect(owner.find('.el-select__wrapper').classes()).toContain('is-disabled')
    await wrapper.find('.form-actions .el-button--primary').trigger('click')
    await flushPromises()
    expect(state.patch).toHaveBeenCalledOnce()
    expect(state.patch.mock.calls[0]![1].products[0].sampling_details).toEqual(hasHistory
      ? [expect.objectContaining({ id: 'legacy', detail_type: '管材', description: '历史说明', is_selected: false })] : [])
  })

  it('已有申请缺少日期或寄送信息时保持未填写，不以当前日期或默认选项覆盖', async () => {
    const missing = result()
    Object.assign(missing.data, { order_date: null, sample_due_date: null, submitted_on: null, shipping_method: '', delivery_batch: '', is_repeat_order: null })
    state.fetch.mockResolvedValue(missing)
    const wrapper = await render()
    const dates = wrapper.findAll('.edit-basic-section .el-date-editor input')
    expect(dates).toHaveLength(3)
    expect(dates.every(input => (input.element as HTMLInputElement).value === '')).toBe(true)
    const shipping = wrapper.findAll('.edit-basic-section .el-form-item').find(item => item.text().includes('寄送方式'))!
    expect(shipping.text()).toContain('邮寄 / 其他')
    expect(wrapper.find('.form-state .request-number').text()).toBe('HTS-123')
    expect(state.patch).not.toHaveBeenCalled()
  })

  it('只读规格、色卡和空打样信息不阻止报工，保存使用原 ETag 和完整原始产品', async () => {
    const wrapper = await render()
    await wrapper.find('textarea').setValue('本次补充说明')
    const inputs = wrapper.findAll('.detail-table__row .el-input-number input')
    expect(inputs[1]!.element).toHaveProperty('value', '0')
    await inputs[1]!.setValue('3')
    await inputs[1]!.trigger('change')
    await wrapper.find('.form-actions .el-button--primary').trigger('click')
    await flushPromises()
    expect(state.patch).toHaveBeenCalledWith('sample-1', expect.objectContaining({
      manual_request_number: '123', purpose: '本次补充说明', submitted_on: '2026-09-01',
      products: [expect.objectContaining({ id: 'product', source_inquiry_item_id: 'source-row', specification: '',
        sampling_details: [], details: [expect.objectContaining({ id: 'detail', sample_quantity: 4, cutting_reported_quantity: 3 })] })],
    }), {}, {}, '"version-4"')
    expect(state.replace).toHaveBeenCalledWith({ name: 'sample-detail', params: { sampleId: 'sample-1' } })
    expect(await state.leave!()).toBe(true)
  })

  it('请求中重复保存只发送一次，失败后保留输入和离开保护', async () => {
    let reject: (error: Error) => void = () => {}
    state.patch.mockImplementationOnce(() => new Promise((_resolve, failure) => { reject = failure }))
    const wrapper = await render()
    await wrapper.find('textarea').setValue('尚未保存')
    const save = wrapper.find('.form-actions .el-button--primary')
    await save.trigger('click')
    await save.trigger('click')
    expect(state.patch).toHaveBeenCalledTimes(1)
    reject(new Error('连接中断'))
    await flushPromises()
    expect(ElMessage.error).toHaveBeenCalledWith('连接中断')
    expect(state.replace).not.toHaveBeenCalled()
    expect(wrapper.find('textarea').element.value).toBe('尚未保存')
    const confirm = vi.spyOn(ElMessageBox, 'confirm').mockRejectedValue('cancel')
    expect(await state.leave!()).toBe(false)
    expect(confirm).toHaveBeenCalledTimes(1)
    await save.trigger('click')
    await flushPromises()
    expect(state.patch).toHaveBeenCalledTimes(2)
  })

  it('缺少版本信息时不发送保存请求', async () => {
    state.fetch.mockResolvedValue({ ...result(), etag: '' })
    const wrapper = await render()
    await wrapper.find('.form-actions .el-button--primary').trigger('click')
    expect(state.patch).not.toHaveBeenCalled()
    expect(ElMessage.error).toHaveBeenCalledWith('缺少版本信息，请重新加载后再保存。')
  })

  it('缺少编辑权限时关闭报工及保存入口', async () => {
    state.permissions.clear()
    const wrapper = await render()
    expect(wrapper.find('.form-actions .el-button--primary').exists()).toBe(false)
    expect(wrapper.find('textarea').attributes('disabled')).toBeDefined()
    expect(wrapper.findAll('.detail-table__row .el-input-number input').every(input => input.attributes('disabled') !== undefined)).toBe(true)
    expect(state.patch).not.toHaveBeenCalled()
  })
})
