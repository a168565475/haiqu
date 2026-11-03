import { mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'
import ProductCatalogOptionsInput from './ProductCatalogOptionsInput.vue'

let wrapper: VueWrapper
afterEach(() => wrapper?.unmount())
describe('产品多值草稿输入', () => {
  it('连续添加仅追加空框；输入、Enter和blur不提交，单独取消不丢其他输入', async () => {
    wrapper = mount(ProductCatalogOptionsInput, {
      props: { modelValue: ['白色'], label: '颜色', 'onUpdate:modelValue': (value: string[]) => { void wrapper.setProps({ modelValue: value }) } },
    })
    await wrapper.get('[aria-label="添加颜色"]').trigger('click')
    await wrapper.get('[aria-label="添加颜色"]').trigger('click')
    expect(wrapper.findAll('input')).toHaveLength(3)
    await wrapper.get('[aria-label="颜色2"]').setValue('黑色')
    await wrapper.get('[aria-label="颜色3"]').trigger('keydown', { key: 'Enter' })
    await wrapper.get('[aria-label="颜色3"]').trigger('blur')
    await wrapper.get('[aria-label="删除颜色1"]').trigger('click')
    expect(wrapper.findAll('input').map(input => (input.element as HTMLInputElement).value)).toEqual(['黑色', ''])
    expect(Object.keys(wrapper.emitted()).filter(event => !['keydown', 'blur', 'click', 'input', 'change'].includes(event))).toEqual(['update:modelValue'])
    expect(wrapper.find('form').exists()).toBe(false)
  })
  it('只读展示无修改入口，保存期间禁用全部输入和按钮', async () => {
    wrapper = mount(ProductCatalogOptionsInput, { props: { modelValue: ['铝'], label: '材质', readonly: true } })
    expect(wrapper.text()).toContain('铝')
    expect(wrapper.find('input').exists()).toBe(false)
    expect(wrapper.find('button').exists()).toBe(false)
    await wrapper.setProps({ readonly: false, disabled: true })
    expect(wrapper.get('input').attributes('disabled')).toBeDefined()
    expect(wrapper.findAll('button').every(button => button.attributes('disabled') !== undefined)).toBe(true)
    await wrapper.get('[aria-label="添加材质"]').trigger('click')
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
  })
})
