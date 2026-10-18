import { defineComponent } from 'vue'
import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { vGlassSpotlight } from './glassSpotlight'

const wrappers: ReturnType<typeof mount>[] = []
const frames = new Map<number, FrameRequestCallback>()
const pointer = { matches: true, listeners: new Set<EventListener>() }
const reducedMotion = { matches: false, listeners: new Set<EventListener>() }
let nextFrame = 0

function render(tilt = false) {
  const wrapper = mount(defineComponent({
    directives: { glassSpotlight: vGlassSpotlight },
    template: tilt
      ? '<section v-glass-spotlight.tilt><button>筛选</button></section>'
      : '<section v-glass-spotlight><button>筛选</button></section>',
  }))
  wrappers.push(wrapper)
  vi.spyOn(wrapper.element, 'getBoundingClientRect').mockReturnValue({
    x: 50, y: 20, left: 50, top: 20, right: 450, bottom: 150, width: 400, height: 130,
    toJSON: () => ({}),
  })
  Object.defineProperty(wrapper.element, 'clientLeft', { value: 1 })
  Object.defineProperty(wrapper.element, 'clientTop', { value: 1 })
  return wrapper
}

function point(element: Element, type: string, x = 100, y = 50, pointerType = 'mouse') {
  element.dispatchEvent(Object.assign(new Event(type), { clientX: x, clientY: y, pointerType }))
}

function flushFrame() {
  const callbacks = [...frames.values()]
  frames.clear()
  callbacks.forEach(callback => callback(0))
}

beforeEach(() => {
  vi.stubGlobal('matchMedia', (query: string) => {
    const state = query.includes('prefers-reduced-motion') ? reducedMotion : pointer
    return {
      get matches() { return state.matches },
      addEventListener: (_: string, callback: EventListener) => state.listeners.add(callback),
      removeEventListener: (_: string, callback: EventListener) => state.listeners.delete(callback),
    }
  })
  vi.stubGlobal('requestAnimationFrame', vi.fn((callback: FrameRequestCallback) => {
    frames.set(++nextFrame, callback)
    return nextFrame
  }))
  vi.stubGlobal('cancelAnimationFrame', vi.fn((id: number) => frames.delete(id)))
})

afterEach(() => {
  wrappers.splice(0).forEach(wrapper => wrapper.unmount())
  frames.clear()
  pointer.matches = true
  reducedMotion.matches = false
  pointer.listeners.clear()
  reducedMotion.listeners.clear()
  nextFrame = 0
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('玻璃卡片跟随光斑', () => {
  it('嵌入区域显式关闭时不添加光效或事件', () => {
    const wrapper = mount(defineComponent({
      directives: { glassSpotlight: vGlassSpotlight },
      template: '<section v-glass-spotlight="false" />',
    }))
    wrappers.push(wrapper)
    point(wrapper.element, 'pointerenter')
    expect(wrapper.classes()).not.toContain('erp-glass-spotlight')
    expect(requestAnimationFrame).not.toHaveBeenCalled()
    expect(pointer.listeners.size).toBe(0)
    expect(reducedMotion.listeners.size).toBe(0)
  })

  it('同一帧仅更新一次，使用最后一次指针位置且扣除已有边框', () => {
    const wrapper = render()
    const element = wrapper.element as HTMLElement
    point(element, 'pointerenter', 100, 50)
    point(element, 'pointermove', 150, 60)
    point(element, 'pointermove', 170, 70)
    expect(requestAnimationFrame).toHaveBeenCalledOnce()
    expect(element.style.getPropertyValue('--erp-spotlight-active')).toBe('')
    flushFrame()
    expect(element.style.getPropertyValue('--erp-spotlight-x')).toBe('119px')
    expect(element.style.getPropertyValue('--erp-spotlight-y')).toBe('49px')
    expect(element.style.getPropertyValue('--erp-spotlight-active')).toBe('1')
  })

  it('默认光斑不会添加倾斜状态', () => {
    const element = render().element as HTMLElement
    point(element, 'pointerenter', 450, 150)
    flushFrame()
    expect(element.style.getPropertyValue('--erp-tilt-x')).toBe('')
    expect(element.style.getPropertyValue('--erp-tilt-y')).toBe('')
    point(element, 'pointerleave')
    expect(element.style.getPropertyValue('--erp-tilt-x')).toBe('')
    expect(element.style.getPropertyValue('--erp-tilt-y')).toBe('')
  })

  it('显式开启倾斜后与光斑同帧跟随，中心归零且角落总倾角小于4度', () => {
    const element = render(true).element as HTMLElement
    point(element, 'pointerenter', 50, 20)
    point(element, 'pointermove', 450, 150)
    expect(frames.size).toBe(1)
    flushFrame()
    expect(element.style.getPropertyValue('--erp-spotlight-x')).toBe('399px')
    expect(element.style.getPropertyValue('--erp-tilt-x')).toBe('-2.5deg')
    expect(element.style.getPropertyValue('--erp-tilt-y')).toBe('2.5deg')
    const x = Number.parseFloat(element.style.getPropertyValue('--erp-tilt-x'))
    const y = Number.parseFloat(element.style.getPropertyValue('--erp-tilt-y'))
    expect(Math.hypot(x, y)).toBeLessThan(4)
    point(element, 'pointermove', 250, 85)
    flushFrame()
    expect(element.style.getPropertyValue('--erp-tilt-x')).toBe('0deg')
    expect(element.style.getPropertyValue('--erp-tilt-y')).toBe('0deg')
  })

  it('指针超出测量边界时限制倾斜角度', () => {
    const element = render(true).element as HTMLElement
    point(element, 'pointerenter', -500, -500)
    flushFrame()
    expect(element.style.getPropertyValue('--erp-tilt-x')).toBe('2.5deg')
    expect(element.style.getPropertyValue('--erp-tilt-y')).toBe('-2.5deg')
  })

  it('悬停期间使用稳定坐标，避免倾斜改变尺寸引起光斑和角度抖动', () => {
    const element = render(true).element as HTMLElement
    point(element, 'pointerenter', 450, 150)
    flushFrame()
    vi.mocked(element.getBoundingClientRect).mockReturnValue({
      x: 40, y: 10, left: 40, top: 10, right: 460, bottom: 160, width: 420, height: 150,
      toJSON: () => ({}),
    })
    point(element, 'pointermove', 250, 85)
    flushFrame()
    expect(element.style.getPropertyValue('--erp-spotlight-x')).toBe('199px')
    expect(element.style.getPropertyValue('--erp-spotlight-y')).toBe('64px')
    expect(element.style.getPropertyValue('--erp-tilt-x')).toBe('0deg')
    expect(element.style.getPropertyValue('--erp-tilt-y')).toBe('0deg')
  })

  it('重新进入复原中的卡片按未变形尺寸测量，并保留原有内联变换和过渡', () => {
    const element = render(true).element as HTMLElement
    element.style.setProperty('transform', 'translateZ(0)', 'important')
    element.style.setProperty('transition', 'transform 800ms ease', 'important')
    vi.mocked(element.getBoundingClientRect).mockImplementation(() => {
      const untransformed = element.style.transform === 'none' && element.style.transition === 'none'
      return untransformed
        ? new DOMRect(50, 20, 400, 130)
        : new DOMRect(40, 10, 420, 150)
    })
    point(element, 'pointerenter', 450, 150)
    flushFrame()
    point(element, 'pointerleave')
    point(element, 'pointerenter', 50, 20)
    flushFrame()
    expect(element.style.getPropertyValue('--erp-spotlight-x')).toBe('-1px')
    expect(element.style.getPropertyValue('--erp-tilt-x')).toBe('2.5deg')
    expect(element.style.getPropertyValue('--erp-tilt-y')).toBe('-2.5deg')
    expect(element.style.transform).toBe('translateZ(0)')
    expect(element.style.transition).toBe('transform 800ms ease')
    expect(element.style.getPropertyPriority('transform')).toBe('important')
    expect(element.style.getPropertyPriority('transition')).toBe('important')
  })

  it.each(['pointerleave', 'pointercancel', 'blur', 'scroll', 'resize'])('%s 取消倾斜帧并复原', type => {
    const element = render(true).element as HTMLElement
    point(element, 'pointerenter', 450, 150)
    flushFrame()
    point(element, 'pointermove', 50, 20)
    if (type.startsWith('pointer')) point(element, type)
    else window.dispatchEvent(new Event(type))
    expect(frames.size).toBe(0)
    expect(element.style.getPropertyValue('--erp-tilt-x')).toBe('0deg')
    expect(element.style.getPropertyValue('--erp-tilt-y')).toBe('0deg')
    expect(element.style.getPropertyValue('--erp-spotlight-active')).toBe('0')
  })

  it('滚动后重新测量卡片位置', () => {
    const element = render(true).element as HTMLElement
    point(element, 'pointerenter', 450, 150)
    flushFrame()
    window.dispatchEvent(new Event('scroll'))
    vi.mocked(element.getBoundingClientRect).mockReturnValue({
      x: 50, y: 0, left: 50, top: 0, right: 450, bottom: 130, width: 400, height: 130,
      toJSON: () => ({}),
    })
    point(element, 'pointermove', 250, 65)
    flushFrame()
    expect(element.style.getPropertyValue('--erp-spotlight-y')).toBe('64px')
    expect(element.style.getPropertyValue('--erp-tilt-x')).toBe('0deg')
    expect(element.style.getPropertyValue('--erp-tilt-y')).toBe('0deg')
  })

  it('没有可见尺寸时不会产生无效倾斜角度', () => {
    const element = render(true).element as HTMLElement
    vi.mocked(element.getBoundingClientRect).mockReturnValue(new DOMRect())
    point(element, 'pointerenter')
    flushFrame()
    expect(element.style.getPropertyValue('--erp-tilt-x')).toBe('0deg')
    expect(element.style.getPropertyValue('--erp-tilt-y')).toBe('0deg')
    expect(element.style.getPropertyValue('--erp-spotlight-active')).toBe('0')
  })

  it.each(['coarse', 'reduced-motion', 'touch'])('%s 清除当前倾斜并禁用继续跟随', mode => {
    const element = render(true).element as HTMLElement
    point(element, 'pointerenter', 450, 150)
    flushFrame()
    if (mode === 'coarse') {
      pointer.matches = false
      pointer.listeners.forEach(listener => listener(new Event('change')))
    }
    if (mode === 'reduced-motion') {
      reducedMotion.matches = true
      reducedMotion.listeners.forEach(listener => listener(new Event('change')))
    }
    point(element, 'pointermove', 50, 20, mode === 'touch' ? 'touch' : 'mouse')
    expect(frames.size).toBe(0)
    expect(element.style.getPropertyValue('--erp-tilt-x')).toBe('0deg')
    expect(element.style.getPropertyValue('--erp-tilt-y')).toBe('0deg')
    expect(element.style.getPropertyValue('--erp-spotlight-active')).toBe('0')
  })

  it.each(['pointerleave', 'pointercancel'])('%s 立即取消待更新帧并隐藏光斑', type => {
    const element = render().element as HTMLElement
    point(element, 'pointerenter')
    flushFrame()
    point(element, 'pointermove')
    point(element, type)
    expect(frames.size).toBe(0)
    expect(element.style.getPropertyValue('--erp-spotlight-active')).toBe('0')
  })

  it.each(['coarse', 'reduced-motion', 'touch'])('%s 不运行跟随效果', mode => {
    if (mode === 'coarse') pointer.matches = false
    if (mode === 'reduced-motion') reducedMotion.matches = true
    const element = render().element as HTMLElement
    point(element, 'pointerenter', 100, 50, mode === 'touch' ? 'touch' : 'mouse')
    expect(requestAnimationFrame).not.toHaveBeenCalled()
    expect(element.style.getPropertyValue('--erp-spotlight-active')).toBe('0')
  })

  it('系统开启减少动画时取消正在等待的帧，偏好恢复后可重新跟随', () => {
    const element = render().element as HTMLElement
    point(element, 'pointerenter')
    reducedMotion.matches = true
    reducedMotion.listeners.forEach(listener => listener(new Event('change')))
    expect(frames.size).toBe(0)
    expect(element.style.getPropertyValue('--erp-spotlight-active')).toBe('0')
    reducedMotion.matches = false
    point(element, 'pointermove')
    flushFrame()
    expect(element.style.getPropertyValue('--erp-spotlight-active')).toBe('1')
  })

  it.each([false, true])('卸载清理帧、媒体事件、指针事件与局部样式（倾斜：%s）', tilt => {
    const wrapper = render(tilt)
    const element = wrapper.element as HTMLElement
    point(element, 'pointerenter')
    flushFrame()
    point(element, 'pointermove')
    wrapper.unmount()
    expect(frames.size).toBe(0)
    expect(pointer.listeners.size).toBe(0)
    expect(reducedMotion.listeners.size).toBe(0)
    expect(element.classList.contains('erp-glass-spotlight')).toBe(false)
    expect(element.style.cssText).toBe('')
    point(element, 'pointermove')
    expect(frames.size).toBe(0)
    window.dispatchEvent(new Event('scroll'))
    window.dispatchEvent(new Event('resize'))
    window.dispatchEvent(new Event('blur'))
    expect(element.style.cssText).toBe('')
  })
})
