import { DOMWrapper, flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElMessage, ElSelect, ElUpload } from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import SampleApplicationCreateView from './SampleApplicationCreateView.vue'

const api = vi.hoisted(() => ({ options: vi.fn(), context: vi.fn(), customers: vi.fn(), customer: vi.fn(), contacts: vi.fn(), products: vi.fn(), submit: vi.fn(), replace: vi.fn(), query: {} as Record<string, string> }))
vi.mock('vue-router', () => ({
  useRoute: () => ({ query: api.query }), useRouter: () => ({ push: vi.fn(), replace: api.replace }),
  onBeforeRouteLeave: vi.fn(), onBeforeRouteUpdate: vi.fn(),
}))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: () => true }) }))
vi.mock('@/api/samples', () => ({ fetchSampleFormOptions: api.options, fetchSampleFormContext: api.context }))
vi.mock('@/api/customers', () => ({ fetchCustomers: api.customers, fetchCustomer: api.customer }))
vi.mock('@/api/contacts', () => ({ fetchCustomerContacts: api.contacts }))
vi.mock('@/api/products', () => ({ fetchProducts: api.products }))
vi.mock('@/api/sampleApplication', () => ({ submitSampleApplication: api.submit }))
const wrappers: ReturnType<typeof mount>[] = []
const customer = (id: string) => ({ id, account_code: id, account_name: `客户${id}` })

async function render() {
  const wrapper = mount(SampleApplicationCreateView, { global: { plugins: [ElementPlus] } })
  wrappers.push(wrapper)
  await flushPromises()
  return wrapper
}
function customerSelect(wrapper: ReturnType<typeof mount>) {
  return wrapper.findAllComponents(ElSelect).find(item => item.props('ariaLabel') === '客户')!
}
beforeEach(() => {
  vi.clearAllMocks()
  api.query = {}
  api.options.mockResolvedValue({ current_maker: { id: 'owner' }, customers: [customer('first')], salespeople: [], sample_types: [], shipping_methods: [], delivery_batches: [], repeat_options: [] })
  api.customers.mockResolvedValue({ data: [customer('501')] })
  api.customer.mockResolvedValue({ data: customer('501') })
  api.contacts.mockResolvedValue({ data: [] })
  api.products.mockResolvedValue({ data: [{ id: 'product-1', product_name: '折叠椅', specification: '57×61×83 cm' }] })
  vi.spyOn(ElMessage, 'error').mockImplementation(() => ({ close: vi.fn() }))
})
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()); vi.restoreAllMocks(); vi.unstubAllGlobals() })

describe('创建打样申请客户查询', () => {
  it('当前登录人不在业务部候选时留空，不把内部ID回显为业务员', async () => {
    const wrapper = await render()
    const owner = wrapper.findAllComponents(ElSelect).find(item => item.props('ariaLabel') === '业务员')!
    expect(owner.props('modelValue')).toBe('')
    expect(owner.text()).toContain('请选择业务员')
  })
  it('当前登录人在业务部候选中时默认选中本人并显示姓名', async () => {
    const options = await api.options()
    api.options.mockResolvedValue({ ...options, salespeople: [{ id: 'owner', display_name: '业务员甲' }] })
    const wrapper = await render()
    const owner = wrapper.findAllComponents(ElSelect).find(item => item.props('ariaLabel') === '业务员')!
    expect(owner.props('modelValue')).toBe('owner')
    expect(owner.text()).toContain('业务员甲')
  })
  it.each([['PENDING_COMPLETION', 'sample-detail'], ['DIRECTOR_REVIEW', 'sample-director-review']])('以服务端%s状态进入真实下一阶段', async (status, name) => {
    vi.spyOn(ElMessage, 'success').mockImplementation(() => ({ close: vi.fn() }))
    api.submit.mockResolvedValue({ id: 'created-sample', etag: 'v1', status })
    const wrapper = await render()
    const form = (wrapper.vm as unknown as { form: Record<string, unknown> }).form
    Object.assign(form, { customerId: 'first', ownerId: 'owner', sampleType: 'PRE_SALES', shippingMethod: 'MAIL', deliveryBatch: 'SINGLE', repeatOrder: false, productName: '折叠椅', quantity: 3 })
    await wrapper.findAll('button').find(button => button.text() === '提交确认')!.trigger('click')
    await flushPromises()
    expect(api.replace).toHaveBeenCalledWith({ name, params: { sampleId: 'created-sample' } })
  })
  it('客户详情入口回填初始列表之外的客户并加载联系人', async () => {
    api.query = { customer_id: '501' }
    const wrapper = await render()
    expect(api.customer).toHaveBeenCalledWith('501')
    expect(customerSelect(wrapper).props('modelValue')).toBe('501')
    expect(api.contacts).toHaveBeenCalledWith('501', expect.any(Object))
    expect(wrapper.findAllComponents({ name: 'ElOption' }).some(option => option.props('value') === '501')).toBe(true)
    expect(api.context).not.toHaveBeenCalled()
  })
  it('入口客户无法读取时显示错误，不静默创建到其他客户', async () => {
    api.query = { customer_id: 'inaccessible' }
    api.customer.mockRejectedValueOnce(new Error('客户无权访问'))
    const wrapper = await render()
    expect(wrapper.text()).toContain('客户无权访问')
    expect(api.contacts).not.toHaveBeenCalled()
  })
  it('归档客户不能通过地址栏预填到新申请', async () => {
    api.query = { customer_id: '501' }
    api.customer.mockResolvedValueOnce({ data: { ...customer('501'), archived_at: '2026-09-11T00:00:00Z' } })
    const wrapper = await render()
    expect(wrapper.text()).toContain('该客户已归档')
  })
  it('从报价入口进入当前新建页并带入唯一报价产品', async () => {
    api.query = { sourceType: 'quotation', sourceId: 'quotation-version' }
    api.context.mockResolvedValue({
      source_type: 'quotation', source_id: 'quotation-version', source_number: 'QUO-202609-000001',
      customer: customer('first'), owner: { id: 'owner' }, basic_info: {}, reference_images: [], unfinished_samples: [],
      products: [{ id: 'quotation-line', product_name: '折叠椅', specification: '50×50 红色' }],
    })

    const wrapper = await render()

    expect(api.context).toHaveBeenCalledWith('quotation', 'quotation-version')
    const productSelect = wrapper.findAllComponents(ElSelect).find(item => item.props('ariaLabel') === '产品名称')!
    expect(productSelect.props('modelValue')).toBe('quotation-line')
    expect((wrapper.find('input[aria-label="规格"]').element as HTMLInputElement).value).toBe('50×50 红色')
    expect(wrapper.findAll('input').some(input => (input.element as HTMLInputElement).value === 'QUO-202609-000001')).toBe(true)
  })
  it('唯一报价产品的明细图片自动进入图片上传区', async () => {
    api.query = { sourceType: 'quotation', sourceId: 'quotation-version' }
    api.context.mockResolvedValue({
      source_type: 'quotation', source_id: 'quotation-version', source_number: 'QUO-202609-000001',
      customer: customer('first'), owner: { id: 'owner' }, basic_info: {}, reference_images: [], unfinished_samples: [],
      products: [{ id: 'quotation-line', product_name: '折叠椅', specification: '50×50 红色', reference_images: [{ id: 'quote-image', name: '折叠椅.png', url: '/quotation-image.png' }] }],
    })

    const wrapper = await render()

    expect(wrapper.find('.source-image-select').text()).toContain('选择报价产品图片（1 张）')
    expect(wrapper.find('.product-image img').attributes('src')).toBe('/quotation-image.png')
    expect(wrapper.find('.reference-preview img').attributes('src')).toBe('/quotation-image.png')
  })
  it('切换报价产品时只展示所选产品的明细图片', async () => {
    api.query = { sourceType: 'quotation', sourceId: 'quotation-version' }
    api.context.mockResolvedValue({
      source_type: 'quotation', source_id: 'quotation-version', source_number: 'QUO-202609-000001',
      customer: customer('first'), owner: { id: 'owner' }, basic_info: {}, reference_images: [], unfinished_samples: [],
      products: [
        { id: 'line-1', product_name: '行军床', specification: '红色', reference_images: [{ id: 'image-1', name: '行军床.png', url: '/bed.png' }] },
        { id: 'line-2', product_name: '折叠椅', specification: '蓝色', reference_images: [{ id: 'image-2', name: '折叠椅.png', url: '/chair.png' }] },
      ],
    })
    const wrapper = await render()
    const productSelect = wrapper.findAllComponents(ElSelect).find(item => item.props('ariaLabel') === '产品名称')!

    productSelect.vm.$emit('change', 'line-2')
    await flushPromises()
    await wrapper.find('.source-image-select').trigger('click')
    await flushPromises()

    const cards = new DOMWrapper(document.body).findAll('.sample-source-images article')
    expect(cards).toHaveLength(1)
    expect(cards[0]!.findComponent({ name: 'ElImage' }).props('src')).toBe('/chair.png')
    expect(wrapper.text()).not.toContain('行军床.png')
  })
  function inquiry(images: Array<{ id: string; name: string; url: string }>) {
    api.query = { sourceType: 'inquiry', sourceId: 'inquiry' }
    api.context.mockResolvedValue({ source_type: 'inquiry', source_id: 'inquiry', customer: customer('first'), owner: { id: 'owner' }, basic_info: {}, reference_images: images, unfinished_samples: [], products: [{ id: 'item', product_name: '椅子', specification: '50cm' }] })
  }
  it('询盘单张附件自动带入产品图片，移除后不自动恢复', async () => {
    inquiry([{ id: 'image1', name: '产品.png', url: '/source-image.png' }])
    api.query.customer_id = '501'
    const wrapper = await render()
    expect(wrapper.findAll('input').some(input => (input.element as HTMLInputElement).value === '客户first')).toBe(true)
    expect(api.customer).not.toHaveBeenCalled()
    expect(wrapper.find('.product-image img').attributes('src')).toBe('/source-image.png')
    expect(wrapper.find('.reference-preview img').attributes('src')).toBe('/source-image.png')
    await wrapper.findAll('button').find(button => button.text() === '移除图片')!.trigger('click')
    expect(wrapper.find('.product-image img').exists()).toBe(false)
    expect(wrapper.find('.reference-preview').exists()).toBe(false)
  })
  it('多张询盘图片需要选择，上传替换同时更新产品图片', async () => {
    inquiry([{ id: 'image1', name: '产品1.png', url: '/source-1.png' }, { id: 'image2', name: '产品2.png', url: '/source-2.png' }])
    const wrapper = await render()
    expect(wrapper.find('.product-image img').exists()).toBe(false)
    await wrapper.find('.source-image-select').trigger('click'); await flushPromises()
    const cards = new DOMWrapper(document.body).findAll('.sample-source-images article')
    expect(cards).toHaveLength(2)
    expect(cards[1]!.findComponent({ name: 'ElImage' }).props('src')).toBe('/source-2.png')
    expect(cards[1]!.findComponent({ name: 'ElImage' }).props('previewSrcList')).toEqual(['/source-1.png', '/source-2.png'])
    expect(cards[1]!.findComponent({ name: 'ElImage' }).props('initialIndex')).toBe(1)
    await cards[1]!.find('button').trigger('click'); await flushPromises()
    expect(wrapper.find('.product-image img').attributes('src')).toBe('/source-2.png')
    vi.stubGlobal('URL', { createObjectURL: vi.fn(() => 'blob:replacement'), revokeObjectURL: vi.fn() })
    wrapper.findComponent(ElUpload).props('onChange')!({ raw: new File(['png'], 'new.png', { type: 'image/png' }) } as never, [])
    await flushPromises()
    expect(wrapper.find('.product-image img').attributes('src')).toBe('blob:replacement')
    expect(new DOMWrapper(document.body).findAll('.sample-source-images article.is-selected')).toHaveLength(0)
  })
  it('无需输入即可下拉选择现有产品，并带入名称和规格', async () => {
    const wrapper = await render()
    const select = wrapper.findAllComponents(ElSelect).find(item => item.props('ariaLabel') === '产品名称')!
    expect(api.products).toHaveBeenCalledWith({ page: 1, page_size: 50, q: '', status: 'ACTIVE' })
    expect(wrapper.findAllComponents({ name: 'ElOption' }).some(option => option.props('value') === 'product-1')).toBe(true)
    select.vm.$emit('update:modelValue', 'product-1')
    select.vm.$emit('change', 'product-1')
    await flushPromises()
    expect((wrapper.find('input[aria-label="规格"]').element as HTMLInputElement).value).toBe('57×61×83 cm')
  })

  it('清空搜索重新展示可选产品，较早搜索返回不会覆盖它', async () => {
    const wrapper = await render()
    const select = wrapper.findAllComponents(ElSelect).find(item => item.props('ariaLabel') === '产品名称')!
    let resolveOld!: (data: unknown) => void
    api.products.mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve }))
    const old = select.props('remoteMethod')!('旧关键词')
    await select.props('remoteMethod')!('')
    resolveOld({ data: [{ id: 'old', product_name: '旧结果' }] })
    await old
    await flushPromises()
    expect(wrapper.findAllComponents({ name: 'ElOption' }).some(option => option.props('value') === 'product-1')).toBe(true)
    expect(wrapper.findAllComponents({ name: 'ElOption' }).some(option => option.props('value') === 'old')).toBe(false)
  })

  it('从真实搜索结果选择初始列表以外客户，清除上一客户联系人', async () => {
    const wrapper = await render()
    const select = customerSelect(wrapper)
    const contact = wrapper.findAllComponents(ElSelect).find(item => item.props('ariaLabel') === '联系人')!
    contact.vm.$emit('update:modelValue', 'previous-contact')
    await flushPromises()
    expect(select.props('remote')).toBe(true)
    await select.props('remoteMethod')!(' 客户501 ')
    await flushPromises()
    expect(api.customers).toHaveBeenCalledWith({ q: '客户501', page: 1, page_size: 50, archived: 'false' })
    expect(wrapper.findAllComponents({ name: 'ElOption' }).some(option => option.props('value') === '501')).toBe(true)
    select.vm.$emit('update:modelValue', '501')
    select.vm.$emit('change', '501')
    await flushPromises()
    expect(api.contacts).toHaveBeenCalledWith('501', expect.any(Object))
    expect(select.props('modelValue')).toBe('501')
    expect(contact.props('modelValue')).toBe('')
  })

  it('旧搜索晚返回不覆盖新结果，查询失败保留选择并提示', async () => {
    let resolveOld!: (result: { data: ReturnType<typeof customer>[] }) => void
    api.customers.mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve }))
    const wrapper = await render()
    const select = customerSelect(wrapper)
    expect(select.props('remote')).toBe(true)
    const pending = select.props('remoteMethod')!('旧客户')
    await select.props('remoteMethod')!('新客户')
    resolveOld({ data: [customer('old')] })
    await pending
    await flushPromises()
    expect(wrapper.findAllComponents({ name: 'ElOption' }).some(option => option.props('value') === 'old')).toBe(false)
    select.vm.$emit('update:modelValue', '501')
    select.vm.$emit('change', '501')
    await flushPromises()
    api.customers.mockRejectedValueOnce(new Error('客户读取失败'))
    await select.props('remoteMethod')!('失败')
    await flushPromises()
    expect(ElMessage.error).toHaveBeenCalledWith('客户读取失败')
    expect(select.props('modelValue')).toBe('501')
    expect(select.props('loading')).toBe(false)
  })
})
