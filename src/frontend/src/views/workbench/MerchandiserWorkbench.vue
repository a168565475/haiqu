<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ArrowRight, Calendar, Flag, Tickets } from '@element-plus/icons-vue'
import { getMerchandiserOverview } from '@/api/merchandiserWorkbench'
import { useAuthStore } from '@/stores/auth'
import { workbenchErrorMessage } from '@/utils/workbench'
import type { MerchandiserFollow, MerchandiserOverview, MerchandiserSelection, MerchandiserTodo } from '@/types/merchandiserWorkbench'
import clipboard from '@/assets/purchase-workbench/unstarted.png'
import calendarBox from '@/assets/purchase-workbench/due-today.png'
import lateBox from '@/assets/purchase-workbench/overdue.png'
import fabric from '@/assets/purchase-workbench/shortage.png'
import truck from '@/assets/purchase-workbench/near-due.png'
import PurchaseWorkbenchMessages from './PurchaseWorkbenchMessages.vue'
import MerchandiserWorkbenchActivity from './MerchandiserWorkbenchActivity.vue'
import MerchandiserWorkbenchItems from './MerchandiserWorkbenchItems.vue'

const todos: { category: MerchandiserTodo; title: string; unit: string; hint: string; icon: string; color: string }[] = [
  { category: 'need', title: '包材待下单', unit: '项', hint: '需求未买足的材料', icon: clipboard, color: '#285e88' },
  { category: 'soon', title: '包材临近到货', unit: '行', hint: '今天至未来三天', icon: calendarBox, color: '#80651f' },
  { category: 'late', title: '包材逾期未到齐', unit: '行', hint: '已过预计交期，仍有欠数', icon: lateBox, color: '#a04741' },
  { category: 'owing', title: '丝印厂待交', unit: '张', hint: '已发裁片尚在丝印厂', icon: fabric, color: '#176d70' },
  { category: 'past', title: '生产任务已过交期', unit: '张', hint: '交期已过，任务未完成', icon: truck, color: '#925146' },
]
const follow: { category: MerchandiserFollow; title: string; detailTitle?: string; unit: string }[] = [
  { category: 'unsent', title: '丝印待发', unit: '张' },
  { category: 'returns', title: '包材退货待处理', unit: '行' },
  { category: 'ordinary', title: '普通采购到货异常', detailTitle: '普通采购逾期未到齐', unit: '行' },
]
const auth = useAuthStore()
const summary = ref<MerchandiserOverview | null>(null), error = ref(''), retry = ref(0)
const selection = ref<MerchandiserSelection | null>(null)
watch([() => auth.identityGeneration, retry], async (_, __, cleanup) => {
  const request = new AbortController()
  cleanup(() => request.abort())
  summary.value = null
  selection.value = null
  error.value = ''
  try {
    const data = await getMerchandiserOverview(request.signal)
    if (!request.signal.aborted) summary.value = data
  } catch (cause) {
    if (!request.signal.aborted) error.value = workbenchErrorMessage(cause, '加载跟单工作台')
  }
}, { immediate: true })

const dateFormat = new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: 'long', day: 'numeric', weekday: 'long', timeZone: 'Asia/Shanghai' })
const shortDate = (day: string) => day.slice(5).replace('-', '/')
const week = computed(() => summary.value?.upcoming ?? [])
const tallest = computed(() => Math.max(1, ...week.value.map(day => day.count)))
const weekTotal = computed(() => week.value.reduce((total, day) => total + day.count, 0))
</script>

<template>
  <main class="sewing-workbench merchandiser-workbench">
    <header class="page-heading">
      <h1>跟单工作台<small>本人跟进的生产任务</small></h1>
      <time v-if="summary" :datetime="summary.as_of">{{ dateFormat.format(new Date(summary.as_of)) }}</time>
    </header>
    <p v-if="error" role="alert" class="glass load-state">{{ error }} <ElButton @click="retry++">重新加载</ElButton></p>
    <p v-else-if="!summary" role="status" class="glass load-state">正在加载跟单工作台…</p>
    <template v-else>
      <section class="glass todo-panel">
        <h2><Tickets />我的待办</h2>
        <div class="todos">
          <button v-for="item in todos" :key="item.category" type="button" class="todo" :disabled="summary.counts[item.category] === null" @click="selection = item">
            <img :src="item.icon" alt=""><span><span class="todo-title">{{ item.title }}</span>
              <strong :style="{ color: item.color }">{{ summary.counts[item.category] ?? '—' }}</strong><small v-if="summary.counts[item.category] !== null">{{ item.unit }}</small>
              <small class="hint">{{ summary.counts[item.category] === null ? '无查看权限' : item.hint }}</small>
            </span><ArrowRight class="chevron" />
          </button>
        </div>
      </section>
      <MerchandiserWorkbenchActivity :key="auth.identityGeneration" @select="selection = $event">
        <template #calendar>
          <section class="glass panel upcoming">
            <header class="panel-head"><h2><Calendar />未来七天任务交期</h2><small v-if="week.length">{{ shortDate(week[0]!.date) }} — {{ shortDate(week[week.length - 1]!.date) }}</small></header>
            <p class="subtitle">按任务交期查看仍需跟进的生产任务</p>
            <div class="week-bars">
              <button v-for="day in week" :key="day.date" type="button" :aria-label="`${day.date} 交期任务 ${day.count} 张`" @click="selection = { category: 'day', title: shortDate(day.date) + ' 交期任务', date: day.date, unit: '张任务' }">
                <span class="bar-frame"><b>{{ day.count }}</b><i :style="{ height: day.count * 80 / tallest + '%' }" /></span>
                <span>{{ day.date === summary.as_of ? '今天' : shortDate(day.date) }}</span>
              </button>
            </div>
            <footer class="totals"><span>七天内到期</span><b>{{ weekTotal }} 张任务</b></footer>
          </section>
        </template>
        <template #rail>
          <aside class="rail">
            <section class="glass sidepanel"><h2><Flag />需要跟进</h2>
              <button v-for="item in follow" :key="item.category" class="follow-row" type="button" :title="item.detailTitle" :disabled="summary.counts[item.category] === null" @click="selection = { ...item, title: item.detailTitle ?? item.title }">
                <span>{{ item.title }}</span><b>{{ summary.counts[item.category] ?? '—' }}</b>
                <small>{{ summary.counts[item.category] === null ? '无查看权限' : item.unit }}</small><ArrowRight class="chevron" />
              </button>
            </section>
            <PurchaseWorkbenchMessages />
          </aside>
        </template>
      </MerchandiserWorkbenchActivity>
      <MerchandiserWorkbenchItems v-if="selection" :key="[selection.category, selection.date, selection.period, selection.supplier_id].join('/')" :selection="selection" @close="selection = null" />
    </template>
  </main>
</template>

<style lang="scss" src="./sewingWorkbench.scss"></style>
<style scoped>
.page-heading h1 small { margin-left: 15px; font-size: 13px; font-weight: 400; }
.merchandiser-workbench button:disabled { cursor: default; }
.merchandiser-workbench button:disabled .chevron { visibility: hidden; }
</style>
