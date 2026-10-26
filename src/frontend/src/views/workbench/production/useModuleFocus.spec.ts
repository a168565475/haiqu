import { mount } from '@vue/test-utils'
import { defineComponent, nextTick, ref } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useModuleFocus, type OverviewModuleKey } from './useModuleFocus'

const keys: OverviewModuleKey[] = ['delivery', 'production', 'outsourcing', 'output', 'todo']
const wrappers: ReturnType<typeof mount>[] = []

function renderPage() {
  let state!: ReturnType<typeof useModuleFocus>
  const wrapper = mount(defineComponent({
    setup() {
      const root = ref<HTMLElement>()
      state = useModuleFocus(root)
      return { root, keys, ...state }
    },
    template: `<section ref="root" :data-active="activeModule" @keydown="onKeydown">
      <article v-for="key in keys" :key="key" class="po-module" :data-module="key">
        <button v-if="activeModule !== key" data-module-open @click="transitionTo(key)">{{ key }}</button>
        <header><span>{{ key }}</span><button v-if="activeModule === key" data-module-close @click="transitionTo(null)">收起</button></header>
        <div class="content">模块内容</div>
        <div hidden>隐藏内容</div>
      </article>
    </section>`,
  }), { attachTo: document.body })
  wrappers.push(wrapper)
  return { wrapper, state }
}

function mockAnimationLayout(wrapper: ReturnType<typeof mount>) {
  const animations: { target: HTMLElement; frames: Keyframe[]; options: KeyframeAnimationOptions; cancelled: boolean; finish: () => void; fail: (reason: unknown) => void }[] = []
  const visualRects = new Map<string, DOMRect>()
  for (const [index, card] of wrapper.findAll('.po-module').entries()) {
    const element = card.element as HTMLElement
    vi.spyOn(element, 'getBoundingClientRect').mockImplementation(() => {
      const visual = visualRects.get(element.dataset.module!)
      if (visual) return visual
      const active = wrapper.attributes('data-active')
      if (!active) return new DOMRect(index * 210, 0, 200, 100)
      if (element.dataset.module === active) return new DOMRect(0, 0, 600, 400)
      return new DOMRect(index * 110, 450, 100, 70)
    })
    for (const target of [element, ...Array.from(element.children) as HTMLElement[]]) {
      target.animate = (frames, options) => {
        let finish!: () => void
        let reject!: (reason: unknown) => void
        const finished = new Promise<void>((resolve, rejectPromise) => { finish = resolve; reject = rejectPromise })
        const record = { target, frames: frames as Keyframe[], options: options as KeyframeAnimationOptions, cancelled: false, finish, fail: reject }
        animations.push(record)
        return {
          finished,
          cancel() { record.cancelled = true; reject(new DOMException('Cancelled', 'AbortError')) },
        } as unknown as Animation
      }
    }
  }
  return { animations, visualRects }
}

afterEach(() => {
  wrappers.splice(0).forEach(wrapper => wrapper.unmount())
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  document.body.innerHTML = ''
})

describe('生产总览模块聚焦', () => {
  it('无动画 API 时保留卡片 DOM，切换后收回当前模块并返回对应按钮', async () => {
    const { wrapper, state } = renderPage()
    const cards = wrapper.findAll('.po-module').map(card => card.element)
    await state.transitionTo('delivery')
    expect(document.activeElement).toBe(wrapper.find('[data-module="delivery"] [data-module-close]').element)
    await state.transitionTo('outsourcing')
    expect(state.activeModule.value).toBe('outsourcing')
    expect(document.activeElement).toBe(wrapper.find('[data-module="outsourcing"] [data-module-close]').element)
    await state.transitionTo(null)
    expect(state.activeModule.value).toBeNull()
    expect(state.isAnimating.value).toBe(false)
    expect(document.activeElement).toBe(wrapper.find('[data-module="outsourcing"] [data-module-open]').element)
    expect(wrapper.findAll('.po-module').map(card => card.element)).toEqual(cards)
  })

  it('Escape 收起详情，已被内部控件处理的按键不收起', async () => {
    const { wrapper, state } = renderPage()
    await state.transitionTo('production')
    const consumed = new KeyboardEvent('keydown', { key: 'Escape', cancelable: true })
    consumed.preventDefault()
    state.onKeydown(consumed)
    expect(state.activeModule.value).toBe('production')
    await wrapper.trigger('keydown', { key: 'Enter' })
    expect(state.activeModule.value).toBe('production')
    const escape = new KeyboardEvent('keydown', { key: 'Escape', cancelable: true })
    state.onKeydown(escape)
    await nextTick()
    expect(state.activeModule.value).toBeNull()
    expect(escape.defaultPrevented).toBe(true)
    expect(document.activeElement).toBe(wrapper.find('[data-module="production"] [data-module-open]').element)
  })

  it('减少动态时直接切换布局和焦点，不产生位移动画', async () => {
    vi.stubGlobal('matchMedia', () => ({ matches: true }))
    const { wrapper, state } = renderPage()
    const { animations } = mockAnimationLayout(wrapper)
    await state.transitionTo('output')
    expect(state.activeModule.value).toBe('output')
    expect(state.isAnimating.value).toBe(false)
    expect(animations).toHaveLength(0)
    expect(document.activeElement).toBe(wrapper.find('[data-module="output"] [data-module-close]').element)
  })

  it('底栏左右键循环移动入口焦点，不触发切换也不影响详情内按键', async () => {
    const { wrapper, state } = renderPage()
    await state.transitionTo('delivery')
    const first = wrapper.find('[data-module="production"] [data-module-open]')
    const last = wrapper.find('[data-module="todo"] [data-module-open]')
    ;(first.element as HTMLButtonElement).focus()
    await first.trigger('keydown', { key: 'ArrowLeft' })
    expect(document.activeElement).toBe(last.element)
    await last.trigger('keydown', { key: 'ArrowRight' })
    expect(document.activeElement).toBe(first.element)
    await first.trigger('keydown', { key: 'ArrowRight' })
    expect(document.activeElement).toBe(wrapper.find('[data-module="outsourcing"] [data-module-open]').element)
    expect(state.activeModule.value).toBe('delivery')
    const close = wrapper.find('[data-module-close]')
    ;(close.element as HTMLButtonElement).focus()
    await close.trigger('keydown', { key: 'ArrowRight' })
    expect(document.activeElement).toBe(close.element)
  })

  it('展开时内容延迟淡入，透明入口和隐藏元素不参与淡入', async () => {
    const { wrapper, state } = renderPage()
    const { animations } = mockAnimationLayout(wrapper)
    const transition = state.transitionTo('delivery')
    await nextTick()
    const fades = animations.filter(animation => animation.frames[0]!.opacity === 0)
    expect(fades).toHaveLength(10)
    expect(fades.every(animation => animation.options.delay === 140 && animation.options.duration === 180 && animation.options.fill === 'backwards')).toBe(true)
    expect(fades.every(animation => !animation.target.hasAttribute('data-module-open') && !animation.target.hidden)).toBe(true)
    expect(fades.every(animation => animation.frames[1]!.opacity === 1)).toBe(true)
    animations.forEach(animation => animation.finish())
    await transition
    expect(state.isAnimating.value).toBe(false)
  })

  it('以原卡片矩形展开，动画结束后才把焦点移入详情', async () => {
    const { wrapper, state } = renderPage()
    const { animations } = mockAnimationLayout(wrapper)
    const transition = state.transitionTo('delivery')
    await nextTick()
    expect(state.isAnimating.value).toBe(true)
    expect(animations.filter(animation => animation.frames[0]!.transform)).toHaveLength(5)
    expect(animations[0]!.frames[0]!.transform).toBe('translate(0px, 0px) scale(0.3333333333333333, 0.25)')
    expect(animations[0]!.options.duration).toBe(460)
    animations.forEach(animation => animation.finish())
    await transition
    expect(state.isAnimating.value).toBe(false)
    expect(document.activeElement).toBe(wrapper.find('[data-module="delivery"] [data-module-close]').element)
    const firstBatch = animations.length
    const close = state.transitionTo(null)
    await nextTick()
    expect(animations[firstBatch]!.options.duration).toBe(350)
    animations.slice(firstBatch).forEach(animation => animation.finish())
    await close
    expect(document.activeElement).toBe(wrapper.find('[data-module="delivery"] [data-module-open]').element)
  })

  it('动画中切换从当前可见位置接续，旧动画不能夺回焦点', async () => {
    const { wrapper, state } = renderPage()
    const { animations, visualRects } = mockAnimationLayout(wrapper)
    const opening = state.transitionTo('delivery')
    await nextTick()
    const firstBatch = animations.length
    visualRects.set('delivery', new DOMRect(40, 20, 400, 250))
    const switching = state.transitionTo('outsourcing')
    visualRects.clear()
    await nextTick()
    await opening
    expect(animations.slice(0, firstBatch).every(animation => animation.cancelled)).toBe(true)
    expect(animations[firstBatch]!.frames[0]!.transform).toBe('translate(40px, -430px) scale(4, 3.5714285714285716)')
    expect(state.activeModule.value).toBe('outsourcing')
    expect(state.isAnimating.value).toBe(true)
    expect(document.activeElement).not.toBe(wrapper.find('[data-module="outsourcing"] [data-module-close]').element)
    animations.slice(firstBatch).forEach(animation => animation.finish())
    await switching
    expect(document.activeElement).toBe(wrapper.find('[data-module="outsourcing"] [data-module-close]').element)
    expect(state.isAnimating.value).toBe(false)
  })

  it('同一渲染周期连续切换只执行最后一次布局动画', async () => {
    const { wrapper, state } = renderPage()
    const { animations } = mockAnimationLayout(wrapper)
    const first = state.transitionTo('delivery')
    const last = state.transitionTo('todo')
    await nextTick()
    expect(animations.filter(animation => animation.frames[0]!.transform)).toHaveLength(5)
    animations.forEach(animation => animation.finish())
    await Promise.all([first, last])
    expect(state.activeModule.value).toBe('todo')
    expect(document.activeElement).toBe(wrapper.find('[data-module="todo"] [data-module-close]').element)
  })

  it('非取消错误继续上抛，同时释放动画中的状态', async () => {
    const { wrapper, state } = renderPage()
    const { animations } = mockAnimationLayout(wrapper)
    const transition = state.transitionTo('delivery')
    const rejected = expect(transition).rejects.toThrow('Animation failed')
    await nextTick()
    animations[0]!.fail(new Error('Animation failed'))
    await rejected
    expect(state.isAnimating.value).toBe(false)
    expect(animations.every(animation => animation.cancelled)).toBe(true)
  })

  it('容器尺寸变化取消旧坐标动画，卸载释放观察器和动画', async () => {
    let resize!: ResizeObserverCallback
    const disconnect = vi.fn()
    vi.stubGlobal('ResizeObserver', class {
      constructor(callback: ResizeObserverCallback) { resize = callback }
      observe() {}
      disconnect = disconnect
    })
    const { wrapper, state } = renderPage()
    const { animations } = mockAnimationLayout(wrapper)
    const transition = state.transitionTo('delivery')
    await nextTick()
    vi.spyOn(wrapper.element, 'getBoundingClientRect').mockReturnValue(new DOMRect(0, 0, 900, 500))
    resize([{ contentRect: new DOMRect(0, 0, 900, 500) } as ResizeObserverEntry], {} as ResizeObserver)
    await transition
    expect(state.isAnimating.value).toBe(false)
    expect(animations.every(animation => animation.cancelled)).toBe(true)
    expect(state.activeModule.value).toBe('delivery')
    expect(document.activeElement).toBe(wrapper.find('[data-module="delivery"] [data-module-close]').element)
    const switching = state.transitionTo('output')
    await nextTick()
    wrapper.unmount()
    await switching
    expect(animations.every(animation => animation.cancelled)).toBe(true)
    expect(disconnect).toHaveBeenCalledOnce()
  })
})
