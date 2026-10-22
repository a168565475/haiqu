import { defineComponent, ref } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElSelect } from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import SampleApplicationBasics from './SampleApplicationBasics.vue'

const api = vi.hoisted(() => ({ contacts: vi.fn(), customers: vi.fn(), inquiries: vi.fn(), quotations: vi.fn(), context: vi.fn() }))
vi.mock('@/api/contacts', () => ({ fetchCustomerContacts: api.contacts }))
vi.mock('@/api/customers', () => ({ fetchCustomers: api.customers }))
vi.mock('@/api/inquiries', () => ({ fetchInquiries: api.inquiries }))
vi.mock('@/api/quotations', () => ({ fetchQuotations: api.quotations }))
vi.mock('@/api/sampleApplication', () => ({ fetchSampleApplicationSourceContext: api.context }))
const baseline = { source_type: 'inquiry', source_id: 'source1', customer_account_id: 'customer1', customer_contact_id: 'contact1', owner_employee_id: 'owner1', sample_type: 'PRE_SALES', shipping_method: 'MAIL', delivery_batch: 'SINGLE', is_repeat_order: false, order_date: null, sample_due_date: null }
const options = { customers: [{ id: 'customer2', account_name: '第二客户' }], salespeople: [], sample_types: [], shipping_methods: [], delivery_batches: [], repeat_options: [] }
const sample = { id: 'sample1', customer_account: 'customer1', customer_name: '当前客户', customer_contact: 'contact1', customer_contact_name: '当前联系人', owner: { id: 'owner1', display_name: '当前业务员' }, source_inquiry: 'source1', source_inquiry_number: 'INQ-1' }
const mounted: ReturnType<typeof mount>[] = []
async function render(readonly = false) {
  const wrapper = mount(defineComponent({ components: { SampleApplicationBasics }, setup() { return { value: ref({ ...baseline }), options: readonly ? null : options, sample, readonly } }, template: '<ElForm :disabled="readonly"><SampleApplicationBasics v-model="value" :options="options" :sample="sample" /></ElForm>' }), { global: { plugins: [ElementPlus] } })
  mounted.push(wrapper); await flushPromises(); return wrapper
}
function select(wrapper: ReturnType<typeof mount>, label: string) { return wrapper.findAllComponents(ElSelect).find(item => item.props('ariaLabel') === label)! }
beforeEach(() => { vi.clearAllMocks(); api.contacts.mockResolvedValue({ data: [] }); api.customers.mockResolvedValue({ data: [] }); api.inquiries.mockResolvedValue({ data: [] }); api.quotations.mockResolvedValue({ data: [] }) })
afterEach(() => mounted.splice(0).forEach(wrapper => wrapper.unmount()))

describe('样品基础信息组件契约（模拟接口）', () => {
  it('已有客户联系人业务员来源不在候选列表仍正确显示，并允许修改', async () => {
    const wrapper = await render()
    expect(wrapper.text()).toContain('当前客户')
    expect(wrapper.text()).toContain('当前联系人')
    expect(wrapper.text()).toContain('当前业务员')
    expect(wrapper.text()).toContain('INQ-1')
    expect(select(wrapper, '客户').find('input').attributes('disabled')).toBeUndefined()
    expect(wrapper.findAll('.el-form-item')).toHaveLength(11)
  })
  it('切换客户清除旧来源和联系人，切换后加载新客户联系人', async () => {
    const wrapper = await render()
    select(wrapper, '客户').vm.$emit('update:modelValue', 'customer2'); await flushPromises()
    expect(wrapper.findComponent(SampleApplicationBasics).props('modelValue')).toMatchObject({ customer_account_id: 'customer2', customer_contact_id: null, source_type: null, source_id: null })
    expect(api.contacts).toHaveBeenLastCalledWith('customer2', expect.any(Object))
  })
  it('选择来源使用编辑专属上下文，原子带入客户联系人业务员', async () => {
    const wrapper = await render()
    api.context.mockResolvedValue({ source_number: 'INQ-2', customer: { id: 'customer2', account_name: '第二客户' }, contact: null, owner: { id: 'owner2', display_name: '第二业务员' } })
    select(wrapper, '来源单据').vm.$emit('update:modelValue', 'source2'); await flushPromises()
    expect(api.context).toHaveBeenCalledWith('sample1', 'inquiry', 'source2')
    expect(wrapper.findComponent(SampleApplicationBasics).props('modelValue')).toMatchObject({ source_id: 'source2', customer_account_id: 'customer2', customer_contact_id: null, owner_employee_id: 'owner2' })
    select(wrapper, '来源单据').vm.$emit('update:modelValue', ''); await flushPromises()
    expect(wrapper.findComponent(SampleApplicationBasics).props('modelValue')).toMatchObject({ source_type: null, source_id: null })
  })
  it('来源读取失败保留已有输入并显示错误', async () => {
    const wrapper = await render()
    api.context.mockRejectedValue(new Error('来源读取失败'))
    select(wrapper, '来源单据').vm.$emit('update:modelValue', 'source2'); await flushPromises()
    expect(wrapper.findComponent(SampleApplicationBasics).props('modelValue')).toEqual(baseline)
    expect(wrapper.get('[role="alert"]').text()).toBe('来源读取失败')
  })
  it('只读页没有选项仍显示原信息，不额外读取联系人', async () => {
    const wrapper = await render(true)
    expect(wrapper.text()).toContain('当前客户')
    expect(select(wrapper, '客户').find('input').attributes('disabled')).toBeDefined()
    expect(api.contacts).not.toHaveBeenCalled()
  })
})
