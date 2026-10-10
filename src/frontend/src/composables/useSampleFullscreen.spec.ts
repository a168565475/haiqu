import { defineComponent, nextTick, ref } from 'vue'
import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'
import { useSampleFullscreen } from './useSampleFullscreen'

const Page = defineComponent({
  setup() {
    const root = ref<HTMLElement>()
    return { root, ...useSampleFullscreen(root) }
  },
  template: `<section ref="root"><button class="enter" @click="toggleFullscreen">全屏</button>
    <header v-if="fullscreen" class="fullscreen-header"><button @click="toggleFullscreen">退出全屏</button></header>
    <div class="el-message-box"><button class="confirm-cancel">保留</button></div>
    <div role="dialog"><input class="dialog-input"></div>
    <div class="el-select"><input class="select-input"></div>
    <input class="field">
  </section>`,
})
const wrappers: ReturnType<typeof mount>[] = []
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()); document.body.innerHTML = '' })

async function renderFullscreen() {
  const wrapper = mount(Page, { attachTo: document.body })
  wrappers.push(wrapper)
  ;(wrapper.find('.enter').element as HTMLButtonElement).focus()
  await wrapper.find('.enter').trigger('click')
  expect(document.activeElement).toBe(wrapper.find('.fullscreen-header button').element)
  return wrapper
}

describe('材料/仓库全屏 Escape 交互', () => {
  it.each(['.confirm-cancel', '.dialog-input', '.select-input'])('弹出控件 %s 内 Escape 保留全屏', async selector => {
    const wrapper = await renderFullscreen()
    await wrapper.find(selector).trigger('keydown', { key: 'Escape' })
    expect(wrapper.find('.fullscreen-header').exists()).toBe(true)
  })

  it('普通字段中 Escape 退出全屏并恢复原按钮焦点', async () => {
    const wrapper = await renderFullscreen()
    await wrapper.find('.field').trigger('keydown', { key: 'Escape' })
    expect(wrapper.find('.fullscreen-header').exists()).toBe(false)
    expect(document.activeElement).toBe(wrapper.find('.enter').element)
  })

  it('尊重已经被内部控件处理的 Escape', async () => {
    const wrapper = await renderFullscreen()
    const event = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })
    event.preventDefault()
    wrapper.find('.field').element.dispatchEvent(event)
    await nextTick()
    expect(wrapper.find('.fullscreen-header').exists()).toBe(true)
  })
})
