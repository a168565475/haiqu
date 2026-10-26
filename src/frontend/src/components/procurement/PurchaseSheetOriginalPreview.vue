<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import type { CSSProperties } from 'vue'
import type { PurchaseSheetPreview } from '@/types/purchaseOrder'

const props = defineProps<{ preview: PurchaseSheetPreview }>()
const container = ref<HTMLElement>()
const availableWidth = ref(800)
let observer: ResizeObserver | undefined
const pageWidth = computed(() => props.preview.width + props.preview.margins.left + props.preview.margins.right)
const scale = computed(() => Math.min(1, Math.max(0.1, (availableWidth.value - 24) / pageWidth.value)))
const pageStyle = computed(() => ({
  width: `${pageWidth.value}px`,
  padding: `${props.preview.margins.top}px ${props.preview.margins.right}px ${props.preview.margins.bottom}px ${props.preview.margins.left}px`,
  zoom: scale.value,
}))
watch(container, element => {
  observer?.disconnect()
  if (!element || typeof ResizeObserver === 'undefined') return
  observer = new ResizeObserver(() => { availableWidth.value = element.clientWidth })
  observer.observe(element)
  availableWidth.value = element.clientWidth
})
onBeforeUnmount(() => observer?.disconnect())
</script>

<template>
  <div ref="container" class="original-preview" aria-label="原版 Excel 合同预览">
    <article class="original-page" :style="pageStyle">
      <div class="original-sheet" :style="{ width: `${preview.width}px` }">
        <table aria-label="原版合同" :style="{ width: `${preview.width}px` }">
          <colgroup><col v-for="(width, index) in preview.columns" :key="index" :style="{ width: `${width}px` }"></colgroup>
          <tbody><tr v-for="(row, index) in preview.rows" :key="index" :style="{ height: `${row.height}px` }">
            <td v-for="cell in row.cells" :key="cell.address" :data-cell="cell.address" :rowspan="cell.rowspan" :colspan="cell.colspan" :style="cell.style as CSSProperties"><span v-for="(run, i) in cell.runs" :key="i" :style="run.style as CSSProperties">{{ run.text }}</span></td>
          </tr></tbody>
        </table>
        <img v-for="(picture, index) in preview.images" :key="index" :src="picture.src" alt="合同原版图片" :style="{ left: `${picture.left}px`, top: `${picture.top}px`, width: `${picture.width}px`, height: `${picture.height}px` }">
      </div>
    </article>
  </div>
</template>

<style scoped>
.original-preview { width: 100%; min-width: 0; padding: 12px 0; }
.original-page { box-sizing: border-box; margin: 0 auto; background: #fff; color: #000; }
.original-sheet { position: relative; }
table { border-collapse: collapse; table-layout: fixed; border: none; }
td { box-sizing: border-box; padding: 0 2px; overflow-wrap: anywhere; }
img { position: absolute; object-fit: contain; pointer-events: none; }
</style>
