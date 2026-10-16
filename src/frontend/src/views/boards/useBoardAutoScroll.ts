import { onBeforeUnmount, onMounted, ref, type Ref } from 'vue'

export function useBoardAutoScroll(container: Ref<HTMLElement | undefined>, content: Ref<HTMLElement | undefined>, headerHeight = 0) {
  const hovered = ref(false)
  const focused = ref(false)
  const looping = ref(false)
  let frame = 0
  let previousTime: number | undefined
  let height = 0
  let offset = 0
  let appliedOffset = 0
  let observer: ResizeObserver | undefined
  let media: MediaQueryList | undefined

  function measure() {
    height = content.value?.offsetHeight ?? 0
    const available = (container.value?.clientHeight ?? 0) - headerHeight
    looping.value = !media?.matches && available > 0 && height > available + 1
    if (!looping.value && container.value) container.value.scrollTop = offset = appliedOffset = 0
  }
  function reset() {
    offset = appliedOffset = 0
    previousTime = undefined
    if (container.value) container.value.scrollTop = 0
    measure()
  }
  function tick(time: number) {
    const elapsed = previousTime === undefined ? 0 : Math.min(time - previousTime, 100)
    previousTime = time
    const element = container.value
    if (element && looping.value && !hovered.value && !focused.value && !document.hidden) {
      // 保留小数，避免浏览器将每帧 scrollTop 取整后改变实际速度；手动滚动后从当前位置继续。
      if (element.scrollTop !== appliedOffset) offset = element.scrollTop
      offset = (offset + elapsed * 40 / 1000) % height
      element.scrollTop = offset
      appliedOffset = element.scrollTop
    }
    frame = requestAnimationFrame(tick)
  }
  function visibilityChanged() { previousTime = undefined }
  onMounted(() => {
    media = window.matchMedia?.('(prefers-reduced-motion: reduce)')
    media?.addEventListener('change', reset)
    if (typeof ResizeObserver !== 'undefined') {
      observer = new ResizeObserver(measure)
      if (container.value) observer.observe(container.value)
      if (content.value) observer.observe(content.value)
    }
    document.addEventListener('visibilitychange', visibilityChanged)
    measure()
    frame = requestAnimationFrame(tick)
  })
  onBeforeUnmount(() => {
    cancelAnimationFrame(frame)
    observer?.disconnect()
    media?.removeEventListener('change', reset)
    document.removeEventListener('visibilitychange', visibilityChanged)
  })
  return { hovered, focused, looping, reset }
}
