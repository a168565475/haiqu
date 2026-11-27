<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ArrowRight, Calendar, Flag, Tickets } from '@element-plus/icons-vue'
import { getSewingOverview } from '@/api/sewingOutsourcingWorkbench'
import { useAuthStore } from '@/stores/auth'
import { workbenchErrorMessage } from '@/utils/workbench'
import type { SewingFollow, SewingQueue, SewingTodo, SewingWorkbenchOverview } from '@/types/sewingOutsourcingWorkbench'
import fabric from '@/assets/purchase-workbench/shortage.png'
import truck from '@/assets/purchase-workbench/near-due.png'
import clipboard from '@/assets/purchase-workbench/unstarted.png'
import calendarBox from '@/assets/purchase-workbench/due-today.png'
import lateBox from '@/assets/purchase-workbench/overdue.png'
import PurchaseWorkbenchMessages from './PurchaseWorkbenchMessages.vue'
import SewingWorkbenchActivity from './SewingWorkbenchActivity.vue'
import SewingWorkbenchItems from './SewingWorkbenchItems.vue'

const todos: { key: SewingTodo; title: string; hint: string; icon: string; color: string }[] = [
  { key: 'send', title: '待发料', hint: '含未发和待补发', icon: fabric, color: '#265e8c' },
  { key: 'working', title: '在外待回', hint: '已发料或部分回货，待回齐', icon: truck, color: '#176d70' },
  { key: 'soon', title: '临近应回', hint: '明天起三天内', icon: clipboard, color: '#497393' },
  { key: 'today', title: '今天应回', hint: '预计今天回货', icon: calendarBox, color: '#92601b' },
  { key: 'overdue', title: '逾期未回齐', hint: '已过预计回货日', icon: lateBox, color: '#a84843' },
]
const follow: { key: SewingFollow; title: string }[] = [
  { key: 'late_send', title: '已过计划发料日' },
  { key: 'today_send', title: '今天计划发料' },
  { key: 'partial', title: '部分已发，仍需补发' },
]
const auth = useAuthStore()
const summary = ref<SewingWorkbenchOverview | null>(null)
const error = ref(''), reload = ref(0)
const selection = ref<{ key: SewingQueue; title: string; date?: string } | null>(null)
watch([() => auth.identityGeneration, reload], async (_, __, cleanup) => {
  const request = new AbortController()
  cleanup(() => request.abort())
  summary.value = null
  selection.value = null
  error.value = ''
  try {
    const data = await getSewingOverview(request.signal)
    if (!request.signal.aborted) summary.value = data
  } catch (cause) {
    if (!request.signal.aborted) error.value = workbenchErrorMessage(cause, '加载车缝外协工作台')
  }
}, { immediate: true })

const dateFormat = new Intl.DateTimeFormat('zh-CN', {
  year: 'numeric', month: 'long', day: 'numeric', weekday: 'long', timeZone: 'Asia/Shanghai',
})
const shortDate = (day: string) => day.slice(5).replace('-', '/')
const week = computed(() => summary.value?.upcoming ?? [])
const tallest = computed(() => Math.max(1, ...week.value.map(day => day.count)))
const weekTotal = computed(() => week.value.reduce((total, day) => total + day.count, 0))
</script>

<template>
  <main class="sewing-workbench">
    <header class="page-heading"><h1>车缝外协工作台</h1><time v-if="summary" :datetime="summary.as_of">{{ dateFormat.format(new Date(summary.as_of)) }}</time></header>
    <div v-if="error" role="alert" class="glass load-state">{{ error }} <ElButton @click="reload++">重新加载</ElButton></div>
    <p v-else-if="!summary" role="status" class="glass load-state">正在加载车缝外协工作台…</p>
    <template v-else>
      <section class="glass todo-panel">
        <h2><Tickets />我的待办</h2>
        <div class="todos">
          <button v-for="todo in todos" :key="todo.key" type="button" class="todo" @click="selection = todo">
            <img :src="todo.icon" alt=""><span><span class="todo-title">{{ todo.title }}</span><strong :style="{ color: todo.color }">{{ summary.counts[todo.key] }}</strong><small>张</small><small class="hint">{{ todo.hint }}</small></span><ArrowRight class="chevron" />
          </button>
        </div>
      </section>
      <SewingWorkbenchActivity>
        <section class="glass panel upcoming">
          <header class="panel-head"><h2><Calendar />未来七天应回</h2><small v-if="week.length">{{ shortDate(week[0]!.date) }} — {{ shortDate(week[week.length - 1]!.date) }}</small></header>
          <p class="subtitle">按预计回货日看仍有部位未回齐的外协单</p>
          <div class="week-bars">
            <button v-for="day in week" :key="day.date" type="button" :aria-label="`${day.date} 应回 ${day.count} 张`" @click="selection = { key: 'upcoming', title: shortDate(day.date) + ' 应回', date: day.date }">
              <span class="bar-frame"><b>{{ day.count }}</b><i :style="{ height: day.count * 80 / tallest + '%' }" /></span>
              <span>{{ day.date === summary.as_of ? '今天' : shortDate(day.date) }}</span>
            </button>
          </div>
          <footer class="totals"><span>七天内需跟进</span><b>{{ weekTotal }} 张总单</b></footer>
        </section>
        <aside class="rail">
          <section class="glass sidepanel"><h2><Flag />发料跟进</h2>
            <button v-for="item in follow" :key="item.key" class="follow-row" type="button" @click="selection = item">
              <span>{{ item.title }}</span><b>{{ summary.counts[item.key] }}</b><small>张</small><ArrowRight class="chevron" />
            </button>
          </section>
          <PurchaseWorkbenchMessages />
        </aside>
      </SewingWorkbenchActivity>
      <SewingWorkbenchItems v-if="selection" :key="selection.key + (selection.date ?? '')" :category="selection.key" :title="selection.title" :date="selection.date" :as-of="summary.as_of" @close="selection = null" />
    </template>
  </main>
</template>

<style lang="scss" src="./sewingWorkbench.scss"></style>
