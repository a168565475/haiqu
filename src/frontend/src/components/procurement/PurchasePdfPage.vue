<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import type { PDFDocumentProxy, PDFPageProxy, RenderTask } from 'pdfjs-dist'

const props = defineProps<{ document: PDFDocumentProxy; pageNumber: number; initialHeight: number; scrollRoot: HTMLElement }>()
const emit = defineEmits<{ ready: []; error: [] }>()
const element = ref<HTMLElement>()
const canvas = ref<HTMLCanvasElement>()
const height = ref(props.initialHeight)
const active = ref(false)
const rendered = ref(false)
const text = ref('')
let observer: IntersectionObserver | null = null
let renderTask: RenderTask | null = null
let page: PDFPageProxy | null = null
let generation = 0

function release(): void {
  generation++
  renderTask?.cancel()
  renderTask = null
  active.value = false
  rendered.value = false
  // 每次进入可视区创建新画布，旧任务即使尚未结束也不会覆盖新页面。
  if (canvas.value) canvas.value.width = canvas.value.height = 0
  page?.cleanup()
}

async function render(): Promise<void> {
  if (active.value) return
  active.value = true
  const current = ++generation
  try {
    const pdfPage = await props.document.getPage(props.pageNumber)
    if (current !== generation) return
    page = pdfPage
    const original = pdfPage.getViewport({ scale: 1 })
    const viewport = pdfPage.getViewport({ scale: 830 / original.width })
    height.value = viewport.height
    await nextTick()
    if (current !== generation || !canvas.value) return
    const target = canvas.value
    const scale = Math.min(window.devicePixelRatio || 1, 2)
    target.width = Math.ceil(viewport.width * scale)
    target.height = Math.ceil(viewport.height * scale)
    const task = pdfPage.render({ canvas: target, viewport, transform: [scale, 0, 0, scale, 0, 0] })
    renderTask = task
    await task.promise
    const content = await pdfPage.getTextContent()
    if (current !== generation) return
    text.value = content.items.map(item => 'str' in item ? item.str : '').join(' ')
    rendered.value = true
    emit('ready')
  } catch {
    if (current === generation) emit('error')
  } finally {
    if (current === generation) renderTask = null
    else page?.cleanup()
  }
}

onMounted(() => {
  observer = new IntersectionObserver(entries => {
    if (entries.some(entry => entry.isIntersecting)) void render()
    else release()
  }, { root: props.scrollRoot, rootMargin: '400px 0px' })
  if (element.value) observer.observe(element.value)
})
onBeforeUnmount(() => { observer?.disconnect(); release() })
</script>

<template>
  <div ref="element" class="pdf-paper" :style="{ height: `${height}px` }" :data-page="pageNumber" :data-rendered="rendered"
    role="document" :aria-label="`采购表第 ${pageNumber} 页`" :aria-busy="active && !rendered">
    <canvas v-if="active" ref="canvas" class="pdf-page-canvas" :style="{ height: `${height}px` }" aria-hidden="true" />
    <p v-if="active && !rendered" class="pdf-page-loading">正在加载第 {{ pageNumber }} 页…</p>
    <p class="pdf-accessible-text">{{ text }}</p>
  </div>
</template>

<style lang="scss" scoped>
.pdf-paper { position: relative; width: 830px; flex: none; background: white; box-shadow: 0 2px 10px color-mix(in srgb, var(--erp-shadow-color) 7.843%, transparent); }
.pdf-page-canvas { display: block; width: 830px; }
.pdf-page-loading { position: absolute; top: 35px; width: 100%; text-align: center; color: var(--erp-color-text-secondary); font-size: 14px; }
.pdf-accessible-text { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip-path: inset(50%); white-space: nowrap; }
</style>
