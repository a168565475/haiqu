import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import InquiryProductDialog from './InquiryProductDialog.vue'
import type { InquiryItem, InquiryProductCandidate } from '@/types/inquiry'

const api = vi.hoisted(() => ({ selection: vi.fn() }))
vi.mock('@/api/inquiries', () => ({ fetchInquiryProductSelectionOptions: api.selection, inquiryProductImageUrl: (id: string) => `/api/v1/inquiry-items/${id}/product-image/` }))
const first: InquiryProductCandidate = { id: 'p1', category_id: 'c1', category_name: '成品', product_name: '导演椅', specification: '50X60', unit_id: 'u1', unit_code: 'PCS', unit_name: '件', product_number: 'P1', product_code: 'C1', item_number: 'I1' }
const item = (overrides: Partial<InquiryItem> = {}): InquiryItem => ({ line_number: 1, product_description: '', specification: '', color: '亚黑', material: '铝', quantity: '8', unit_code: 'PCS', target_unit_price: '20', target_currency_code: 'USD', expected_date: null, product_match_status: 'PENDING', notes: '', ...overrides })
const control = { props: ['modelValue', 'disabled'], emits: ['update:modelValue', 'change'], template: '<input :value="modelValue" :disabled="disabled" @input="$emit(\'update:modelValue\', $event.target.value)" @change="$emit(\'change\', $event.target.value)"/>' }
const selectControl = { ...control, inheritAttrs: false, template: '<div><input v-bind="$attrs" :value="modelValue" :disabled="disabled" @input="$emit(\'update:modelValue\', $event.target.value)" @change="$emit(\'change\', $event.target.value)"/><slot name="label"/></div>' }
function open(value = item(), units = [{ id: 'u1', unit_code: 'PCS', unit_name: '件' }], slots: Record<string, string> = {}) {
  return mount(InquiryProductDialog, { props: { modelValue: true, item: value, categories: [{ id: 'c1', category_name: '成品' }], units, colors: [], currencies: [], canUpload: true }, slots, global: { stubs: { AppWindowDialog: { template: '<section><slot/><slot name="footer"/></section>' }, ElInput: control, ElSelect: selectControl, ElDatePicker: control, ElOption: true, ElImage: true, ElIcon: { template: '<span><slot/></span>' }, ElButton: { template: '<button><slot/></button>' } } } })
}
const button = (wrapper: ReturnType<typeof open>, label: string) => wrapper.findAll('button').find(row => row.text() === label)!
beforeEach(() => { vi.clearAllMocks(); api.selection.mockResolvedValue({ category: { id: 'c1', category_name: '成品' }, groups: [{ product_name: '导演椅', specifications: [{ specification: '50X60', products: [first, { ...first, id: 'p2', product_number: 'P2', product_code: 'C2' }] }] }] }) })
describe('询盘A组产品弹窗', () => {
  it('生产嵌入可隐藏销售标题并使用生产文案，普通销售弹窗仍保留标题', async () => {
    const wrapper = open()
    await wrapper.setProps({ scene: 'sales-order' })
    expect(wrapper.text()).toContain('销售订单产品明细')
    await wrapper.setProps({ embedded: true, hideSummary: true, businessTitle: '本次生产内容' })
    expect(wrapper.find('.entry-summary').exists()).toBe(false)
    expect(wrapper.get('.business-zone').attributes('aria-label')).toBe('本次生产内容')
    expect(wrapper.text()).not.toContain('本次销售订单内容')
    expect(button(wrapper, '添加产品').exists()).toBe(true)
    wrapper.unmount()
  })
  it('单位界面只显示名称，不拼接内部编码', async () => {
    const wrapper = open(item({ product_id: null, product_category_id: 'c1', product_unit_id: 'u7', product_description: '定制箱', specification: '50X60', unit_code: '07' }), [{ id: 'u7', unit_code: '07', unit_name: '箱' }])
    await flushPromises()
    expect(wrapper.text()).toContain('箱')
    expect(wrapper.text()).not.toContain('箱 (07)')
    await button(wrapper, '保存产品信息').trigger('click')
    expect((wrapper.emitted('confirm')![0]![0] as { item: InquiryItem }).item).toMatchObject({ product_unit_id: 'u7', unit_code: '07' })
    wrapper.unmount()
  })
  it('销售订单使用订单单价，空值和负值不能确认，合法价格保留产品关联', async () => {
    const original = item({ product_id: 'p1', product_category_id: 'c1', product_description: '导演椅', specification: '50X60', target_unit_price: '' })
    const wrapper = open(original)
    await wrapper.setProps({ scene: 'sales-order', quotationCurrency: 'USD', canUpload: false })
    await flushPromises()
    expect(wrapper.find('[aria-label="目标价"]').exists()).toBe(false)
    await button(wrapper, '保存产品信息').trigger('click')
    expect(wrapper.emitted('confirm')).toBeUndefined()
    expect(wrapper.text()).toContain('请填写订单单价')
    await wrapper.get('input[aria-label="订单单价"]').setValue('-1')
    await button(wrapper, '保存产品信息').trigger('click')
    expect(wrapper.emitted('confirm')).toBeUndefined()
    expect(wrapper.text()).toContain('订单单价须为非负数')
    await wrapper.get('input[aria-label="订单单价"]').setValue('12.3456')
    await button(wrapper, '保存产品信息').trigger('click')
    expect((wrapper.emitted('confirm')![0]![0] as { item: InquiryItem }).item).toMatchObject({ product_id: 'p1', quantity: '8', target_unit_price: '12.3456', target_currency_code: 'USD', color: '亚黑', material: '铝' })
    expect(original.target_unit_price).toBe('')
    wrapper.unmount()
  })
  it('三级选择后必须明确选中同名同规格中的真实记录，保留本单要求', async () => {
    const wrapper = open()
    await wrapper.get('input[aria-label="类别"]').setValue('c1'); await flushPromises()
    expect(api.selection).toHaveBeenCalledWith('c1')
    await wrapper.get('input[aria-label="品名"]').setValue('导演椅')
    await wrapper.get('input[aria-label="规格"]').setValue('50X60')
    await button(wrapper, '添加到当前单据').trigger('click')
    expect(wrapper.emitted('confirm')).toBeUndefined()
    expect(wrapper.text()).toContain('请选择具体产品记录')
    await wrapper.get('input[aria-label="选择 P2"]').setValue(true)
    await button(wrapper, '添加到当前单据').trigger('click')
    const result = wrapper.emitted('confirm')![0]![0] as { item: InquiryItem }
    expect(result.item).toMatchObject({ product_id: 'p2', product_number_snapshot: 'P2', product_description: '导演椅', specification: '50X60', quantity: '8', color: '亚黑', target_unit_price: '20' })
    wrapper.unmount()
  })
  it('切换定制模式与单位手填清除失效关联，取消不修改原记录', async () => {
    const original = item({ product_id: 'p1', product_category_id: 'c1', product_description: '导演椅', specification: '50X60', product_number_snapshot: 'P1' })
    const wrapper = open(original); await flushPromises()
    await button(wrapper, '手工录入定制产品').trigger('click')
    await wrapper.get('input[aria-label="单位"]').setValue('把')
    await wrapper.get('input[aria-label="品名"]').setValue('定制导演椅')
    await button(wrapper, '保存产品信息').trigger('click')
    const result = wrapper.emitted('confirm')![0]![0] as { item: InquiryItem }
    expect(result.item).toMatchObject({ product_id: null, product_unit_id: null, unit_code: '把', product_description: '定制导演椅', quantity: '8', color: '亚黑' })
    expect(original.product_id).toBe('p1'); expect(original.product_description).toBe('导演椅')
    wrapper.unmount()
  })
  it('较早请求晚返回时不能替换新类别的选项', async () => {
    let finish!: (value: unknown) => void
    api.selection.mockReturnValueOnce(new Promise(resolve => { finish = resolve })).mockResolvedValueOnce({ category: { id: 'c2' }, groups: [] })
    const wrapper = open()
    await wrapper.get('input[aria-label="类别"]').setValue('c1')
    await wrapper.get('input[aria-label="类别"]').setValue('c2'); await flushPromises()
    finish({ category: { id: 'c1' }, groups: [{ product_name: '旧选项', specifications: [] }] }); await flushPromises()
    expect(wrapper.text()).toContain('没有匹配的产品')
    expect(wrapper.text()).not.toContain('旧选项')
    wrapper.unmount()
  })
  it('保存错误提示保留输入，重复点击仅发出一次确认', async () => {
    const wrapper = open(item({ product_category_id: 'c1', product_description: '手填椅', specification: '客户规格', quantity: '0' })); await flushPromises()
    await button(wrapper, '保存产品信息').trigger('click')
    expect(wrapper.text()).toContain('数量须大于零')
    await wrapper.get('input[aria-label="数量"]').setValue('2')
    await button(wrapper, '保存产品信息').trigger('click'); await button(wrapper, '保存产品信息').trigger('click')
    expect(wrapper.emitted('confirm')).toHaveLength(1)
    wrapper.unmount()
  })
  it('手填搜索内容按 Enter 或离开输入框时保存文本，不伪造维护项 ID', async () => {
    const wrapper = open(item({ product_category_id: 'c1', product_description: '定制椅', specification: '旧规格' })); await flushPromises()
    const spec = wrapper.get('input[aria-label="规格"]')
    ;(spec.element as HTMLInputElement).value = '手填新规格'
    await spec.trigger('keydown', { key: 'Enter' })
    const unit = wrapper.get('input[aria-label="单位"]')
    ;(unit.element as HTMLInputElement).value = '定制套装'
    await unit.trigger('blur')
    const color = wrapper.get('input[aria-label="颜色"]')
    ;(color.element as HTMLInputElement).value = '手填亚黑'
    await color.trigger('blur')
    await button(wrapper, '保存产品信息').trigger('click')
    expect((wrapper.emitted('confirm')![0]![0] as { item: InquiryItem }).item).toMatchObject({ specification: '手填新规格', unit_code: '定制套装', product_unit_id: null, color: '手填亚黑', product_color_id: null })
    wrapper.unmount()
  })
})

it('内嵌销售录入直接显示完整字段并提交，无需弹窗', async () => {
  const wrapper = open(item({ product_id: 'p1', product_category_id: 'c1', product_description: '导演椅', specification: '50X60', target_unit_price: '12.3456' }))
  await wrapper.setProps({ embedded: true, scene: 'sales-order', quotationCurrency: 'CNY', closeOnConfirm: false })
  await flushPromises()
  expect(wrapper.find('[aria-label="订单单价"]').exists()).toBe(true)
  expect(wrapper.find('[aria-label="数量"]').exists()).toBe(true)
  expect(wrapper.find('[aria-label="上传产品图片"]').exists()).toBe(true)
  expect(wrapper.findAll('button').some(row => row.text() === '取消')).toBe(false)
  await button(wrapper, '保存产品信息').trigger('click')
  expect((wrapper.emitted('confirm')![0]![0] as { item: InquiryItem }).item).toMatchObject({ product_id: 'p1', specification: '50X60', target_unit_price: '12.3456', material: '铝' })
  wrapper.unmount()
})

it('隐藏内嵌按钮后，外部确认仍执行数量和价格校验并保留原产品输入', async () => {
  const original = item({ product_id: 'p1', product_category_id: 'c1', product_description: '导演椅', specification: '50X60', quantity: '0', target_unit_price: '' })
  const wrapper = open(original)
  try {
    await wrapper.setProps({ embedded: true, hideEmbeddedFooter: true, scene: 'sales-order', quotationCurrency: 'CNY', closeOnConfirm: false })
    await flushPromises()
    expect(wrapper.find('.entry-footer').exists()).toBe(false)
    const dialog = wrapper.vm as unknown as { confirm: () => void }
    dialog.confirm()
    await flushPromises()
    expect(wrapper.emitted('confirm')).toBeUndefined()
    expect(wrapper.text()).toContain('数量须大于零')
    await wrapper.get('input[aria-label="数量"]').setValue('2')
    dialog.confirm()
    await flushPromises()
    expect(wrapper.emitted('confirm')).toBeUndefined()
    expect(wrapper.text()).toContain('请填写订单单价')
    await wrapper.get('input[aria-label="订单单价"]').setValue('12.3456')
    dialog.confirm()
    expect((wrapper.emitted('confirm')![0]![0] as { item: InquiryItem }).item).toMatchObject({ product_id: 'p1', quantity: '2', target_unit_price: '12.3456', specification: '50X60', color: '亚黑' })
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
    expect(original).toMatchObject({ quantity: '0', target_unit_price: '' })
    await wrapper.setProps({ busy: true })
    dialog.confirm()
    expect(wrapper.emitted('confirm')).toHaveLength(1)
  } finally { wrapper.unmount() }
})

it.each([false, true])('额外生产明细位于操作前且默认确认按钮仍可用，内嵌=%s', async embedded => {
  const wrapper = open(item({ product_id: 'p1', product_category_id: 'c1', product_description: '导演椅', specification: '50X60' }), undefined, { 'before-actions': '<section aria-label="生产明细">附加生产明细</section>' })
  try {
    await wrapper.setProps({ embedded, scene: 'sales-order', quotationCurrency: 'CNY' })
    await flushPromises()
    const details = wrapper.get('[aria-label="生产明细"]')
    const footer = wrapper.get('.entry-footer')
    expect(details.element.compareDocumentPosition(footer.element) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    await button(wrapper, '保存产品信息').trigger('click')
    expect((wrapper.emitted('confirm')![0]![0] as { item: InquiryItem }).item).toMatchObject({ product_id: 'p1', quantity: '8', target_unit_price: '20' })
  } finally { wrapper.unmount() }
})
