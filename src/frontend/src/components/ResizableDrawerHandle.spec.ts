import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'

import ResizableDrawerHandle from './ResizableDrawerHandle.vue'

const mountedWrappers: ReturnType<typeof mount>[] = []

function pointerEvent(type: string, properties: Record<string, number>): Event {
  const event = new Event(type, { bubbles: true, cancelable: true })
  Object.entries(properties).forEach(([key, value]) => {
    Object.defineProperty(event, key, { value })
  })
  return event
}

function mountDrawer(width = 680) {
  Object.defineProperty(window, 'innerWidth', { configurable: true, value: 1200 })
  const wrapper = mount({
    components: { ResizableDrawerHandle },
    template: `<section class="el-drawer" style="position: fixed; right: 0; width: ${width}px"><ResizableDrawerHandle /></section>`,
  }, { attachTo: document.body })
  mountedWrappers.push(wrapper)

  const drawer = wrapper.get('.el-drawer').element as HTMLElement
  drawer.getBoundingClientRect = () => {
    const currentWidth = Number.parseFloat(drawer.style.width)
    return {
      x: 1200 - currentWidth,
      y: 0,
      top: 0,
      right: 1200,
      bottom: 800,
      left: 1200 - currentWidth,
      width: currentWidth,
      height: 800,
      toJSON: () => ({}),
    }
  }
  return { wrapper, drawer }
}

afterEach(() => {
  mountedWrappers.splice(0).forEach((wrapper) => wrapper.unmount())
})

describe('ResizableDrawerHandle', () => {
  it('支持使用左右方向键调整抽屉宽度', async () => {
    const { wrapper, drawer } = mountDrawer()
    const handle = wrapper.get('button')

    await handle.trigger('keydown', { key: 'ArrowLeft' })
    expect(drawer.style.width).toBe('704px')

    await handle.trigger('keydown', { key: 'ArrowRight' })
    expect(drawer.style.width).toBe('680px')
  })

  it('拖动左边缘时调整宽度并遵守最小值', () => {
    const { wrapper, drawer } = mountDrawer()
    const handle = wrapper.get('button').element as HTMLButtonElement
    handle.setPointerCapture = () => undefined
    handle.hasPointerCapture = () => false

    handle.dispatchEvent(pointerEvent('pointerdown', { button: 0, pointerId: 1, clientX: 520 }))
    window.dispatchEvent(pointerEvent('pointermove', { pointerId: 1, clientX: 400 }))
    expect(drawer.style.width).toBe('800px')

    window.dispatchEvent(pointerEvent('pointermove', { pointerId: 1, clientX: 1100 }))
    expect(drawer.style.width).toBe('320px')
    window.dispatchEvent(pointerEvent('pointerup', { pointerId: 1, clientX: 1100 }))
  })
})
