<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useBoardAutoScroll } from '../useBoardAutoScroll'
import '../boardLists.scss'

interface RankingRow {
  name: string
  value: number
}

const props = withDefaults(defineProps<{ rows: RankingRow[]; label?: string }>(), { label: '入库商品数量排行' })
const sortedRows = computed(() => [...props.rows].sort((left, right) => right.value - left.value))
const maximum = computed(() => Math.max(1, ...sortedRows.value.map((row) => row.value)))
const viewport = ref<HTMLElement>()
const content = ref<HTMLElement>()
const { hovered, focused, looping, reset } = useBoardAutoScroll(viewport, content)
watch(sortedRows, reset, { flush: 'post' })
</script>

<template>
  <div ref="viewport" class="board-table-scroll board-list-scroll board-ranking-list" :data-loop-active="looping"
    tabindex="0" :aria-label="`${label}，可滚动；停留时暂停轮播`"
    @mouseenter="hovered = true" @mouseleave="hovered = false" @focusin="focused = true" @focusout="focused = false">
    <ol ref="content" class="board-ranking-list-content" data-loop-content>
      <li v-for="(row, index) in sortedRows" :key="row.name" :class="{ 'is-leading': index === 0 }">
        <span class="board-ranking-name" :title="row.name">{{ row.name }}</span>
        <div class="board-ranking-track" role="meter" :aria-label="`${row.name}${label}`" :aria-valuemin="0" :aria-valuemax="maximum" :aria-valuenow="row.value">
          <span class="board-ranking-fill" :style="{ width: `${row.value / maximum * 80}%` }" /><span class="board-ranking-value">{{ row.value }}</span>
        </div>
      </li>
    </ol>
    <ol v-if="looping" class="board-ranking-list-content" data-loop-copy aria-hidden="true" inert>
      <li v-for="(row, index) in sortedRows" :key="row.name" :class="{ 'is-leading': index === 0 }">
        <span class="board-ranking-name" :title="row.name">{{ row.name }}</span>
        <div class="board-ranking-track" role="meter" :aria-label="`${row.name}${label}`" :aria-valuemin="0" :aria-valuemax="maximum" :aria-valuenow="row.value">
          <span class="board-ranking-fill" :style="{ width: `${row.value / maximum * 80}%` }" /><span class="board-ranking-value">{{ row.value }}</span>
        </div>
      </li>
    </ol>
    <p v-if="sortedRows.length === 0" class="board-empty">暂无演示记录</p>
  </div>
</template>
