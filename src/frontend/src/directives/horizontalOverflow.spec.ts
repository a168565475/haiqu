import { defineComponent } from 'vue'
import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { vHorizontalOverflow } from './horizontalOverflow'

const observers: { callback: ResizeObserverCallback; observe: ReturnType<typeof vi.fn>; unobserve: ReturnType<typeof vi.fn>; disconnect: ReturnType<typeof vi.fn> }[] = []
const wrappers: ReturnType<typeof mount>[] = []
let visibleWidth = 600
let contentWidth = 900

function render() {
  vi.stubGlobal('ResizeObserver', class {
    observe = vi.fn()
    unobserve = vi.fn()
    disconnect = vi.fn()
    constructor(public callback: ResizeObserverCallback) { observers.push(this) }
  })
  vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockImplementation(() => visibleWidth)
  vi.spyOn(HTMLElement.prototype, 'scrollWidth', 'get').mockImplementation(() => contentWidth)
  const wrapper = mount(defineComponent({
    directives: { horizontalOverflow: vHorizontalOverflow },
    template: '<div v-horizontal-overflow><table><tbody><tr><td>查看</td></tr></tbody></table></div>',
  }))
  wrappers.push(wrapper)
  return wrapper
}

afterEach(() => {
  wrappers.splice(0).forEach(wrapper => wrapper.unmount())
  observers.splice(0)
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  visibleWidth = 600
  contentWidth = 900
})

describe('表格横向溢出状态', () => {
  it('仅在实际超出容器宽度时启用，窗口变宽后关闭', () => {
    const wrapper = render()
    expect(wrapper.attributes('data-horizontal-overflow')).toBe('true')
    visibleWidth = 900
    observers[0]!.callback([], {} as ResizeObserver)
    expect(wrapper.attributes('data-horizontal-overflow')).toBe('false')
    contentWidth = 901
    observers[0]!.callback([], {} as ResizeObserver)
    expect(wrapper.attributes('data-horizontal-overflow')).toBe('true')
  })

  it('同时观察表格及容器，隐藏时关闭，重新显示时恢复', () => {
    const wrapper = render()
    expect(observers[0]!.observe).toHaveBeenCalledWith(wrapper.element)
    expect(observers[0]!.observe).toHaveBeenCalledWith(wrapper.find('table').element)
    visibleWidth = 0
    observers[0]!.callback([], {} as ResizeObserver)
    expect(wrapper.attributes('data-horizontal-overflow')).toBe('false')
    visibleWidth = 600
    observers[0]!.callback([], {} as ResizeObserver)
    expect(wrapper.attributes('data-horizontal-overflow')).toBe('true')
  })

  it('卸载时释放尺寸观察器', () => {
    const wrapper = render()
    wrapper.unmount()
    expect(observers[0]!.disconnect).toHaveBeenCalledOnce()
  })
})
