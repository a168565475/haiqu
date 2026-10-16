import { mount } from '@vue/test-utils'
import { defineComponent, h, ref } from 'vue'
import { afterEach, expect, it, vi } from 'vitest'
import { useBoardAutoScroll } from './useBoardAutoScroll'

afterEach(() => vi.unstubAllGlobals())

it('以40px/秒无缝循环，停留和焦点暂停，内容不足时关闭并释放帧', async () => {
  let callback: FrameRequestCallback | undefined
  let resize: (() => void) | undefined
  const cancel = vi.fn()
  vi.stubGlobal('requestAnimationFrame', (next: FrameRequestCallback) => { callback = next; return 1 })
  vi.stubGlobal('cancelAnimationFrame', cancel)
  vi.stubGlobal('ResizeObserver', class { constructor(next: () => void) { resize = next } observe() {} disconnect() {} })
  vi.stubGlobal('matchMedia', () => ({ matches: false, addEventListener() {}, removeEventListener() {} }))
  const viewport = document.createElement('div')
  const content = document.createElement('div')
  Object.defineProperty(viewport, 'clientHeight', { value: 130 })
  Object.defineProperty(content, 'offsetHeight', { value: 200, configurable: true })
  let state!: ReturnType<typeof useBoardAutoScroll>
  const wrapper = mount(defineComponent({ setup() {
    state = useBoardAutoScroll(ref(viewport), ref(content), 30)
    return () => h('div')
  } }))
  const advance = (from: number, to: number) => { for (let time = from; time <= to; time += 20) callback?.(time) }
  expect(state.looping.value).toBe(true)
  advance(0, 1000)
  expect(viewport.scrollTop).toBeCloseTo(40)
  state.hovered.value = true
  advance(1020, 2000)
  expect(viewport.scrollTop).toBeCloseTo(40)
  state.hovered.value = false
  advance(2020, 3020)
  expect(viewport.scrollTop).toBeCloseTo(80.8)
  state.focused.value = true
  advance(3040, 4000)
  expect(viewport.scrollTop).toBeCloseTo(80.8)
  state.focused.value = false
  viewport.scrollTop = 199
  advance(4020, 4060)
  expect(viewport.scrollTop).toBeCloseTo(1.4)
  Object.defineProperty(content, 'offsetHeight', { value: 80 })
  resize?.()
  expect(state.looping.value).toBe(false)
  expect(viewport.scrollTop).toBe(0)
  wrapper.unmount()
  expect(cancel).toHaveBeenCalled()
})

it('减少动态效果时不复制、不自动滚动', () => {
  vi.stubGlobal('requestAnimationFrame', vi.fn())
  vi.stubGlobal('cancelAnimationFrame', vi.fn())
  vi.stubGlobal('matchMedia', () => ({ matches: true, addEventListener() {}, removeEventListener() {} }))
  const viewport = document.createElement('div')
  const content = document.createElement('div')
  Object.defineProperty(viewport, 'clientHeight', { value: 100 })
  Object.defineProperty(content, 'offsetHeight', { value: 200 })
  let state!: ReturnType<typeof useBoardAutoScroll>
  const wrapper = mount(defineComponent({ setup() {
    state = useBoardAutoScroll(ref(viewport), ref(content))
    return () => h('div')
  } }))
  expect(state.looping.value).toBe(false)
  expect(viewport.scrollTop).toBe(0)
  wrapper.unmount()
})
