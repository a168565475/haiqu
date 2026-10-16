<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import type { BoardColumn, BoardRow } from '@/types/board'
import '../boardFeed.scss'

const props = defineProps<{ columns: BoardColumn[]; rows: BoardRow[] }>()
const focused = ref(false)
const first = ref(0)
const progress = ref(0)
const rows = computed(() => props.rows.map((_, index) => props.rows[(index + first.value) % props.rows.length]!))
let frame = 0
let previousTime: number | undefined
let media: MediaQueryList | undefined

function resetMotion() { progress.value = first.value = 0; previousTime = undefined }
function visibilityChanged() { previousTime = undefined }
function tick(time: number) {
  const elapsed = previousTime === undefined ? 0 : Math.min(time - previousTime, 100)
  previousTime = time
  // 原站报工悬停时仍轮换；键盘阅读、隐藏页及减少动态效果时暂停。
  if (props.rows.length > 1 && !focused.value && !media?.matches && !document.hidden) {
    progress.value += elapsed / 1000
    if (progress.value >= 1) {
      first.value = (first.value + 1) % props.rows.length
      progress.value %= 1
    }
  }
  frame = requestAnimationFrame(tick)
}
onMounted(() => {
  media = window.matchMedia?.('(prefers-reduced-motion: reduce)')
  media?.addEventListener('change', resetMotion)
  document.addEventListener('visibilitychange', visibilityChanged)
  frame = requestAnimationFrame(tick)
})
onBeforeUnmount(() => {
  cancelAnimationFrame(frame)
  media?.removeEventListener('change', resetMotion)
  document.removeEventListener('visibilitychange', visibilityChanged)
})
</script>

<template>
  <div class="board-table-scroll board-feed-scroll" data-motion="feed" tabindex="0" aria-label="实时报工数据，键盘聚焦时暂停轮播"
    @focusin="focused = true" @focusout="focused = false">
    <table class="board-table board-feed-table">
      <colgroup><col v-for="column in columns" :key="column.key" :style="{ width: column.width }" /></colgroup>
      <thead><tr><th v-for="column in columns" :key="column.key" scope="col">{{ column.label }}</th></tr></thead>
      <tbody><tr v-for="(row, index) in rows" :key="index" :data-feed-row="index === 0 ? '' : undefined"
        :style="index === 0 ? { opacity: 1 - progress, '--board-feed-height': `${38 * (1 - progress)}px` } : undefined">
        <td v-for="column in columns" :key="column.key" :class="column.tone ? `board-tone-${column.tone}` : undefined" :title="String(row[column.key] ?? '—')">
          <div class="board-feed-cell">{{ row[column.key] ?? '—' }}</div>
        </td>
      </tr></tbody>
    </table>
    <p v-if="rows.length === 0" class="board-empty">暂无演示记录</p>
  </div>
</template>
