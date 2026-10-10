<script setup lang="ts">
const minimumWidth = 320
const keyboardStep = 24

function widthLimits() {
  const maximum = Math.max(160, window.innerWidth - 16)
  return { minimum: Math.min(minimumWidth, maximum), maximum }
}

function resizedWidth(drawer: HTMLElement, clientX: number): number {
  const rightEdge = drawer.getBoundingClientRect().right
  const limits = widthLimits()
  return Math.min(limits.maximum, Math.max(limits.minimum, rightEdge - clientX))
}

function applyWidth(drawer: HTMLElement, width: number) {
  drawer.style.width = `${width}px`
  drawer.style.maxWidth = 'calc(100vw - 16px)'
}

function startResize(event: PointerEvent) {
  if (event.button !== 0) return
  const handle = event.currentTarget as HTMLButtonElement | null
  const drawer = handle?.closest<HTMLElement>('.el-drawer')
  if (!handle || !drawer) return

  event.preventDefault()
  handle.setPointerCapture(event.pointerId)

  const move = (moveEvent: PointerEvent) => {
    applyWidth(drawer, resizedWidth(drawer, moveEvent.clientX))
  }
  const stop = () => {
    window.removeEventListener('pointermove', move)
    window.removeEventListener('pointerup', stop)
    window.removeEventListener('pointercancel', stop)
    if (handle.hasPointerCapture(event.pointerId)) handle.releasePointerCapture(event.pointerId)
  }

  window.addEventListener('pointermove', move)
  window.addEventListener('pointerup', stop)
  window.addEventListener('pointercancel', stop)
}

function resizeWithKeyboard(event: KeyboardEvent) {
  if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return
  const handle = event.currentTarget as HTMLButtonElement | null
  const drawer = handle?.closest<HTMLElement>('.el-drawer')
  if (!drawer) return

  event.preventDefault()
  const direction = event.key === 'ArrowLeft' ? 1 : -1
  const limits = widthLimits()
  const width = Math.min(limits.maximum, Math.max(limits.minimum, drawer.getBoundingClientRect().width + direction * keyboardStep))
  applyWidth(drawer, width)
}
</script>

<template>
  <button
    type="button"
    class="drawer-resize-handle"
    aria-label="调整窗口宽度；左右方向键也可调整"
    title="拖动调整窗口宽度"
    @pointerdown="startResize"
    @keydown="resizeWithKeyboard"
  >
    <span aria-hidden="true" />
  </button>
</template>

<style lang="scss" scoped>
.drawer-resize-handle{position:absolute;z-index:3;top:0;bottom:0;left:0;width:10px;padding:0;border:0;background:transparent;cursor:ew-resize;touch-action:none}.drawer-resize-handle span{position:absolute;top:50%;left:3px;width:3px;height:48px;border-radius:2px;background:#c9cdd4;opacity:0;transform:translateY(-50%);transition:opacity .15s,background-color .15s}.drawer-resize-handle:hover span,.drawer-resize-handle:focus-visible span{background:#3898ec;opacity:1}.drawer-resize-handle:focus-visible{outline:2px solid #3898ec;outline-offset:-2px}
</style>
