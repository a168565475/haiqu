import { flushPromises, mount, shallowMount, type VueWrapper } from '@vue/test-utils'
import { AxiosError, AxiosHeaders } from 'axios'
import ElementPlus, { ElMessage, ElMessageBox } from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import type { CustomerDetail, CustomerOptions } from '@/types/customer'
import CustomerEditDialog from './CustomerEditDialog.vue'
import CustomerEditView from './CustomerEditView.vue'

const mocks = vi.hoisted(() => ({
  canEdit: true, fetchCustomer: vi.fn(), fetchCustomerOptions: vi.fn(), fetchCustomerEntities: vi.fn(),
  fetchCustomerEntity: vi.fn(), fetchEntityAddresses: vi.fn(), fetchEntityAddress: vi.fn(),
  updateCustomer: vi.fn(), setCustomerGrade: vi.fn(), setCustomerSource: vi.fn(), setCustomerClassification: vi.fn(),
  createCustomerEntity: vi.fn(), updateCustomerEntity: vi.fn(), createEntityAddress: vi.fn(), updateEntityAddress: vi.fn(),
  checkCustomerDuplicates: vi.fn(), replace: vi.fn(), route: { params: { customerId: 'customer-1' } },
  leave: [] as Array<() => Promise<boolean>>, update: [] as Array<() => Promise<boolean>>,
}))
vi.mock('@/api/customers', () => mocks)
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: () => mocks.canEdit }) }))
vi.mock('vue-router', () => ({
  useRoute: () => mocks.route, useRouter: () => ({ replace: mocks.replace }),
  onBeforeRouteLeave: (guard: () => Promise<boolean>) => mocks.leave.push(guard),
  onBeforeRouteUpdate: (guard: () => Promise<boolean>) => mocks.update.push(guard),
}))
const options: CustomerOptions = {
  lifecycle_stages: [{ item_code: 'LEAD', display_name: '线索客户' }], activity_statuses: [],
  customer_grades: [{ id: 'grade-a', item_code: 'A', display_name: 'A级', description: '' }, { id: 'grade-b', item_code: 'B', display_name: 'B级', description: '' }],
  customer_types: [{ id: 'type-brand', item_code: 'BRAND', display_name: '品牌客户', description: '' }],
  customer_sources: [{ id: 'source-web', item_code: 'WEB', display_name: '网站', description: '' }],
  primary_regions: [{ id: 'europe', region_name: '欧洲', legacy_selector_code: 'EU', legacy_tree_code: 'EU' }],
  secondary_regions: [{ id: 'de', parent_id: 'europe', country_code: 'DE', region_name: '德国', legacy_selector_code: 'DE', legacy_tree_code: 'EU-DE' }],
  industries: [], interested_products: [], customer_tags: [], owner_options: [], country_options: [],
}
function customer(id = 'customer-1'): CustomerDetail {
  return {
    id, account_code: `KH-${id}`, account_name: `客户${id}`, english_name: '', short_name: '', lifecycle_stage: 'LEAD',
    primary_country_code: 'DE', primary_region: { id: 'europe' }, secondary_region: { id: 'de' },
    latest_source: { item_code: 'WEB' }, customer_grade: { item_code: 'A' }, customer_types: [{ item_code: 'BRAND' }],
    customer_tags: [], interested_products: [], current_assignments: [], company_contact_methods: [],
    primary_website_url: '', source_system: '', external_id: '', notes: '', updated_at: '2026-10-17T00:00:00Z',
  } as unknown as CustomerDetail
}
const windowStub = {
  props: ['modelValue', 'width', 'height', 'beforeClose', 'minimizable'], emits: ['update:modelValue'],
  template: '<section v-if="modelValue"><div class="app-window-dialog__body"><slot /></div><footer><slot name="footer" /></footer></section>',
}
let wrapper: VueWrapper | undefined
beforeEach(() => {
  vi.resetAllMocks(); mocks.canEdit = true; mocks.leave = []; mocks.update = []
  mocks.fetchCustomer.mockImplementation(async (id: string) => ({ data: customer(id), etag: '"customer-v1"' }))
  mocks.fetchCustomerOptions.mockResolvedValue(options)
  mocks.fetchCustomerEntities.mockResolvedValue([])
  mocks.fetchEntityAddresses.mockResolvedValue([])
  mocks.checkCustomerDuplicates.mockResolvedValue({ matches: [] })
  vi.spyOn(ElMessage, 'success').mockImplementation(() => ({ close: vi.fn() }))
  vi.spyOn(ElMessage, 'warning').mockImplementation(() => ({ close: vi.fn() }))
  vi.spyOn(ElMessage, 'error').mockImplementation(() => ({ close: vi.fn() }))
  vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue('confirm' as Awaited<ReturnType<typeof ElMessageBox.confirm>>)
})
afterEach(() => { wrapper?.unmount(); wrapper = undefined; document.body.innerHTML = ''; vi.restoreAllMocks() })
async function setup(open = true, id = 'customer-1') {
  wrapper = mount(CustomerEditDialog, { props: { modelValue: open, customerId: id }, attachTo: document.body, global: { plugins: [ElementPlus], stubs: { AppWindowDialog: windowStub } } })
  await flushPromises(); return wrapper
}
function button(view: VueWrapper, text: string) { return view.get('footer').findAll('button').find(item => item.text() === text)! }
async function editName(view: VueWrapper) { await view.get('[data-field="accountName"] input').setValue('修改后的客户') }
function requestError(status: number) {
  return new AxiosError('request failed', undefined, undefined, undefined, { status, statusText: '', headers: {}, config: { headers: new AxiosHeaders() }, data: {} })
}

describe('客户编辑弹窗', () => {
  it('关闭且编号为空时不请求，打开后读取数据并使用固定窗口和原表单', async () => {
    const view = await setup(false, '')
    expect(mocks.fetchCustomer).not.toHaveBeenCalled()
    await view.setProps({ modelValue: true, customerId: 'customer-1' }); await flushPromises()
    expect(mocks.fetchCustomer).toHaveBeenCalledWith('customer-1')
    expect(view.getComponent(AppWindowDialog).props()).toMatchObject({ width: 1040, height: 780, minimizable: false })
    expect(view.find('.edit-context').exists()).toBe(false)
    expect(view.get('.edit-section-nav').findAll('button').map(item => item.text())).toEqual(['主体资料', '地址属性', '客户属性', '归属与标签'])
    expect(view.find('h1').exists()).toBe(false)
    expect(view.get('[data-field="accountName"] input').element).toHaveProperty('value', '客户customer-1')
    expect(view.findAllComponents({ name: 'ElFormItem' }).length).toBe(33)
    expect(view.get('footer').findAll('button').map(item => item.text())).toEqual(['取消', '保存'])
  })

  it('分区导航定位弹窗正文，手动滚动同步选中，重开回到主体资料', async () => {
    const view = await setup()
    const body = view.get<HTMLElement>('.app-window-dialog__body').element
    const scrollTo = vi.fn()
    Object.defineProperty(body, 'scrollTo', { configurable: true, value: scrollTo })
    vi.spyOn(body, 'getBoundingClientRect').mockReturnValue({ top: 40 } as DOMRect)
    const sectionTops = [60, 400, 760, 1000]
    for (const [index, id] of ['profile', 'address', 'attributes', 'ownership'].entries()) {
      vi.spyOn(view.get(`#edit-section-${id}`).element, 'getBoundingClientRect').mockImplementation(() => ({ top: sectionTops[index]! - body.scrollTop } as DOMRect))
    }
    const nav = view.get('.edit-section-nav').findAll('button')
    await nav[1]!.trigger('click')
    expect(scrollTo).toHaveBeenCalledWith({ top: 352, behavior: 'auto' })
    expect(nav[1]!.attributes('aria-current')).toBe('location')
    body.scrollTop = 720
    await view.get('.app-window-dialog__body').trigger('scroll')
    expect(nav[2]!.attributes('aria-current')).toBe('location')
    expect(nav[1]!.attributes('aria-current')).toBeUndefined()
    Object.defineProperty(body, 'clientHeight', { configurable: true, value: 600 })
    Object.defineProperty(body, 'scrollHeight', { configurable: true, value: 1500 })
    body.scrollTop = 900
    await view.get('.app-window-dialog__body').trigger('scroll')
    expect(nav[3]!.attributes('aria-current')).toBe('location')
    await view.setProps({ modelValue: false })
    await view.setProps({ modelValue: true }); await flushPromises()
    expect(view.get('.edit-section-nav button').attributes('aria-current')).toBe('location')
    expect(view.get('.app-window-dialog__body').element.scrollTop).toBe(0)
  })

  it('切换客户或关闭后迟到的关联数据不能覆盖新客户，重新打开再次加载', async () => {
    let resolveOld!: (value: unknown[]) => void
    mocks.fetchCustomerEntities.mockReturnValueOnce(new Promise(resolve => { resolveOld = resolve }))
    const view = await setup()
    await view.setProps({ customerId: 'customer-2' }); await flushPromises()
    resolveOld([{ id: 'old-entity' }]); await flushPromises()
    expect(mocks.fetchCustomerEntity).not.toHaveBeenCalled()
    expect(view.get('[data-field="accountName"] input').element).toHaveProperty('value', '客户customer-2')
    await view.setProps({ modelValue: false }); await view.setProps({ modelValue: true }); await flushPromises()
    expect(mocks.fetchCustomer).toHaveBeenCalledTimes(3)
    let resolveClosed!: (value: unknown) => void
    mocks.fetchCustomer.mockReturnValueOnce(new Promise(resolve => { resolveClosed = resolve }))
    await view.setProps({ customerId: 'customer-3' }); await view.setProps({ modelValue: false })
    const callsBefore = mocks.fetchCustomerEntities.mock.calls.length
    resolveClosed({ data: customer('customer-3'), etag: 'v3' }); await flushPromises()
    expect(mocks.fetchCustomerEntities).toHaveBeenCalledTimes(callsBefore)
  })

  it('脏表单关闭与路由离开需要确认，取消保留输入，刷新有保护', async () => {
    const view = await setup(); await editName(view)
    vi.mocked(ElMessageBox.confirm).mockRejectedValueOnce('cancel')
    await button(view, '取消').trigger('click'); await flushPromises()
    expect(view.emitted('cancelled')).toBeUndefined()
    const event = new Event('beforeunload', { cancelable: true }); window.dispatchEvent(event)
    expect(event.defaultPrevented).toBe(true)
    vi.mocked(ElMessageBox.confirm).mockRejectedValueOnce('cancel')
    expect(await mocks.leave[0]!()).toBe(false)
    await button(view, '取消').trigger('click'); await flushPromises()
    expect(view.emitted('cancelled')).toEqual([[]])
    expect(view.emitted('update:modelValue')).toEqual([[false]])
  })

  it('保存中禁止关闭和离开，普通保存携带ETag、刷新后保持打开', async () => {
    let resolveSave!: () => void
    mocks.updateCustomer.mockReturnValue(new Promise<void>(resolve => { resolveSave = resolve }))
    const view = await setup(); await editName(view)
    await button(view, '保存').trigger('click'); await flushPromises()
    const done = vi.fn(); await view.getComponent(AppWindowDialog).props('beforeClose')!(done)
    expect(done).not.toHaveBeenCalled(); expect(await mocks.leave[0]!()).toBe(false)
    expect(button(view, '取消').attributes('disabled')).toBeDefined()
    expect(view.get('[data-field="accountName"] input').attributes('disabled')).toBeDefined()
    resolveSave(); await flushPromises()
    expect(mocks.updateCustomer).toHaveBeenCalledWith('customer-1', expect.objectContaining({ account_name: '修改后的客户' }), '"customer-v1"')
    expect(view.emitted('saved')).toEqual([['customer-1', false]])
    expect(view.emitted('update:modelValue')).toBeUndefined()
    expect(view.emitted('cancelled')).toBeUndefined()
    expect(ElMessage.success).toHaveBeenCalledWith('客户资料已保存。')
    expect(await mocks.leave[0]!()).toBe(true)
  })

  it('412保留输入与窗口，缺ETag禁止提交，均不报告保存成功', async () => {
    mocks.updateCustomer.mockRejectedValueOnce(requestError(412))
    const view = await setup(); await editName(view)
    await button(view, '保存').trigger('click'); await flushPromises()
    expect(ElMessage.error).toHaveBeenCalledWith('客户资料已被其他人修改，请刷新后重试。')
    expect(view.get('[data-field="accountName"] input').element).toHaveProperty('value', '修改后的客户')
    expect(view.emitted('saved')).toBeUndefined(); expect(view.emitted('update:modelValue')).toBeUndefined()
    await view.setProps({ modelValue: false })
    mocks.fetchCustomer.mockResolvedValueOnce({ data: customer(), etag: null })
    await view.setProps({ modelValue: true }); await flushPromises(); await editName(view)
    await button(view, '保存').trigger('click'); await flushPromises()
    expect(mocks.updateCustomer).toHaveBeenCalledTimes(1)
    expect(ElMessage.error).toHaveBeenLastCalledWith('缺少客户版本信息，请刷新页面后重试。')
    expect(ElMessage.success).not.toHaveBeenCalled()
  })

  it('后续分类保存失败保留部分成功提示并重载，不触发完成关闭', async () => {
    mocks.setCustomerGrade.mockRejectedValueOnce(requestError(500))
    const view = await setup()
    view.get('[data-field="gradeId"]').getComponent({ name: 'ElSelect' }).vm.$emit('update:modelValue', 'grade-b')
    await view.vm.$nextTick(); await button(view, '保存').trigger('click'); await flushPromises()
    expect(mocks.setCustomerGrade).toHaveBeenCalledWith('customer-1', { grade_item_id: 'grade-b', reason: '客户资料编辑' })
    expect(ElMessage.error).toHaveBeenCalledWith(expect.stringContaining('部分资料可能已保存'))
    expect(mocks.fetchCustomer).toHaveBeenCalledTimes(2)
    expect(view.emitted('saved')).toBeUndefined(); expect(ElMessage.success).not.toHaveBeenCalled()
  })

  it('权限不足不请求；加载失败可重试；保存后的重载失败不触发完成', async () => {
    mocks.canEdit = false
    const view = await setup()
    expect(view.text()).toContain('无权编辑客户'); expect(mocks.fetchCustomer).not.toHaveBeenCalled()
    view.unmount(); wrapper = undefined; mocks.canEdit = true
    mocks.fetchCustomer.mockRejectedValueOnce(requestError(500))
    const retry = await setup()
    expect(retry.text()).toContain('无法打开客户编辑')
    await retry.findAll('button').find(item => item.text() === '重新加载')!.trigger('click'); await flushPromises()
    await editName(retry)
    mocks.fetchCustomer.mockRejectedValueOnce(requestError(500))
    await button(retry, '保存').trigger('click'); await flushPromises()
    expect(retry.text()).toContain('无法打开客户编辑')
    expect(retry.emitted('saved')).toBeUndefined(); expect(ElMessage.success).not.toHaveBeenCalled()
  })

  it('校验只聚焦弹窗内字段，不操作背后页面同名输入框', async () => {
    document.body.innerHTML = '<div data-field="accountName"><input /></div>'
    const outside = document.querySelector('input')!; const outsideFocus = vi.spyOn(outside, 'focus')
    const view = await setup()
    const inside = view.get<HTMLInputElement>('[data-field="accountName"] input'); const insideFocus = vi.spyOn(inside.element, 'focus')
    await inside.setValue(''); await button(view, '保存').trigger('click'); await flushPromises()
    expect(insideFocus).toHaveBeenCalled(); expect(outsideFocus).not.toHaveBeenCalled()
    expect(mocks.updateCustomer).not.toHaveBeenCalled()
  })
})

describe('编辑客户直接URL兼容', () => {
  it('关闭与保存并返回回详情，普通保存不跳转', () => {
    wrapper = shallowMount(CustomerEditView)
    const dialog = wrapper.getComponent(CustomerEditDialog)
    expect(dialog.props()).toMatchObject({ modelValue: true, customerId: 'customer-1' })
    dialog.vm.$emit('saved', 'customer-1', false); expect(mocks.replace).not.toHaveBeenCalled()
    dialog.vm.$emit('saved', 'customer-1', true)
    expect(mocks.replace).toHaveBeenLastCalledWith({ name: 'customer-detail', params: { customerId: 'customer-1' } })
    mocks.replace.mockClear(); dialog.vm.$emit('update:modelValue', false)
    expect(mocks.replace).not.toHaveBeenCalled()
    dialog.vm.$emit('cancelled')
    expect(mocks.replace).toHaveBeenCalledExactlyOnceWith({ name: 'customer-detail', params: { customerId: 'customer-1' } })
  })
})
