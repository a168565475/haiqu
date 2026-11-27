<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ArrowRight, Calendar } from '@element-plus/icons-vue'
import { getDirectorItems } from '@/api/workshopDirectorWorkbench'
import type { DirectorJob, DirectorOverview, DirectorSelection } from '@/types/workshopDirectorWorkbench'
import { workbenchErrorMessage } from '@/utils/workbench'
import { deadlineLabel, shortDate, stageLabel } from './WorkshopDirectorDisplay'

const props = defineProps<{ overview: DirectorOverview }>()
const emit = defineEmits<{ select: [DirectorSelection] }>()
const day = ref(props.overview.as_of)
const chosen = computed(() => props.overview.upcoming.find(item => item.date === day.value))
const total = computed(() => props.overview.upcoming.reduce((sum, item) => sum + item.count, 0))
const rows = ref<DirectorJob[] | null>(null), error = ref(''), retry = ref(0)
const weekDay = new Intl.DateTimeFormat('zh-CN', { weekday: 'short', timeZone: 'Asia/Shanghai' })
watch([chosen, retry], async ([selected], _, cleanup) => {
  rows.value = null
  error.value = ''
  if (!selected?.count) { rows.value = []; return }
  const request = new AbortController()
  cleanup(() => request.abort())
  try {
    const result = await getDirectorItems(props.overview.workshop, 'day', selected.date, 1, request.signal, 2)
    if (!request.signal.aborted) rows.value = result.data
  } catch (cause) {
    if (!request.signal.aborted) error.value = workbenchErrorMessage(cause, '加载当日排程')
  }
}, { immediate: true })
</script>

<template>
  <section class="glass director-calendar">
    <h2><Calendar />未来七天完工排程</h2><p class="context">按{{ deadlineLabel[overview.workshop] }}查看尚未完工的产品计划</p>
    <div class="day-selector"><button v-for="item in overview.upcoming" :key="item.date" type="button" :aria-label="item.date + '到期 ' + item.count + ' 项'" :aria-pressed="day === item.date" @click="day = item.date">
      <small>{{ item.date === overview.as_of ? '今天' : weekDay.format(new Date(item.date)) }}</small><span>{{ shortDate(item.date) }}</span><b>{{ item.count }}<small>项</small></b>
    </button></div>
    <div class="day-head"><strong>{{ shortDate(day) }} 到期的产品计划</strong>
      <button v-if="chosen && rows && chosen.count > rows.length" class="action" @click="emit('select', { kind: 'items', category: 'day', date: day, title: day + ' 完工排程' })">查看全部 {{ chosen.count }} 项 ›</button></div>
    <p v-if="error" role="alert" class="context">{{ error }} <button class="action" @click="retry++">重试</button></p>
    <p v-else-if="!rows" role="status" class="context">正在加载排程…</p>
    <p v-else-if="!rows.length" class="empty">当天没有待完工的产品计划。</p>
    <button v-for="job in rows" :key="job.id" type="button" class="day-job" @click="emit('select', { kind: 'detail', id: job.id })">
      <span><b>{{ job.task_number }}</b><small>{{ job.product_name }}<template v-if="job.craft_name"> · {{ job.craft_name }}</template></small></span><small>{{ stageLabel[job.stage] }} <ArrowRight /></small>
    </button>
    <footer class="board-foot"><span>七天共 {{ total }} 项产品计划</span><button class="action" @click="emit('select', { kind: 'items', category: 'week', title: '未来七天完工排程' })">查看七天排程 ›</button></footer>
  </section>
</template>
