import { DOMWrapper, flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import InquiryProductDialog from './InquiryProductDialog.vue'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import type { InquiryItem } from '@/types/inquiry'

vi.mock('@/api/inquiries', () => ({
  fetchInquiryProductSelectionOptions: vi.fn().mockResolvedValue({ groups: [] }),
  inquiryProductImageUrl: () => '',
}))

const item: InquiryItem = {
  product_id: 'p1', product_category_id: 'c1', product_unit_id: 'u1', product_color_id: 'color1',
  product_description: '三折床', specification: '186*55*24cm', unit_code: 'PCS',
  color: '深宝蓝', material: 'PE', quantity: '1000', target_unit_price: null,
  target_currency_code: '', expected_date: null, product_match_status: 'MATCHED', notes: '',
}
const control = { props: ['modelValue', 'disabled'], emits: ['update:modelValue', 'change'], template: '<input :value="modelValue" :disabled="disabled" @input="$emit(\'update:modelValue\', $event.target.value)" @change="$emit(\'change\', $event.target.value)" />' }
const wrappers: ReturnType<typeof mount>[] = []
function open(reviewed = false) {
  const wrapper = mount(InquiryProductDialog, {
    attachTo: document.body,
    props: { modelValue: true, item: { ...item }, scene: 'bom', reviewed, closeOnConfirm: false,
      categories: [{ id: 'c1', category_name: '成品' }], units: [{ id: 'u1', unit_code: 'PCS', unit_name: '张' }],
      colors: [{ id: 'color1', color_name: '深宝蓝' }], currencies: [], canUpload: false },
    global: { stubs: { ElInput: control, ElSelect: control, ElOption: true, ElDatePicker: control,
      ElButton: { props: ['disabled'], template: '<button :disabled="disabled"><slot /></button>' } } },
  })
  wrappers.push(wrapper)
  return wrapper
}
const body = () => new DOMWrapper(document.body)
const button = (label: string) => body().findAll('button').find(row => row.text() === label)!
beforeEach(() => vi.clearAllMocks())
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()); document.body.innerHTML = '' })

describe('BOM 产品核对关闭保护', () => {
  it('未核对时所有关闭途径和最小化都不能绕回用料页', async () => {
    const wrapper = open()
    await flushPromises()
    expect(body().find('[aria-label="关闭"]').exists()).toBe(false)
    expect(body().find('[aria-label="最小化"]').exists()).toBe(false)
    expect(button('取消').attributes('disabled')).toBeDefined()
    await button('取消').trigger('click')
    await body().get('.app-window-overlay').trigger('click')
    await body().get('.app-window-overlay').trigger('keydown', { key: 'Escape' })
    wrapper.findComponent(AppWindowDialog).vm.$emit('update:modelValue', false)
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
    expect(document.body.style.overflow).toBe('hidden')
  })

  it('已核对未修改可以关闭，修改后取消和 Esc 必须被拦截', async () => {
    const unchanged = open(true)
    await flushPromises()
    await button('取消').trigger('click')
    expect(unchanged.emitted('update:modelValue')).toEqual([[false]])
    unchanged.unmount(); wrappers.pop()
    const changed = open(true)
    await flushPromises()
    await body().get('input[aria-label="材质"]').setValue('铝')
    expect(button('取消').attributes('disabled')).toBeDefined()
    expect(body().find('[aria-label="关闭"]').exists()).toBe(false)
    expect(body().find('[aria-label="最小化"]').exists()).toBe(false)
    await body().get('.app-window-overlay').trigger('keydown', { key: 'Escape' })
    expect(changed.emitted('update:modelValue')).toBeUndefined()
  })

  it('确认只发请求事件；保存失败保留输入和关闭保护，再次确认仍可提交', async () => {
    const wrapper = open()
    await flushPromises()
    await body().get('input[aria-label="材质"]').setValue('铝')
    await button('确认本次产品信息').trigger('click')
    expect(wrapper.emitted('confirm')).toHaveLength(1)
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
    await wrapper.setProps({ busy: true })
    await button('确认本次产品信息').trigger('click')
    expect(wrapper.emitted('confirm')).toHaveLength(1)
    await wrapper.setProps({ busy: false, saveError: '版本冲突，请重试' })
    expect((body().get('input[aria-label="材质"]').element as HTMLInputElement).value).toBe('铝')
    expect(button('取消').attributes('disabled')).toBeDefined()
    expect(body().text()).toContain('版本冲突')
    await button('确认本次产品信息').trigger('click')
    expect(wrapper.emitted('confirm')).toHaveLength(2)
    await wrapper.setProps({ modelValue: false, reviewed: true })
    expect(body().get('.app-window-overlay').isVisible()).toBe(false)
  })

  it('字典失败可以原地重试，输入不重置', async () => {
    const wrapper = open()
    await flushPromises()
    await body().get('input[aria-label="材质"]').setValue('铝')
    await wrapper.setProps({ catalogError: '颜色维护加载失败' })
    const retry = button('重试基础资料')
    expect(retry).toBeDefined()
    await retry.trigger('click')
    expect(wrapper.emitted('retry-catalog')).toHaveLength(1)
    expect((body().get('input[aria-label="材质"]').element as HTMLInputElement).value).toBe('铝')
  })

  it('普通询盘仍允许取消与最小化', async () => {
    const wrapper = open()
    await wrapper.setProps({ scene: 'inquiry' })
    await flushPromises()
    expect(body().find('[aria-label="最小化"]').exists()).toBe(true)
    await button('取消').trigger('click')
    expect(wrapper.emitted('update:modelValue')).toEqual([[false]])
  })
})
