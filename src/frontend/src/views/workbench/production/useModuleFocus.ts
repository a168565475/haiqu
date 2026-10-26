import { nextTick, onBeforeUnmount, onMounted, ref, type Ref } from 'vue'

export type OverviewModuleKey = 'delivery' | 'production' | 'outsourcing' | 'output' | 'todo'

export function useModuleFocus(root: Ref<HTMLElement | undefined>) {
  const activeModule = ref<OverviewModuleKey | null>(null)
  const isAnimating = ref(false)
  let animations: Animation[] = []
  let generation = 0
  let disposed = false
  let resizeObserver: ResizeObserver | undefined
  let rootRect: DOMRect | undefined
  let returnModule: OverviewModuleKey | null = null

  function cancelAnimations() {
    animations.forEach(animation => animation.cancel())
    animations = []
    isAnimating.value = false
  }

  function focusCurrentModule() {
    const key = activeModule.value ?? returnModule
    if (!key) return
    root.value?.querySelector<HTMLButtonElement>(
      `[data-module="${key}"] [${activeModule.value === null ? 'data-module-open' : 'data-module-close'}]`,
    )?.focus({ preventScroll: true })
  }

  async function transitionTo(key: OverviewModuleKey | null) {
    if (disposed || key === activeModule.value) return
    const previousKey = activeModule.value
    const cards = Array.from(root.value?.querySelectorAll<HTMLElement>('.po-module[data-module]') ?? [])
    // 先读取动画中的可见位置，再取消旧动画，连续切换才不会跳回旧起点。
    const before = cards.map(card => card.getBoundingClientRect())
    const currentGeneration = ++generation
    cancelAnimations()
    returnModule = key ?? previousKey
    activeModule.value = key
    await nextTick()
    if (disposed || currentGeneration !== generation) return
    rootRect = root.value?.getBoundingClientRect()

    const reducedMotion = typeof window.matchMedia === 'function'
      && window.matchMedia('(prefers-reduced-motion: reduce)').matches
    if (!reducedMotion) {
      cards.forEach((card, index) => {
        if (typeof card.animate !== 'function') return
        const first = before[index]!
        const last = card.getBoundingClientRect()
        if (!first.width || !first.height || !last.width || !last.height) return
        const animation = card.animate([
          {
            transformOrigin: '0 0',
            transform: `translate(${first.left - last.left}px, ${first.top - last.top}px) scale(${first.width / last.width}, ${first.height / last.height})`,
          },
          { transformOrigin: '0 0', transform: 'none' },
        ], { duration: key === null ? 350 : 460, easing: 'cubic-bezier(0.22, 1, 0.36, 1)' })
        animations.push(animation)
        // 布局切换后文字已经属于新尺寸，稍后淡入，避免被旧大卡片比例放大。
        Array.from(card.children).forEach(child => {
          if (!(child instanceof HTMLElement) || child.hidden || child.hasAttribute('data-module-open') || typeof child.animate !== 'function') return
          const style = window.getComputedStyle(child)
          if (style.display === 'none' || style.visibility === 'hidden') return
          animations.push(child.animate([{ opacity: 0 }, { opacity: 1 }], {
            delay: 140, duration: 180, fill: 'backwards', easing: 'ease-out',
          }))
        })
      })
    }
    isAnimating.value = animations.length > 0
    if (animations.length) {
      try {
        await Promise.all(animations.map(animation => animation.finished.catch((error: unknown) => {
          // cancel() 会按 WAAPI 约定拒绝 finished；其他动画错误仍然上抛。
          if (!(error instanceof DOMException && error.name === 'AbortError')) throw error
        })))
      } finally {
        if (currentGeneration === generation) cancelAnimations()
      }
    }
    if (disposed || currentGeneration !== generation) return
    animations = []
    isAnimating.value = false
    focusCurrentModule()
  }

  function onKeydown(event: KeyboardEvent) {
    if (event.defaultPrevented || !activeModule.value) return
    if (event.key === 'Escape') {
      event.preventDefault()
      void transitionTo(null)
      return
    }
    if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return
    const target = event.target instanceof Element ? event.target.closest<HTMLButtonElement>('button[data-module-open]') : null
    const buttons = Array.from(root.value?.querySelectorAll<HTMLButtonElement>('button[data-module-open]') ?? [])
    const index = target ? buttons.indexOf(target) : -1
    if (index < 0) return
    event.preventDefault()
    const offset = event.key === 'ArrowRight' ? 1 : -1
    buttons[(index + offset + buttons.length) % buttons.length]?.focus({ preventScroll: true })
  }

  onMounted(() => {
    if (!root.value || typeof ResizeObserver === 'undefined') return
    rootRect = root.value.getBoundingClientRect()
    resizeObserver = new ResizeObserver(() => {
      const rect = root.value?.getBoundingClientRect()
      if (!rect || (rect.width === rootRect?.width && rect.height === rootRect.height)) return
      rootRect = rect
      // 容器尺寸改变后，旧坐标已经失效，立即交还 CSS 布局。
      ++generation
      cancelAnimations()
      focusCurrentModule()
    })
    resizeObserver.observe(root.value)
  })

  onBeforeUnmount(() => {
    disposed = true
    ++generation
    cancelAnimations()
    resizeObserver?.disconnect()
  })

  return { activeModule, transitionTo, onKeydown, isAnimating }
}
