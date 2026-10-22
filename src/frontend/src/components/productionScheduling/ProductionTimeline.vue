<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { fetchProductionTimeline } from '@/api/productionTimeline'
import type { ProductionTimelineEvent } from '@/types/productionTimeline'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'

const props = defineProps<{ scheduleId: string; revision: number }>()
const router = useRouter()
const rows = ref<ProductionTimelineEvent[]>([])
const total = ref(0)
const page = ref(1)
const search = ref('')
const appliedSearch = ref('')
const loading = ref(false)
const error = ref('')
const selected = ref<ProductionTimelineEvent | null>(null)
const dialogOpen = ref(false)
const timelineBody = ref<HTMLElement | null>(null)
let sequence = 0
const dateFormat = new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })
function time(value: string) { return dateFormat.format(new Date(value)) }
async function load() {
  const current = ++sequence
  loading.value = true
  error.value = ''
  try {
    const result = await fetchProductionTimeline(props.scheduleId, { page: page.value, page_size: 20, search: appliedSearch.value })
    if (current !== sequence) return
    rows.value = result.data
    total.value = result.meta.total
    await nextTick()
    if (current === sequence && timelineBody.value) timelineBody.value.scrollTop = 0
  } catch {
    if (current === sequence) error.value = '事件记录加载失败，请重试。'
  } finally { if (current === sequence) loading.value = false }
}
function applySearch() { appliedSearch.value = search.value.trim(); page.value = 1; void load() }
function show(event: ProductionTimelineEvent) { selected.value = event; dialogOpen.value = true }
watch(() => [props.scheduleId, props.revision], () => {
  page.value = 1; rows.value = []; total.value = 0; selected.value = null; dialogOpen.value = false
  void load()
}, { immediate: true })
</script>

<template>
  <section class="schedule-section production-timeline" data-testid="production-timeline" :aria-busy="loading">
    <header><div><h2>生产事件记录 <small>按时间从早到晚</small></h2></div><div class="timeline-search">
      <ElInput v-model="search" clearable maxlength="100" placeholder="搜索事项、操作人、单号" aria-label="搜索生产事件" @keyup.enter="applySearch" @clear="applySearch" />
      <ElButton :loading="loading" @click="applySearch">查询</ElButton><ElButton :disabled="loading" @click="load">刷新</ElButton>
    </div></header>
    <ElAlert v-if="error" :title="error" type="error" :closable="false"><ElButton link @click="load">重试</ElButton></ElAlert>
    <div ref="timelineBody" v-loading="loading" class="timeline-body">
      <ol v-if="rows.length" class="timeline-list">
        <li v-for="event in rows" :key="event.id">
          <time :datetime="event.occurred_at">{{ time(event.occurred_at) }}</time>
          <span class="timeline-node" aria-hidden="true" />
          <div class="timeline-event"><strong>{{ event.title }}</strong><span>{{ event.document_number }}</span></div>
          <span class="timeline-actor">{{ event.actor_name }}</span>
          <ElButton link type="primary" :aria-label="`查看详情：${event.title} ${event.document_number}`" @click="show(event)">查看详情</ElButton>
        </li>
      </ol>
      <ElEmpty v-else-if="!loading && !error" :description="appliedSearch ? '没有匹配的事件记录' : '暂无可查看的事件记录'" :image-size="50" />
    </div>
    <footer><span>共 {{ total }} 条</span><ElPagination v-model:current-page="page" :page-size="20" :total="total" layout="prev, pager, next" :disabled="loading" @current-change="load" /></footer>
    <AppWindowDialog v-model="dialogOpen" title="生产事件详情" :width="660" :height="460" destroy-on-close>
      <template v-if="selected">
        <dl class="event-facts"><div><dt>操作事项</dt><dd>{{ selected.title }}</dd></div><div><dt>操作人</dt><dd>{{ selected.actor_name }}</dd></div><div><dt>操作时间</dt><dd>{{ time(selected.occurred_at) }}</dd></div><div><dt>关联单号</dt><dd>{{ selected.document_number || '—' }}</dd></div></dl>
        <div v-for="(change, index) in selected.changes" :key="index" class="event-change"><strong>{{ change.label }}</strong><span>{{ change.before || '未填写' }}</span><span>→</span><span>{{ change.after || '未填写' }}</span></div>
      </template>
      <template #footer><ElButton @click="dialogOpen = false">关闭</ElButton><ElButton v-if="selected?.detail_path" type="primary" @click="router.push(selected.detail_path)">打开关联单据</ElButton></template>
    </AppWindowDialog>
  </section>
</template>

<style scoped lang="scss">
.production-timeline { margin-top: 16px; }
.production-timeline > header, .production-timeline > footer { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 12px 16px; }
.production-timeline h2 { margin: 0; font-size: 16px; }
.production-timeline h2 small { margin-left: 12px; font-size: 12px; font-weight: 400; color: var(--erp-color-text-secondary); }
.timeline-search { display: flex; gap: 8px; }
.timeline-search .el-input { width: 250px; }
.timeline-body { min-height: 80px; max-height: 420px; overflow-y: auto; padding: 0 16px; }
.timeline-list { list-style: none; margin: 0; padding: 4px 0; }
.timeline-list li { display: grid; grid-template-columns: 155px 20px minmax(0, 1fr) 100px 74px; align-items: center; gap: 12px; min-height: 48px; font-size: 13px; }
.timeline-list time { color: var(--erp-color-text-secondary); font-size: 12px; font-variant-numeric: tabular-nums; }
.timeline-node { align-self: stretch; position: relative; }
.timeline-node::before { content: ''; position: absolute; top: 0; bottom: 0; left: 9px; width: 1px; background: var(--erp-table-grid); }
.timeline-node::after { content: ''; position: absolute; top: calc(50% - 4px); left: 5px; width: 9px; height: 9px; border-radius: 50%; background: var(--erp-color-brand); }
li:first-child .timeline-node::before { top: 50%; }
li:last-child .timeline-node::before { bottom: 50%; }
.timeline-event { display: flex; align-items: center; flex-wrap: wrap; gap: 12px; }
.timeline-event strong { font-weight: 500; }
.timeline-event > span { font-size: 12px; color: var(--erp-color-text-secondary); }
.timeline-actor { overflow-wrap: anywhere; }
.production-timeline > footer { font-size: 12px; color: var(--erp-color-text-secondary); }
.event-facts { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; margin: 0 0 20px; }
.event-facts dt { color: var(--erp-color-text-secondary); font-size: 12px; }
.event-facts dd { margin: 6px 0 0; font-size: 14px; }
.event-change { display: grid; grid-template-columns: 90px 1fr 20px 1fr; gap: 8px; padding: 10px 0; border-top: 1px solid var(--erp-table-grid); overflow-wrap: anywhere; font-size: 13px; }
@media(max-width: 800px) { .production-timeline > header { align-items: stretch; flex-direction: column; } .timeline-search .el-input { width: auto; flex: 1; } .timeline-list li { grid-template-columns: 125px 16px minmax(0, 1fr) 65px 65px; gap: 6px; } }
</style>
