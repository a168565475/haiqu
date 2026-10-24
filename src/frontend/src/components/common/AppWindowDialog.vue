<script lang="ts">
let bodyLockCount = 0
let bodyOverflowBeforeFirstLock = ''
</script>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, useAttrs, useSlots, watch } from 'vue'
import { Close, FullScreen, Minus, Rank } from '@element-plus/icons-vue'
import { ElIcon, useZIndex } from 'element-plus'

defineOptions({ inheritAttrs: false })

type WindowState = 'normal' | 'maximized' | 'minimized'
type WindowRect = { x: number; y: number; width: number; height: number }

const props = withDefaults(defineProps<{
  modelValue: boolean
  title: string
  width?: number | string
  height?: number | string
  autoMaxHeightRatio?: number
  fullscreen?: boolean
  edgeToEdge?: boolean
  withHeader?: boolean
  minWidth?: number
  minHeight?: number
  centerOnResize?: boolean
  closeOnClickModal?: boolean
  closeOnPressEscape?: boolean
  showClose?: boolean
  minimizable?: boolean
  destroyOnClose?: boolean
  lockScroll?: boolean
  modalClass?: string
  beforeClose?: (done: () => void) => void
}>(), {
  width: 680,
  height: 'auto',
  autoMaxHeightRatio: 0.8,
  fullscreen: false,
  edgeToEdge: false,
  withHeader: true,
  minWidth: 360,
  minHeight: 180,
  centerOnResize: false,
  closeOnClickModal: true,
  closeOnPressEscape: true,
  showClose: true,
  minimizable: true,
  destroyOnClose: false,
  lockScroll: true,
  modalClass: '',
  beforeClose: undefined,
})

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  open: []
  opened: []
  close: []
  closed: []
}>()

const attrs = useAttrs()
const slots = useSlots()
const { nextZIndex } = useZIndex()
const rendered = ref(props.modelValue)
const windowRef = ref<HTMLElement | null>(null)
const state = ref<WindowState>('normal')
const rect = ref<WindowRect | null>(null)
const restoreRect = ref<WindowRect | null>(null)
const stateBeforeMinimize = ref<Exclude<WindowState, 'minimized'>>('normal')
const previouslyFocused = ref<HTMLElement | null>(null)
const overlayZIndex = ref(nextZIndex())
const viewportSize = ref({ width: window.innerWidth, height: window.innerHeight })
let bodyLocked = false
let interaction: null | {
  type: 'drag' | 'resize'
  startX: number
  startY: number
  rect: WindowRect
} = null
let autoContentObserver: ResizeObserver | null = null
let autoRootObserver: MutationObserver | null = null
let autoFitFrame: number | null = null
let manuallyAdjusted = false
let requestedHeight = 0

const forwardedAttrs = computed(() => {
  const ignoredLegacyAttrs = new Set([
    'class', 'style', 'alignCenter', 'align-center', 'appendToBody', 'append-to-body',
    'draggable', 'overflow', 'top',
  ])
  return Object.fromEntries(Object.entries(attrs).filter(([key]) => !ignoredLegacyAttrs.has(key)))
})

function cssSize(value: number | string): string {
  return typeof value === 'number' ? `${value}px` : value
}

function pixelFallback(value: number | string, fallback: number): number {
  if (typeof value === 'number') return value
  const parsed = Number.parseFloat(value)
  return Number.isFinite(parsed) && value.trim().endsWith('px') ? parsed : fallback
}

function viewportBounds() {
  return { ...viewportSize.value, padding: 16 }
}

function clampRect(value: WindowRect): WindowRect {
  const viewport = viewportBounds()
  const maxWidth = Math.max(props.minWidth, viewport.width - viewport.padding * 2)
  const maxHeight = Math.max(0, Math.min(viewport.height - viewport.padding * 2, manuallyAdjusted ? Infinity : viewport.height * props.autoMaxHeightRatio))
  const width = Math.min(Math.max(value.width, props.minWidth), maxWidth)
  const height = Math.min(Math.max(value.height, props.minHeight), maxHeight)
  return {
    x: Math.min(Math.max(value.x, viewport.padding), Math.max(viewport.padding, viewport.width - width - viewport.padding)),
    y: Math.min(Math.max(value.y, viewport.padding), Math.max(viewport.padding, viewport.height - height - viewport.padding)),
    width,
    height,
  }
}

function naturalContentHeight(element: HTMLElement): number {
  const body = element.querySelector<HTMLElement>('.app-window-dialog__body')
  const bodyStyle = body ? window.getComputedStyle(body) : null
  const paddingTop = Number.parseFloat(bodyStyle?.paddingTop || '0') || 0
  const paddingBottom = Number.parseFloat(bodyStyle?.paddingBottom || '0') || 0
  const bodyTop = body?.getBoundingClientRect().top || 0
  const contentBottom = body ? Array.from(body.children).reduce((bottom, child) => {
    const childElement = child as HTMLElement
    if (!childElement.getClientRects().length) return bottom
    const marginBottom = Number.parseFloat(window.getComputedStyle(childElement).marginBottom) || 0
    return Math.max(bottom, childElement.getBoundingClientRect().bottom - bodyTop + (body?.scrollTop || 0) + marginBottom)
  }, paddingTop) : 0
  return Math.ceil((element.querySelector<HTMLElement>('.app-window-dialog__header')?.getBoundingClientRect().height || 0)
    + contentBottom + paddingBottom
    + (element.querySelector<HTMLElement>('.app-window-dialog__footer')?.getBoundingClientRect().height || 0)
    + element.offsetHeight - element.clientHeight)
}

function stopAutoFit() {
  autoContentObserver?.disconnect()
  autoContentObserver = null
  autoRootObserver?.disconnect()
  autoRootObserver = null
  if (autoFitFrame !== null) window.cancelAnimationFrame(autoFitFrame)
  autoFitFrame = null
}

function fitAutoHeight() {
  autoFitFrame = null
  const element = windowRef.value
  const current = rect.value
  if (!element || !current || !props.modelValue || state.value !== 'normal' || manuallyAdjusted) return
  const height = Math.max(requestedHeight, naturalContentHeight(element))
  if (!height) return
  const next = clampRect({ ...current, height })
  next.y = (viewportSize.value.height - next.height) / 2
  if (Math.abs(next.height - current.height) > 0.5 || Math.abs(next.y - current.y) > 0.5) rect.value = next
}

function queueAutoFit() {
  if (!props.modelValue || state.value !== 'normal' || manuallyAdjusted || autoFitFrame !== null || typeof window.requestAnimationFrame !== 'function') return
  autoFitFrame = window.requestAnimationFrame(fitAutoHeight)
}

function observeAutoContent() {
  stopAutoFit()
  if (typeof ResizeObserver === 'undefined') return
  const element = windowRef.value
  const body = element?.querySelector<HTMLElement>('.app-window-dialog__body')
  if (!body) return
  autoContentObserver = new ResizeObserver(queueAutoFit)
  const observeRoots = () => {
    autoContentObserver?.disconnect()
    Array.from(body.children).forEach(child => autoContentObserver?.observe(child))
    element?.querySelectorAll('.app-window-dialog__header, .app-window-dialog__footer').forEach(child => autoContentObserver?.observe(child))
  }
  observeRoots()
  autoRootObserver = new MutationObserver(() => {
    observeRoots()
    queueAutoFit()
  })
  autoRootObserver.observe(body, { childList: true })
  if (element) autoRootObserver.observe(element, { childList: true })
}

const windowStyle = computed(() => {
  const viewport = typeof window === 'undefined' ? { width: 1920, height: 1080, padding: 16 } : viewportBounds()
  if (state.value === 'minimized') {
    const width = Math.min(320, viewport.width - viewport.padding * 2)
    return {
      left: `${viewport.width - width - viewport.padding}px`,
      top: `${viewport.height - 44 - viewport.padding}px`,
      width: `${width}px`,
      height: '44px',
    }
  }
  if (state.value === 'maximized') {
    const padding = props.edgeToEdge ? 0 : viewport.padding
    return {
      left: `${padding}px`,
      top: `${padding}px`,
      width: `${viewport.width - padding * 2}px`,
      height: `${viewport.height - padding * 2}px`,
    }
  }
  if (rect.value) {
    return {
      left: `${rect.value.x}px`,
      top: `${rect.value.y}px`,
      width: `${rect.value.width}px`,
      height: `${rect.value.height}px`,
    }
  }
  return {
    width: cssSize(props.width),
    height: props.height === 'auto' ? 'auto' : cssSize(props.height),
    maxWidth: 'calc(100vw - 32px)',
    maxHeight: `min(${props.autoMaxHeightRatio * 100}vh, calc(100vh - 32px))`,
  }
})

function lockBody() {
  if (!props.lockScroll || bodyLocked || state.value === 'minimized') return
  if (bodyLockCount === 0) {
    bodyOverflowBeforeFirstLock = document.body.style.overflow
    document.body.style.overflow = 'hidden'
  }
  bodyLockCount += 1
  bodyLocked = true
}

function unlockBody() {
  if (!bodyLocked) return
  bodyLocked = false
  bodyLockCount = Math.max(0, bodyLockCount - 1)
  if (bodyLockCount === 0) {
    document.body.style.overflow = bodyOverflowBeforeFirstLock
    bodyOverflowBeforeFirstLock = ''
  }
}

async function initializeWindow() {
  await nextTick()
  if (props.height === 'auto' && typeof window.requestAnimationFrame === 'function') {
    await new Promise<void>(resolve => window.requestAnimationFrame(() => window.requestAnimationFrame(() => resolve())))
  }
  const element = windowRef.value
  if (!props.modelValue || !element) return
  const viewport = viewportBounds()
  const measured = element.getBoundingClientRect()
  // 显式高度保留工作区下限；内容仍可自动增高，默认上限为 80vh。
  requestedHeight = props.height === 'auto' ? 0 : pixelFallback(props.height, measured.height)
  if (props.fullscreen) {
    const width = Math.min(pixelFallback(props.width, 680), viewport.width - viewport.padding * 2)
    const height = Math.max(requestedHeight, naturalContentHeight(element))
    const normalRect = clampRect({
      x: (viewport.width - width) / 2,
      y: (viewport.height - height) / 2,
      width,
      height,
    })
    normalRect.y = (viewport.height - normalRect.height) / 2
    restoreRect.value = normalRect
    rect.value = normalRect
    observeAutoContent()
    element.focus({ preventScroll: true })
    emit('opened')
    return
  }
  const targetHeight = Math.max(requestedHeight, naturalContentHeight(element))
  const initial = clampRect({
    x: (viewport.width - measured.width) / 2,
    y: (viewport.height - targetHeight) / 2,
    width: measured.width || Math.min(pixelFallback(props.width, 680), viewport.width - 32),
    height: targetHeight || Math.min(pixelFallback(props.height, 420), viewport.height - 32),
  })
  initial.y = (viewport.height - initial.height) / 2
  rect.value = initial
  observeAutoContent()
  element.focus({ preventScroll: true })
  emit('opened')
}

function commitClose() {
  emit('update:modelValue', false)
}

function requestClose() {
  if (props.beforeClose) props.beforeClose(commitClose)
  else commitClose()
}

function minimize() {
  if (!props.minimizable) return
  if (state.value === 'minimized') {
    state.value = stateBeforeMinimize.value
    if (state.value === 'normal' && restoreRect.value) rect.value = clampRect(restoreRect.value)
    lockBody()
    queueAutoFit()
    return
  }
  stateBeforeMinimize.value = state.value
  if (state.value === 'normal' && windowRef.value) {
    const current = windowRef.value.getBoundingClientRect()
    restoreRect.value = { x: current.left, y: current.top, width: current.width, height: current.height }
  }
  state.value = 'minimized'
  unlockBody()
}

function toggleMaximize() {
  if (state.value === 'maximized') {
    state.value = 'normal'
    if (restoreRect.value) rect.value = clampRect(restoreRect.value)
    queueAutoFit()
    return
  }
  if (state.value === 'normal' && windowRef.value) {
    const current = windowRef.value.getBoundingClientRect()
    restoreRect.value = { x: current.left, y: current.top, width: current.width, height: current.height }
  }
  state.value = 'maximized'
  lockBody()
}

function beginInteraction(event: PointerEvent, type: 'drag' | 'resize') {
  if (event.button !== 0 || state.value !== 'normal' || !windowRef.value) return
  if (type === 'drag' && (event.target as HTMLElement).closest('.app-window-dialog__actions')) return
  const current = windowRef.value.getBoundingClientRect()
  interaction = {
    type,
    startX: event.clientX,
    startY: event.clientY,
    rect: { x: current.left, y: current.top, width: current.width, height: current.height },
  }
  window.addEventListener('pointermove', continueInteraction)
  window.addEventListener('pointerup', endInteraction, { once: true })
  event.preventDefault()
}

function continueInteraction(event: PointerEvent) {
  if (!interaction) return
  const dx = event.clientX - interaction.startX
  const dy = event.clientY - interaction.startY
  if (dx !== 0 || dy !== 0) {
    manuallyAdjusted = true
    stopAutoFit()
  }
  rect.value = clampRect(interaction.type === 'drag'
    ? { ...interaction.rect, x: interaction.rect.x + dx, y: interaction.rect.y + dy }
    : { ...interaction.rect, width: interaction.rect.width + dx, height: interaction.rect.height + dy })
}

function endInteraction() {
  interaction = null
  window.removeEventListener('pointermove', continueInteraction)
}

function handleViewportResize() {
  viewportSize.value = { width: window.innerWidth, height: window.innerHeight }
  if (state.value !== 'normal' || !rect.value) return
  const nextRect = clampRect(rect.value)
  if (props.centerOnResize) {
    rect.value = {
      ...nextRect,
      x: (viewportSize.value.width - nextRect.width) / 2,
      y: (viewportSize.value.height - nextRect.height) / 2,
    }
    queueAutoFit()
    return
  }
  rect.value = nextRect
  queueAutoFit()
}

function handleOverlayClick(event: MouseEvent) {
  if (event.target === event.currentTarget && props.closeOnClickModal && state.value !== 'minimized') requestClose()
}

function handleKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape' && props.closeOnPressEscape) {
    event.preventDefault()
    requestClose()
    return
  }
  if (event.key !== 'Tab' || !windowRef.value) return
  const focusable = Array.from(windowRef.value.querySelectorAll<HTMLElement>(
    'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [href], [tabindex]:not([tabindex="-1"])',
  )).filter(element => element.offsetParent !== null)
  if (!focusable.length) {
    event.preventDefault()
    windowRef.value.focus()
    return
  }
  const first = focusable[0]
  const last = focusable[focusable.length - 1]
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault()
    first.focus()
  }
}

watch(() => props.modelValue, visible => {
  if (visible) {
    stopAutoFit()
    manuallyAdjusted = false
    rendered.value = true
    state.value = props.fullscreen ? 'maximized' : 'normal'
    rect.value = null
    restoreRect.value = null
    previouslyFocused.value = document.activeElement as HTMLElement | null
    overlayZIndex.value = nextZIndex()
    emit('open')
    lockBody()
    void initializeWindow()
    return
  }
  if (!rendered.value) return
  stopAutoFit()
  unlockBody()
  emit('close')
  nextTick(() => {
    if (props.destroyOnClose) rendered.value = false
    previouslyFocused.value?.focus?.({ preventScroll: true })
    emit('closed')
  })
}, { immediate: true })

watch(() => props.fullscreen, fullscreen => {
  if (!props.modelValue) return
  if (fullscreen && state.value !== 'maximized') {
    if (state.value === 'normal' && windowRef.value) {
      const current = windowRef.value.getBoundingClientRect()
      restoreRect.value = { x: current.left, y: current.top, width: current.width, height: current.height }
    }
    state.value = 'maximized'
    lockBody()
  } else if (!fullscreen && state.value === 'maximized') {
    state.value = 'normal'
    if (restoreRect.value) rect.value = clampRect(restoreRect.value)
    queueAutoFit()
  }
})

window.addEventListener('resize', handleViewportResize)

onBeforeUnmount(() => {
  stopAutoFit()
  unlockBody()
  window.removeEventListener('resize', handleViewportResize)
  window.removeEventListener('pointermove', continueInteraction)
  window.removeEventListener('pointerup', endInteraction)
})
</script>

<template>
  <Teleport to="body">
    <div
      v-if="rendered"
      v-show="modelValue"
      class="app-window-overlay"
      :class="[{ 'is-minimized': state === 'minimized' }, modalClass]"
      :style="{ zIndex: overlayZIndex }"
      @mousedown="handleOverlayClick"
      @keydown="handleKeydown"
    >
      <section
        ref="windowRef"
        v-bind="forwardedAttrs"
        class="el-dialog app-window-dialog"
        :class="[$attrs.class, `is-${state}`]"
        :style="[windowStyle, $attrs.style]"
        role="dialog"
        :aria-modal="state !== 'minimized'"
        :aria-label="title"
        tabindex="-1"
      >
        <header v-if="withHeader" class="el-dialog__header app-window-dialog__header" @pointerdown="beginInteraction($event, 'drag')">
          <div class="app-window-dialog__heading">
            <slot name="header"><span class="el-dialog__title"><slot name="title">{{ title }}</slot></span></slot>
          </div>
          <div class="app-window-dialog__actions">
            <button v-if="minimizable" type="button" :aria-label="state === 'minimized' ? '还原' : '最小化'" :title="state === 'minimized' ? '还原' : '最小化'" @click="minimize"><ElIcon><Rank v-if="state === 'minimized'" /><Minus v-else /></ElIcon></button>
            <button type="button" :aria-label="state === 'maximized' ? '还原' : '最大化'" :title="state === 'maximized' ? '还原' : '最大化'" @click="toggleMaximize">
              <ElIcon><Rank v-if="state === 'maximized'" /><FullScreen v-else /></ElIcon>
            </button>
            <button v-if="showClose" type="button" aria-label="关闭" title="关闭" @click="requestClose"><ElIcon><Close /></ElIcon></button>
          </div>
        </header>
        <div v-show="state !== 'minimized'" class="el-dialog__body app-window-dialog__body"><slot /></div>
        <footer v-if="slots.footer" v-show="state !== 'minimized'" class="el-dialog__footer app-window-dialog__footer"><slot name="footer" /></footer>
        <button
          v-show="state === 'normal'"
          class="app-window-dialog__resize-handle"
          type="button"
          aria-label="调整窗口大小"
          title="拖动调整窗口大小"
          @pointerdown="beginInteraction($event, 'resize')"
        />
      </section>
    </div>
  </Teleport>
</template>

<style scoped lang="scss">
@use '../../styles/crm/tokens' as token;

.app-window-overlay {
  position: fixed;
  inset: 0;
  background: color-mix(in srgb, var(--erp-overlay-scrim-color) 34%, transparent);

  &.is-minimized {
    pointer-events: none;
    background: transparent;
  }
}

.app-window-dialog {
  position: fixed;
  box-sizing: border-box;
  display: flex;
  min-width: 0;
  min-height: 0;
  flex-direction: column;
  margin: 0;
  padding: 0;
  overflow: hidden;
  border: 1px solid token.$crm-border-default;
  border-radius: token.$crm-radius-3;
  color: token.$crm-text-primary;
  background: token.$crm-color-surface;
  box-shadow: 0 18px 48px color-mix(in srgb, var(--erp-shadow-color) 18%, transparent);
  font-family: token.$crm-font-body;
  pointer-events: auto;
  outline: none;
  --el-color-primary: #{token.$crm-primary};
  --el-border-color: #{token.$crm-border-default};
  --el-fill-color-blank: #{token.$crm-color-surface};
  --el-text-color-primary: #{token.$crm-text-primary};
  --el-text-color-regular: #{token.$crm-text-regular};

  &.is-maximized {
    border-radius: token.$crm-radius-2;
  }

  &.is-minimized {
    border-radius: token.$crm-radius-2;
    box-shadow: 0 8px 24px color-mix(in srgb, var(--erp-shadow-color) 20%, transparent);

    .app-window-dialog__header {
      border-bottom: 0;
      cursor: default;
    }
  }
}

.app-window-dialog.el-dialog > .app-window-dialog__header {
  box-sizing: border-box;
  display: flex;
  height: 44px !important;
  min-height: 44px !important;
  align-items: center;
  justify-content: space-between;
  margin: 0 !important;
  padding: 0 104px 0 16px !important;
  border-bottom: 1px solid token.$crm-border-subtle;
  cursor: move;
  user-select: none;

  .el-dialog__title {
    overflow: hidden;
    color: token.$crm-text-primary;
    font-family: token.$crm-font-display;
    font-size: 16px;
    font-weight: 600;
    line-height: 22px;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
}

.app-window-dialog__heading {
  min-width: 0;
  flex: 1 1 auto;
}

.app-window-dialog__actions {
  position: absolute;
  z-index: 1;
  top: 0;
  right: 0;
  display: flex;
  width: 96px;
  flex: none;
  height: 32px;
  align-items: center;
  gap: 0;

  button {
    display: inline-grid;
    place-items: center;
    width: 32px;
    height: 32px;
    padding: 0;
    border: 0;
    border-radius: token.$crm-radius-2;
    color: token.$crm-text-secondary;
    background: transparent;
    cursor: pointer;
    font-size: 16px;
    line-height: 1;

    .el-icon {
      display: inline-flex;
      width: 16px;
      height: 16px;
      align-items: center;
      justify-content: center;
      margin: 0;
      font-size: 16px;
    }

    &:hover {
      color: token.$crm-text-primary;
      background: token.$crm-color-subtle;
      outline: 1px solid token.$crm-focus;
      outline-offset: -1px;
    }

    &:focus-visible {
      color: token.$crm-text-primary;
      background: token.$crm-color-subtle;
      outline: 2px solid token.$crm-focus;
      outline-offset: 2px;
    }

    &:last-child:hover {
      color: token.$crm-text-inverse;
      background: token.$crm-danger;
    }
  }
}

.app-window-dialog.el-dialog {
  min-height: 0 !important;
}

/* 窗口统一分配正文高度，避免调用页的旧限高留下空白或提前滚动。 */
.app-window-dialog.el-dialog > .app-window-dialog__body {
  height: auto !important;
  min-height: 0 !important;
  max-height: none !important;
  flex: 1 1 auto !important;
}

.app-window-dialog__body {
  overflow: auto;
  padding: 20px 24px;
}

/* 业务弹窗统一执行 ERP 32px 单行控件规范，避免调用页旧样式重新放大控件。 */
.app-window-dialog {
  :deep(.el-button:not(:where(.paper *, .quotation-document *, .a4-canvas *, .contract-sheet *, .el-table *))),
  :deep(.el-input:not(.el-textarea) .el-input__wrapper:not(:where(.paper *, .quotation-document *, .a4-canvas *, .contract-sheet *, .el-table *))),
  :deep(.el-select__wrapper:not(:where(.paper *, .quotation-document *, .a4-canvas *, .contract-sheet *, .el-table *))),
  :deep(.el-date-editor.el-input__wrapper:not(:where(.paper *, .quotation-document *, .a4-canvas *, .contract-sheet *, .el-table *))),
  :deep(.el-date-editor.el-range-editor:not(:where(.paper *, .quotation-document *, .a4-canvas *, .contract-sheet *, .el-table *))),
  :deep(.el-autocomplete .el-input__wrapper:not(:where(.paper *, .quotation-document *, .a4-canvas *, .contract-sheet *, .el-table *))),
  :deep(.el-cascader .el-input__wrapper:not(:where(.paper *, .quotation-document *, .a4-canvas *, .contract-sheet *, .el-table *))),
  :deep(.el-input-number:not(:where(.paper *, .quotation-document *, .a4-canvas *, .contract-sheet *, .el-table *))),
  :deep(.el-input-number .el-input:not(:where(.paper *, .quotation-document *, .a4-canvas *, .contract-sheet *, .el-table *))),
  :deep(.el-input-number .el-input__wrapper:not(:where(.paper *, .quotation-document *, .a4-canvas *, .contract-sheet *, .el-table *))) {
    box-sizing: border-box;
    height: 32px !important;
    min-height: 32px !important;
  }

  :deep(.el-form-item) {
    margin-bottom: 12px;
  }

  :deep(.el-form-item__label) {
    padding-bottom: 4px;
    line-height: 20px;
  }
}

.app-window-dialog.el-dialog > .app-window-dialog__footer {
  height: auto !important;
  min-height: 0 !important;
  flex: 0 0 auto !important;
  padding-top: 6px !important;
  padding-bottom: 8px !important;
}

.app-window-dialog__footer {
  padding: 6px 24px 8px;
  border-top: 1px solid token.$crm-border-subtle;

  :deep(.el-button) {
    height: 32px !important;
  }
}

.app-window-dialog__resize-handle {
  position: absolute;
  right: 0;
  bottom: 0;
  width: 18px;
  height: 18px;
  padding: 0;
  border: 0;
  background: transparent;
  cursor: nwse-resize;

  &::after {
    position: absolute;
    right: 4px;
    bottom: 4px;
    width: 7px;
    height: 7px;
    border-right: 2px solid token.$crm-border-strong;
    border-bottom: 2px solid token.$crm-border-strong;
    content: '';
  }
}

@media (max-width: 640px) {
  .app-window-dialog.el-dialog > .app-window-dialog__header { padding-left: 12px; }
  .app-window-dialog__body { padding: 16px; }
  .app-window-dialog__footer { padding-inline: 16px; }
}
</style>
