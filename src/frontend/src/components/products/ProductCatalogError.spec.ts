import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'
import { defineComponent } from 'vue'
import ProductCatalogError from './ProductCatalogError.vue'

let wrapper: VueWrapper | undefined
const settle = async () => { await flushPromises(); await new Promise(resolve => setTimeout(resolve, 40)); await flushPromises() }
const visibleBubbles = () => [...document.querySelectorAll<HTMLElement>('.product-catalog-error-popper')]
  .filter(item => getComputedStyle(item).display !== 'none' && item.getAttribute('aria-hidden') !== 'true')
async function render() {
  wrapper = mount(defineComponent({ components: { ProductCatalogError }, template: '<div><ProductCatalogError message="第一个字段错误" /><ProductCatalogError message="第二个字段错误" /><button class="outside">其他位置</button></div>' }), { attachTo: document.body })
  await settle()
  return wrapper.findAll('.product-catalog-field-error')
}
afterEach(() => { wrapper?.unmount(); wrapper = undefined; document.body.replaceChildren() })

describe('产品字段错误气泡的真实 Element Plus 行为', () => {
  it('先聚焦第一处再悬停第二处，页面始终只显示当前错误', async () => {
    const triggers = await render()
    ;(triggers[0]!.element as HTMLElement).focus(); await settle()
    expect(visibleBubbles()).toHaveLength(1)
    await triggers[1]!.trigger('mouseenter'); await settle()
    expect(visibleBubbles()).toHaveLength(1)
    expect(visibleBubbles()[0]!.textContent).toContain('第二个字段错误')
  })

  it('外部点击关闭，仍保持焦点不会自动重新展开', async () => {
    const triggers = await render()
    ;(triggers[0]!.element as HTMLElement).focus(); await settle()
    expect(visibleBubbles()).toHaveLength(1)
    await wrapper!.get('.outside').trigger('click'); await settle()
    expect(visibleBubbles()).toHaveLength(0)
    expect(document.activeElement).toBe(triggers[0]!.element)
    await settle()
    expect(visibleBubbles()).toHaveLength(0)
    await triggers[0]!.trigger('click'); await settle()
    expect(visibleBubbles()).toHaveLength(1)
  })

  it('Esc关闭悬停或聚焦气泡，只有新的主动触发才能重新打开', async () => {
    const triggers = await render()
    ;(triggers[0]!.element as HTMLElement).focus()
    await triggers[0]!.trigger('mouseenter'); await settle()
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', code: 'Escape', bubbles: true }))
    await settle()
    expect(visibleBubbles()).toHaveLength(0)
    await triggers[0]!.trigger('mousemove'); await settle()
    expect(visibleBubbles()).toHaveLength(0)
    await triggers[0]!.trigger('mouseleave')
    await triggers[0]!.trigger('mouseenter'); await settle()
    expect(visibleBubbles()).toHaveLength(1)
  })

  it('鼠标可移入错误内容阅读，离开触发区和内容后关闭', async () => {
    const triggers = await render()
    await triggers[0]!.trigger('mouseenter'); await settle()
    const bubble = visibleBubbles()[0]!
    await triggers[0]!.trigger('mouseleave')
    bubble.querySelector('[data-error-content]')?.dispatchEvent(new MouseEvent('mouseenter'))
    await new Promise(resolve => setTimeout(resolve, 180)); await settle()
    expect(visibleBubbles()).toHaveLength(1)
    bubble.querySelector('[data-error-content]')?.dispatchEvent(new MouseEvent('mouseleave'))
    await new Promise(resolve => setTimeout(resolve, 180)); await settle()
    expect(visibleBubbles()).toHaveLength(0)
  })
})
