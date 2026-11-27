<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ArrowRight, Flag, OfficeBuilding, Sort } from '@element-plus/icons-vue'
import { getWarehouseOverview } from '@/api/warehouseWorkbench'
import { useAuthStore } from '@/stores/auth'
import type { WarehouseDrill, WarehouseOverview, WarehouseQueue, WarehouseRow } from '@/types/warehouseWorkbench'
import { workbenchErrorMessage } from '@/utils/workbench'
import PurchaseWorkbenchMessages from './PurchaseWorkbenchMessages.vue'
import WarehouseWorkbenchActivity from './WarehouseWorkbenchActivity.vue'
import WarehouseWorkbenchDialog from './WarehouseWorkbenchDialog.vue'
import { deadline, queueLabels, queueSubtitle, rowIdentity } from './WarehouseWorkbenchDisplay'

const auth = useAuthStore()
const result = ref<WarehouseOverview | null>(null), error = ref(''), retry = ref(0)
const drill = ref<WarehouseDrill | null>(null)
const groups = [
  { title: '入库与生产发料', icon: OfficeBuilding, queues: ['inbound', 'purchase', 'issue'] },
  { title: '外发收发', icon: Sort, queues: ['dispatch', 'returns'] },
] as const
const visibleGroups = computed(() => {
  const board = result.value
  if (!board) return []
  return groups.map(group => ({
    ...group,
    cards: group.queues.map(queue => ({ queue, card: board.queues[queue], label: queueLabels[queue] })),
  }))
})
const headingDate = new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: 'long', day: 'numeric', weekday: 'long', timeZone: 'Asia/Shanghai' })

watch([() => auth.identityGeneration, retry], async (_, __, cleanup) => {
  const request = new AbortController()
  cleanup(() => request.abort())
  result.value = null
  error.value = ''
  drill.value = null
  try {
    const data = await getWarehouseOverview(request.signal)
    if (!request.signal.aborted) result.value = data
  } catch (cause) {
    if (!request.signal.aborted) error.value = workbenchErrorMessage(cause, '加载仓库工作台')
  }
}, { immediate: true })

function openPriority(queue: WarehouseQueue, row: WarehouseRow) {
  drill.value = row.kind === 'task'
    ? { type: 'items', queue, task: { id: row.id, number: row.task_number } }
    : { type: 'detail', queue, kind: row.kind, id: row.id }
}
</script>

<template>
  <main class="warehouse-workbench">
    <header class="warehouse-mast"><h1>仓库工作台</h1>
      <time v-if="result" :datetime="result.as_of">{{ headingDate.format(new Date(result.as_of)) }}</time>
    </header>
    <p v-if="error" class="panel state" role="alert">{{ error }} <button class="action" @click="retry++">重试</button></p>
    <p v-else-if="!result" class="panel state" role="status">正在加载仓库收发待办…</p>
    <template v-else>
      <div class="warehouse-groups">
        <section v-for="group in visibleGroups" :key="group.title" class="queue-group">
          <h2><component :is="group.icon" />{{ group.title }}</h2>
          <div class="queue-cards">
            <button v-for="{ queue, card, label } in group.cards" :key="queue" class="queue-card" :data-queue="queue"
              :disabled="!card.available" @click="drill = { type: 'items', queue }">
              <strong class="queue-title">{{ label.title }}</strong>
              <span class="queue-figure"><span class="queue-number">{{ card.count ?? '—' }}<small>{{ queue === 'issue' ? '个任务' : '张' }}</small></span>
                <img :src="label.image" alt="" />
              </span>
              <span class="queue-subtitle">
                <template v-if="queue === 'returns' && card.available"><b :class="{ overdue: (card.breakdown.overdue ?? 0) > 0 }">{{ card.breakdown.overdue ?? 0 }} 张逾期</b> · {{ card.breakdown.today ?? 0 }} 张今天应回</template>
                <template v-else>{{ queueSubtitle(queue, card) }}</template>
              </span>
              <span class="queue-preview" v-if="card.preview">
                <b>{{ rowIdentity(card.preview) }}</b>
                <span>{{ [card.preview.product, queue === 'issue' && card.preview.document_count != null ? '有 ' + card.preview.document_count + ' 张领料单' : card.preview.party].filter(Boolean).join(' · ') }}</span>
              </span>
              <span v-else class="queue-preview empty">{{ card.available ? '暂无待办单据' : '单据不可见' }}</span>
              <span class="queue-open">{{ label.link }}<ArrowRight /></span>
            </button>
          </div>
        </section>
      </div>
      <div class="warehouse-lower">
        <section class="panel"><header><h2><Flag />优先跟进</h2><small>按约定日期</small></header>
          <div class="priority-list">
            <button v-for="row in result.priority" :key="row.queue + row.kind + row.id" class="priority-row" @click="openPriority(row.queue, row)">
              <span class="date-tag" :class="{ overdue: row.date && row.date < result.as_of, today: row.date === result.as_of }">{{ deadline(row.queue, row.date, result.as_of) }}</span>
              <span class="priority-doc"><strong>{{ queueLabels[row.queue].title }}<template v-if="row.party"> · {{ row.party }}</template></strong>
                <small><b>{{ row.task_number }}</b> {{ row.number }}</small></span><ArrowRight />
            </button>
            <p v-if="!result.priority.length" class="empty">暂无需要跟进的到期单据。</p>
          </div>
        </section>
        <WarehouseWorkbenchActivity @select="drill = $event" />
        <PurchaseWorkbenchMessages class="panel" />
      </div>
      <WarehouseWorkbenchDialog v-if="drill" :initial="drill" :today="result.as_of" @close="drill = null" />
    </template>
  </main>
</template>

<style lang="scss" src="./WarehouseWorkbench.scss"></style>
