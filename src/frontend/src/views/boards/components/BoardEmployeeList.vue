<script setup lang="ts">
import { ref, watch } from 'vue'
import { useBoardAutoScroll } from '../useBoardAutoScroll'
import defaultAvatar from '@/assets/boards/default-avatar.png'
import '../boardLists.scss'

interface EmployeeRow {
  name: string
  reported: number
  defective: number
  weeklyDefective?: number
  totalDefective?: number
}

const props = defineProps<{ rows: EmployeeRow[] }>()
const viewport = ref<HTMLElement>()
const content = ref<HTMLElement>()
const { hovered, focused, looping, reset } = useBoardAutoScroll(viewport, content)
watch(() => props.rows, reset, { flush: 'post' })
</script>

<template>
  <div ref="viewport" class="board-table-scroll board-list-scroll board-employee-list" :data-loop-active="looping"
    tabindex="0" aria-label="人员生产统计，可滚动；停留时暂停轮播"
    @mouseenter="hovered = true" @mouseleave="hovered = false" @focusin="focused = true" @focusout="focused = false">
    <div ref="content" class="board-employees board-employee-list-content" data-loop-content>
      <article v-for="employee in rows" :key="employee.name">
        <div class="board-employee-identity"><img class="board-avatar" :src="defaultAvatar" alt="" /><p :title="employee.name">{{ employee.name }}</p></div>
        <div class="board-employee-statistics"><p>今日报工数：<span class="board-tone-green">{{ employee.reported }}</span></p><p>本周不良品数：<span class="board-tone-red">{{ employee.weeklyDefective ?? '—' }}</span></p><p>本月不良品数：<span class="board-tone-red">{{ employee.totalDefective ?? '—' }}</span></p></div>
      </article>
    </div>
    <div v-if="looping" class="board-employees board-employee-list-content" data-loop-copy aria-hidden="true" inert>
      <article v-for="employee in rows" :key="employee.name">
        <div class="board-employee-identity"><img class="board-avatar" :src="defaultAvatar" alt="" /><p :title="employee.name">{{ employee.name }}</p></div>
        <div class="board-employee-statistics"><p>今日报工数：<span class="board-tone-green">{{ employee.reported }}</span></p><p>本周不良品数：<span class="board-tone-red">{{ employee.weeklyDefective ?? '—' }}</span></p><p>本月不良品数：<span class="board-tone-red">{{ employee.totalDefective ?? '—' }}</span></p></div>
      </article>
    </div>
    <p v-if="rows.length === 0" class="board-empty">暂无演示记录</p>
  </div>
</template>
