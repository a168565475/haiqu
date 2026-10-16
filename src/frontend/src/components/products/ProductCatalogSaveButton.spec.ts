import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'
import ProductCatalogSaveButton from './ProductCatalogSaveButton.vue'

let wrapper: VueWrapper | undefined
afterEach(() => { wrapper?.unmount(); wrapper = undefined; document.body.replaceChildren() })

describe('产品行内保存按钮', () => {
  it('处理中保留焦点和原标签占位，提供旋转图标、状态文本并拦截重复提交', async () => {
    wrapper = mount(ProductCatalogSaveButton, { attachTo: document.body, props: { label: '保存', ariaLabel: '保存规格', loading: false } })
    const button = wrapper.get('button')
    ;(button.element as HTMLButtonElement).focus()
    await button.trigger('click')
    expect(wrapper.emitted('click')).toHaveLength(1)
    await wrapper.setProps({ loading: true, disabled: true })
    expect(document.activeElement).toBe(button.element)
    expect(button.attributes('disabled')).toBeUndefined()
    expect(button.attributes('aria-disabled')).toBe('true')
    expect(button.attributes('aria-busy')).toBe('true')
    expect(button.get('[data-save-label]').text()).toBe('保存')
    expect(button.find('[data-save-spinner]').exists()).toBe(true)
    expect(wrapper.get('[role="status"]').text()).toBe('处理中…')
    await button.trigger('click')
    const keyboard = new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true })
    button.element.dispatchEvent(keyboard)
    expect(keyboard.defaultPrevented).toBe(true)
    expect(wrapper.emitted('click')).toHaveLength(1)
    await wrapper.setProps({ loading: false, disabled: false })
    await button.trigger('click')
    expect(wrapper.emitted('click')).toHaveLength(2)
    expect(button.find('[data-save-spinner]').exists()).toBe(false)
  })

  it('处理中聚焦可阅读可见悬浮说明，结束后关闭', async () => {
    wrapper = mount(ProductCatalogSaveButton, { attachTo: document.body, props: { label: '保存产品', ariaLabel: '保存产品', loading: false } })
    ;(wrapper.get('button').element as HTMLButtonElement).focus()
    await wrapper.setProps({ loading: true }); await flushPromises()
    await new Promise(resolve => setTimeout(resolve, 40)); await flushPromises()
    const popper = document.querySelector<HTMLElement>('.product-catalog-saving-popper')
    expect(popper?.textContent).toContain('处理中…')
    expect(popper?.getAttribute('aria-hidden')).not.toBe('true')
    await wrapper.setProps({ loading: false }); await flushPromises()
    expect(wrapper.find('[role="status"]').exists()).toBe(false)
  })
})
