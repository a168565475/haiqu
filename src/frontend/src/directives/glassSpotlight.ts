import type { ObjectDirective } from 'vue'

const cleanups = new WeakMap<HTMLElement, () => void>()

export const vGlassSpotlight: ObjectDirective<HTMLElement> = {
  mounted(element, binding) {
    if (binding.value === false) return
    const view = element.ownerDocument.defaultView
    if (!view?.matchMedia) return

    const pointer = view.matchMedia('(hover: hover) and (pointer: fine)')
    const reducedMotion = view.matchMedia('(prefers-reduced-motion: reduce)')
    const tilt = binding.modifiers.tilt === true
    let frame: number | undefined
    let point: { x: number; y: number } | undefined
    let tiltBounds: DOMRect | undefined
    element.classList.add('erp-glass-spotlight')

    const reset = () => {
      if (frame !== undefined) view.cancelAnimationFrame(frame)
      frame = undefined
      point = undefined
      element.style.setProperty('--erp-spotlight-active', '0')
      if (tilt) {
        tiltBounds = undefined
        element.style.setProperty('--erp-tilt-x', '0deg')
        element.style.setProperty('--erp-tilt-y', '0deg')
      }
    }

    const move = (event: PointerEvent) => {
      if (!pointer.matches || reducedMotion.matches || event.pointerType === 'touch') {
        reset()
        return
      }
      point = { x: event.clientX, y: event.clientY }
      if (frame !== undefined) return
      frame = view.requestAnimationFrame(() => {
        frame = undefined
        if (!point) return
        // 每次进入只测量一次未变形尺寸，后续帧复用，避免复原动画或倾斜导致坐标漂移。
        if (tilt && !tiltBounds) {
          const transform = element.style.getPropertyValue('transform')
          const transition = element.style.getPropertyValue('transition')
          const transformPriority = element.style.getPropertyPriority('transform')
          const transitionPriority = element.style.getPropertyPriority('transition')
          element.style.setProperty('transition', 'none', 'important')
          element.style.setProperty('transform', 'none', 'important')
          tiltBounds = element.getBoundingClientRect()
          element.style.setProperty('transform', transform, transformPriority)
          element.style.setProperty('transition', transition, transitionPriority)
        }
        const bounds = tiltBounds ?? element.getBoundingClientRect()
        if (tilt) {
          if (!bounds.width || !bounds.height) {
            reset()
            return
          }
          const x = Math.max(-1, Math.min(1, (point.x - bounds.left) / bounds.width * 2 - 1))
          const y = Math.max(-1, Math.min(1, (point.y - bounds.top) / bounds.height * 2 - 1))
          // 每轴最多 2.5 度，组合旋转的总倾角仍低于 4 度。
          element.style.setProperty('--erp-tilt-x', `${-y * 2.5}deg`)
          element.style.setProperty('--erp-tilt-y', `${x * 2.5}deg`)
        }
        // 伪元素以卡片内边缘为原点，扣除现有边框，避免叠加或移动边界。
        element.style.setProperty('--erp-spotlight-x', `${point.x - bounds.left - element.clientLeft}px`)
        element.style.setProperty('--erp-spotlight-y', `${point.y - bounds.top - element.clientTop}px`)
        element.style.setProperty('--erp-spotlight-active', '1')
      })
    }

    element.addEventListener('pointerenter', move)
    element.addEventListener('pointermove', move, { passive: true })
    element.addEventListener('pointerleave', reset)
    element.addEventListener('pointercancel', reset)
    pointer.addEventListener('change', reset)
    reducedMotion.addEventListener('change', reset)
    view.addEventListener('blur', reset)
    if (tilt) {
      view.addEventListener('scroll', reset, { capture: true, passive: true })
      view.addEventListener('resize', reset)
    }

    cleanups.set(element, () => {
      reset()
      element.removeEventListener('pointerenter', move)
      element.removeEventListener('pointermove', move)
      element.removeEventListener('pointerleave', reset)
      element.removeEventListener('pointercancel', reset)
      pointer.removeEventListener('change', reset)
      reducedMotion.removeEventListener('change', reset)
      view.removeEventListener('blur', reset)
      if (tilt) {
        view.removeEventListener('scroll', reset, true)
        view.removeEventListener('resize', reset)
        element.style.removeProperty('--erp-tilt-x')
        element.style.removeProperty('--erp-tilt-y')
      }
      element.classList.remove('erp-glass-spotlight')
      for (const name of ['active', 'x', 'y']) element.style.removeProperty(`--erp-spotlight-${name}`)
    })
  },
  beforeUnmount(element) {
    cleanups.get(element)?.()
    cleanups.delete(element)
  },
}
