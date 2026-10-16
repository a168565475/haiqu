<script setup lang="ts">
import { ref, watch, type ComponentPublicInstance } from 'vue'
import type { BoardColumn, BoardRow } from '@/types/board'
import { useBoardAutoScroll } from '../useBoardAutoScroll'
const props = defineProps<{ columns: BoardColumn[]; rows: BoardRow[] }>()
const scroll = ref<HTMLElement>()
const content = ref<HTMLElement>()
function setContent(element: Element | ComponentPublicInstance | null) { content.value = element as HTMLElement | undefined }
const { hovered, focused, looping, reset } = useBoardAutoScroll(scroll, content, 26.84)
watch(() => props.rows, reset, { flush: 'post' })
</script>

<template>
  <div ref="scroll" class="board-table-scroll" :data-loop-active="looping" tabindex="0" aria-label="数据表格，可滚动；停留时暂停轮播"
    @mouseenter="hovered = true" @mouseleave="hovered = false" @focusin="focused = true" @focusout="focused = false">
    <table class="board-table">
      <colgroup><col v-for="column in columns" :key="column.key" :style="{ width: column.width }" /></colgroup>
      <thead><tr><th v-for="column in columns" :key="column.key" scope="col">{{ column.label }}</th></tr></thead>
      <tbody v-for="copy in looping ? 2 : 1" :key="copy" :ref="copy === 1 ? setContent : undefined"
        :data-loop-content="copy === 1 ? '' : undefined" :data-loop-copy="copy === 2 ? '' : undefined"
        :aria-hidden="copy === 2 ? 'true' : undefined" :inert="copy === 2"><tr v-for="(row, index) in rows" :key="index">
        <td v-for="column in columns" :key="column.key" :class="column.tone ? `board-tone-${column.tone}` : undefined" :title="String(row[column.key] ?? '—')">{{ row[column.key] ?? '—' }}</td>
      </tr></tbody>
    </table>
    <p v-if="rows.length === 0" class="board-empty">暂无演示记录</p>
  </div>
</template>
