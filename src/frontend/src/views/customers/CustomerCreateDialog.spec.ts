import { flushPromises, mount, shallowMount, type VueWrapper } from '@vue/test-utils'
import { defineComponent, watch } from 'vue'
import ElementPlus, { ElMessage, ElMessageBox } from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import CustomerCreateDialog from './CustomerCreateDialog.vue'
import CustomerCreateView from './CustomerCreateView.vue'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import type { CustomerOptions } from '@/types/customer'

const mocks = vi.hoisted(() => ({
  canCreate: true, fetchCustomerOptions: vi.fn(), createCustomer: vi.fn(), checkCustomerDuplicates: vi.fn(), replace: vi.fn(),
  leave: [] as Array<() => Promise<boolean>>, update: [] as Array<() => Promise<boolean>>,
}))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: () => mocks.canCreate }) }))
vi.mock('@/api/customers', () => ({ fetchCustomerOptions: mocks.fetchCustomerOptions, createCustomer: mocks.createCustomer, checkCustomerDuplicates: mocks.checkCustomerDuplicates }))
vi.mock('vue-router', () => ({
  useRouter: () => ({ replace: mocks.replace }),
  onBeforeRouteLeave: (guard: () => Promise<boolean>) => mocks.leave.push(guard),
  onBeforeRouteUpdate: (guard: () => Promise<boolean>) => mocks.update.push(guard),
}))
const options: CustomerOptions = {
  lifecycle_stages: [], activity_statuses: [], customer_grades: [], customer_types: [], customer_tags: [],
  customer_sources: [{ id: 'source-1', item_code: 'WEB', display_name: '网站', description: '' }],
  primary_regions: [{ id: 'europe', region_name: '欧洲', legacy_selector_code: 'EU', legacy_tree_code: 'EU' }],
  secondary_regions: [{ id: 'de', parent_id: 'europe', country_code: 'DE', region_name: '德国', legacy_selector_code: 'DE', legacy_tree_code: 'EU-DE' }],
  industries: [], interested_products: [], owner_options: [], country_options: [],
}
const windowStub = {
  props: ['modelValue', 'title', 'width', 'height', 'beforeClose'],
  emits: ['update:modelValue'],
  template: '<section v-if="modelValue"><slot /><footer><slot name="footer" /></footer></section>',
}
let wrapper: VueWrapper | undefined
beforeEach(() => {
  vi.clearAllMocks()
  mocks.leave = []; mocks.update = []; mocks.canCreate = true
  mocks.fetchCustomerOptions.mockResolvedValue(options)
  mocks.createCustomer.mockResolvedValue({ data: { id: 'created-1' } })
  mocks.checkCustomerDuplicates.mockResolvedValue({ matches: [] })
  vi.spyOn(ElMessage, 'success').mockImplementation(() => ({ close: vi.fn() }))
  vi.spyOn(ElMessage, 'warning').mockImplementation(() => ({ close: vi.fn() }))
  vi.spyOn(ElMessage, 'error').mockImplementation(() => ({ close: vi.fn() }))
  vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue('confirm' as Awaited<ReturnType<typeof ElMessageBox.confirm>>)
})
afterEach(() => {
  wrapper?.unmount(); wrapper = undefined
  document.body.innerHTML = ''
  vi.restoreAllMocks(); vi.useRealTimers()
})
async function setup() {
  wrapper = mount(CustomerCreateDialog, { props: { modelValue: true }, global: { plugins: [ElementPlus], stubs: { AppWindowDialog: windowStub } } })
  await flushPromises()
  return wrapper
}
async function fillValid(view: VueWrapper) {
  await view.get('[data-field="accountName"] input').setValue('测试客户')
  for (const [field, value] of [['primaryRegionId', 'europe'], ['secondaryRegionId', 'de'], ['sourceId', 'source-1']]) {
    view.get(`[data-field="${field}"]`).getComponent({ name: 'ElSelect' }).vm.$emit('update:modelValue', value)
    await view.vm.$nextTick()
  }
  await view.get('[data-field="contactName"] input').setValue('Anna')
  await view.get('[data-field="contactMethod"] input').setValue('anna@example.com')
}
function footerButton(view: VueWrapper, text: string) { return view.get('footer').findAll('button').find(button => button.text() === text)! }

describe('新建客户弹窗', () => {
  it('打开920×620的窗口，只展示姓名和邮箱输入', async () => {
    const main = document.createElement('main'); main.id = 'erp-main-content'; document.body.append(main)
    vi.spyOn(main, 'getBoundingClientRect').mockReturnValue({ width: 980, height: 808 } as DOMRect)
    const view = await setup()
    expect(view.getComponent(AppWindowDialog).props()).toMatchObject({ width: 920, height: 620 })
    expect(view.get('.contact-grid').findAll('input')).toHaveLength(2)
    expect(view.get('[data-field="contactMethod"] input').attributes('type')).toBe('email')
    expect(view.get('.contact-grid').text()).not.toContain('电话')
  })

  it('拒绝把电话当邮箱提交；成功后输出客户ID且不触发取消事件', async () => {
    const view = await setup(); await fillValid(view)
    await view.get('[data-field="contactMethod"] input').setValue('+49 12345678')
    await footerButton(view, '创建客户').trigger('click'); await flushPromises()
    expect(mocks.createCustomer).not.toHaveBeenCalled()
    expect(view.get('[data-field="contactMethod"]').getComponent({ name: 'ElFormItem' }).props('error')).toBe('请输入有效的邮箱地址。')
    await view.get('[data-field="contactMethod"] input').setValue('anna@example.com')
    await footerButton(view, '创建客户').trigger('click'); await flushPromises()
    expect(mocks.createCustomer).toHaveBeenCalledWith(expect.objectContaining({ primary_country_code: 'DE', contact_name: 'Anna', contact_method_type: 'EMAIL', contact_method_value: 'anna@example.com' }))
    expect(view.emitted('created')).toEqual([['created-1', false]])
    expect(view.emitted('update:modelValue')).toEqual([[false]])
    expect(view.emitted('cancelled')).toBeUndefined()
    expect(await mocks.leave[0]!()).toBe(true)
  })

  it('继续创建保留窗口并重置已保存表单，下一次关闭不再提示未保存', async () => {
    const view = await setup(); await fillValid(view)
    await footerButton(view, '继续创建').trigger('click'); await flushPromises()
    expect(view.emitted('created')).toEqual([['created-1', true]])
    expect(view.emitted('update:modelValue')).toBeUndefined()
    expect((view.get('[data-field="accountName"] input').element as HTMLInputElement).value).toBe('')
    expect(await mocks.leave[0]!()).toBe(true)
    expect(ElMessageBox.confirm).not.toHaveBeenCalled()
  })

  it('脏表单取消关闭时保留输入，确认放弃后才关闭', async () => {
    const view = await setup()
    await view.get('[data-field="accountName"] input').setValue('尚未保存')
    vi.mocked(ElMessageBox.confirm).mockRejectedValueOnce('cancel')
    await footerButton(view, '取消').trigger('click'); await flushPromises()
    expect(view.emitted('update:modelValue')).toBeUndefined()
    expect((view.get('[data-field="accountName"] input').element as HTMLInputElement).value).toBe('尚未保存')
    await footerButton(view, '取消').trigger('click'); await flushPromises()
    expect(view.emitted('cancelled')).toEqual([[]])
    expect(view.emitted('update:modelValue')).toEqual([[false]])
  })

  it('提交过程中拒绝关闭和离开，失败保留内容与窗口', async () => {
    let reject!: (error: Error) => void
    mocks.createCustomer.mockReturnValue(new Promise((_resolve, rejectPromise) => { reject = rejectPromise }))
    const view = await setup(); await fillValid(view)
    await footerButton(view, '创建客户').trigger('click'); await flushPromises()
    const done = vi.fn()
    await view.getComponent(AppWindowDialog).props('beforeClose')!(done)
    expect(done).not.toHaveBeenCalled()
    expect(await mocks.leave[0]!()).toBe(false)
    const event = new Event('beforeunload', { cancelable: true }); window.dispatchEvent(event)
    expect(event.defaultPrevented).toBe(true)
    reject(new Error('请求失败')); await flushPromises()
    expect(view.emitted('created')).toBeUndefined()
    expect(view.emitted('update:modelValue')).toBeUndefined()
    expect((view.get('[data-field="accountName"] input').element as HTMLInputElement).value).toBe('测试客户')
    expect(ElMessage.error).toHaveBeenCalled()
  })

  it('无创建权限不读取选项且不能提交；加载失败可以重试', async () => {
    mocks.canCreate = false
    const forbidden = await setup()
    expect(forbidden.text()).toContain('无权新建客户')
    expect(mocks.fetchCustomerOptions).not.toHaveBeenCalled()
    expect(footerButton(forbidden, '创建客户').attributes('disabled')).toBeDefined()
    forbidden.unmount(); wrapper = undefined; mocks.canCreate = true
    mocks.fetchCustomerOptions.mockRejectedValueOnce(new Error('网络失败'))
    const view = await setup()
    expect(view.text()).toContain('无法打开新建客户')
    await view.findAll('button').find(button => button.text() === '重新加载')!.trigger('click'); await flushPromises()
    expect(view.find('[data-field="accountName"]').exists()).toBe(true)
  })

  it('较早查重请求晚到不能覆盖新结果，选择真实匹配客户通过关闭确认', async () => {
    let resolveOld!: (value: unknown) => void
    mocks.checkCustomerDuplicates.mockReturnValueOnce(new Promise(resolve => { resolveOld = resolve }))
      .mockResolvedValueOnce({ matches: [{ customer_id: 'existing-2', account_name: '最新匹配客户', account_code: 'KH-2', primary_country_code: 'DE', lifecycle_stage: 'LEAD', primary_website_url: '', match_level: 'HIGH', match_score: 95 }] })
    const view = await setup(); vi.useFakeTimers()
    await view.get('[data-field="accountName"] input').setValue('第一次名称')
    await vi.advanceTimersByTimeAsync(400)
    await view.get('[data-field="accountName"] input').setValue('第二次名称')
    await vi.advanceTimersByTimeAsync(400)
    resolveOld({ matches: [{ customer_id: 'old-1', account_name: '过期匹配客户' }] })
    await flushPromises()
    expect(view.text()).toContain('最新匹配客户')
    expect(view.text()).not.toContain('过期匹配客户')
    await view.findAll('button').find(button => button.text() === '选择已有客户')!.trigger('click'); await flushPromises()
    expect(ElMessageBox.confirm).toHaveBeenCalled()
    expect(view.emitted('openExisting')).toEqual([['existing-2']])
    expect(view.emitted('cancelled')).toBeUndefined()
    expect(mocks.createCustomer).not.toHaveBeenCalled()
  })
})

describe('新建客户直接URL适配', () => {
  it.each([{ width: 979, height: 808 }, { width: 1798, height: 1004 }])('主内容区为 $width × $height 时，直接入口仍使用920×620窗口', async bounds => {
    const initialSizes: Array<{ width: number | undefined, height: number | string | undefined }> = []
    const originalBounds = HTMLElement.prototype.getBoundingClientRect
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
      return this.id === 'erp-main-content' ? bounds as DOMRect : originalBounds.call(this)
    })
    const initialSizeWindow = defineComponent({
      props: { modelValue: Boolean, width: Number, height: [Number, String] },
      setup(props) {
        watch(() => props.modelValue, visible => {
          if (visible) initialSizes.push({ width: props.width, height: props.height })
        }, { immediate: true })
      },
      template: '<section />',
    })
    wrapper = mount({ components: { CustomerCreateView }, template: '<main id="erp-main-content"><CustomerCreateView /></main>' }, {
      attachTo: document.body,
      global: { plugins: [ElementPlus], stubs: { AppWindowDialog: initialSizeWindow } },
    })
    await flushPromises()
    expect(initialSizes).toEqual([{ width: 920, height: 620 }])
  })

  it('创建成功只进入新客户详情，不先跳列表；继续创建保持当前路由', async () => {
    wrapper = shallowMount(CustomerCreateView)
    const dialog = wrapper.getComponent(CustomerCreateDialog)
    dialog.vm.$emit('created', 'created-1', true)
    expect(mocks.replace).not.toHaveBeenCalled()
    dialog.vm.$emit('update:modelValue', false)
    dialog.vm.$emit('created', 'created-1', false)
    expect(mocks.replace).toHaveBeenCalledExactlyOnceWith({ name: 'customer-detail', params: { customerId: 'created-1' } })
  })
  it('直接URL关闭回到客户列表，选择已有客户进入其详情', () => {
    wrapper = shallowMount(CustomerCreateView)
    const dialog = wrapper.getComponent(CustomerCreateDialog)
    dialog.vm.$emit('cancelled')
    expect(mocks.replace).toHaveBeenLastCalledWith({ name: 'customers' })
    dialog.vm.$emit('openExisting', 'existing-1')
    expect(mocks.replace).toHaveBeenLastCalledWith({ name: 'customer-detail', params: { customerId: 'existing-1' } })
  })
})
