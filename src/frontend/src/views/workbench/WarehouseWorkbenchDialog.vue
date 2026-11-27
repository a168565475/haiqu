<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ArrowRight } from '@element-plus/icons-vue'
import { getWarehouseActivity, getWarehouseDetail, getWarehouseItems } from '@/api/warehouseWorkbench'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import type { PageMeta } from '@/types/referenceData'
import type { WarehouseActivity, WarehouseDetail, WarehouseDrill, WarehouseRow } from '@/types/warehouseWorkbench'
import { workbenchErrorMessage } from '@/utils/workbench'
import { deadline, kindLabel, periodLabels, quantity, queueLabels, rowIdentity } from './WarehouseWorkbenchDisplay'

const props = defineProps<{ initial: WarehouseDrill; today: string }>()
const emit = defineEmits<{ close: [] }>()
const trail = ref<{ view: WarehouseDrill; page: number }[]>([{ view: props.initial, page: 1 }])
const current = computed(() => trail.value[trail.value.length - 1]!)
const view = computed(() => current.value.view)
const labels = computed(() => view.value.queue === 'all' ? null : queueLabels[view.value.queue])
const taskList = computed(() => view.value.type === 'items' && view.value.queue === 'issue' && !view.value.task)
const external = computed(() => view.value.queue === 'dispatch' || view.value.queue === 'returns')
const title = computed(() => {
  const v = view.value
  if (v.type === 'activity') return periodLabels[v.period] + (v.queue === 'all' ? '仓库收发' : queueLabels[v.queue].short) + '记录'
  if (v.type === 'items' && v.task) return v.task.number + ' · 待发料'
  return queueLabels[v.queue].title + (v.type === 'detail' ? '明细' : '')
})
const rows = ref<WarehouseRow[]>([]), records = ref<WarehouseActivity | null>(null), detail = ref<WarehouseDetail | null>(null)
const meta = ref<PageMeta | null>(null), error = ref(''), loading = ref(false), retry = ref(0)

function open(next: WarehouseDrill) {
  trail.value.push({ view: next, page: 1 })
}
function openRow(row: WarehouseRow) {
  const v = view.value
  if (v.type !== 'items') return
  if (taskList.value) open({ type: 'items', queue: v.queue, task: { id: row.id, number: row.task_number } })
  else open({ type: 'detail', queue: v.queue, kind: row.kind, id: row.id })
}
watch([view, () => current.value.page, retry], async ([target, page], _, cleanup) => {
  const request = new AbortController()
  cleanup(() => request.abort())
  rows.value = []
  records.value = null
  detail.value = null
  error.value = ''
  meta.value = null
  loading.value = true
  try {
    if (target.type === 'detail') {
      const data = await getWarehouseDetail({ queue: target.queue, kind: target.kind, id: target.id }, request.signal)
      if (!request.signal.aborted) detail.value = data
    } else if (target.type === 'activity') {
      const response = await getWarehouseActivity(target.period, target.queue, page, request.signal)
      if (!request.signal.aborted) { records.value = response.data; meta.value = response.meta }
    } else {
      const response = await getWarehouseItems(target.queue, target.task?.id, page, request.signal)
      if (!request.signal.aborted) { rows.value = response.data; meta.value = response.meta }
    }
  } catch (cause) {
    if (!request.signal.aborted) error.value = workbenchErrorMessage(cause, '加载仓库单据')
  } finally {
    if (!request.signal.aborted) loading.value = false
  }
}, { immediate: true })
</script>

<template>
  <AppWindowDialog :model-value="true" :title="title" :width="1130" :min-width="300" :minimizable="false"
    @update:model-value="value => { if (!value) emit('close') }">
    <div class="warehouse-dialog">
      <button v-if="trail.length > 1" type="button" class="action back" @click="trail.pop()">‹ 返回上一级</button>
      <p v-if="error" role="alert">{{ error }} <button type="button" class="action" @click="retry++">重试</button></p>
      <p v-else-if="loading" role="status">正在加载单据…</p>
      <template v-else-if="detail && labels && view.type === 'detail'">
        <strong class="file-id">{{ rowIdentity(detail.row) }}</strong><h3 v-if="detail.row.product">{{ detail.row.product }}</h3>
        <div class="file-meta">
          <span>{{ labels.number }}<b>{{ detail.row.number || '—' }}</b></span>
          <span>{{ labels.party }}<b>{{ detail.row.party || '—' }}</b></span>
          <span>{{ labels.date }}<b>{{ detail.row.date ?? '未设置' }}</b></span>
          <span>当前状态<b>{{ detail.row.status }}</b></span>
        </div>
        <p v-if="external" class="note">{{ [kindLabel(detail.row), deadline(view.queue, detail.row.date, today), view.queue === 'returns' ? '按应回仓的加工品核对' : '按应发物料核对'].filter(Boolean).join(' · ') }}</p>
        <p v-else-if="kindLabel(detail.row)" class="note">{{ kindLabel(detail.row) }}</p>
        <div v-if="detail.lines.length" class="table-scroll"><table><thead><tr><th>{{ view.queue === 'returns' ? '应收加工品' : '物品明细' }}</th>
          <th class="amount">{{ labels.required }}</th><th class="amount">{{ labels.done }}</th><th class="amount">{{ labels.remaining }}</th>
        </tr></thead><tbody><tr v-for="(line, index) in detail.lines" :key="index"><td>{{ line.name }}
          <small v-if="view.queue === 'purchase' && (line.party || line.date)">{{ [line.party, line.date && ('预计到货 ' + line.date)].filter(Boolean).join(' · ') }}</small>
          <small v-if="view.queue === 'returns' && line.basis_label">{{ line.basis_label }}</small></td>
          <td class="amount">{{ quantity(line.required, line.unit) }}</td><td class="amount">{{ quantity(line.done, line.unit) }}</td>
          <td class="amount"><strong>{{ quantity(line.remaining, line.unit) }}</strong></td></tr></tbody></table>
        </div>
        <p v-else class="note">这张单据暂无可查看的物品明细。</p>
        <div v-if="detail.related" class="related"><span>这张外发单还有{{ detail.related.queue === 'dispatch' ? '材料待发' : '加工品待收回' }}。</span>
          <button type="button" class="action" @click="open({ type: 'detail', ...detail.related })">查看同单{{ detail.related.queue === 'dispatch' ? '发出' : '回货' }}明细 ›</button></div>
        <template v-if="external || detail.movements.length">
          <h4>本单仓库收发记录</h4><p v-if="!detail.movements.length" class="note">暂无收发记录。</p>
          <div v-for="(record, index) in detail.movements" :key="index" class="movement"><time>{{ record.date ?? '—' }}</time>
            <b>{{ record.action }}</b><span>{{ record.description }}<small v-if="record.number">{{ record.number }}</small></span></div>
        </template>
      </template>
      <template v-else-if="view.type === 'items' && labels">
        <p v-if="!rows.length" class="note">当前没有待处理的{{ taskList ? '生产任务' : '单据' }}。</p>
        <div v-else class="table-scroll"><table><thead><tr><th>生产任务单号</th><th>{{ taskList ? '产品' : labels.number }}</th>
          <th>{{ labels.party }}</th><th>{{ taskList ? '最早提交' : labels.date }}</th><th>{{ taskList ? '待审核领料单' : '单据状态' }}</th><th aria-label="查看明细" /></tr></thead>
          <tbody><tr v-for="row in rows" :key="row.kind + row.id" class="open-row" @click="openRow(row)">
            <td><b>{{ row.task_number || '—' }}</b><small v-if="!taskList">{{ row.product }}</small></td>
            <td>{{ taskList ? row.product || '—' : row.number }}<small v-if="!taskList && kindLabel(row)">{{ kindLabel(row) }}</small></td>
            <td>{{ row.party || '—' }}</td><td>{{ row.date ?? '未设置' }}</td><td>{{ taskList ? row.document_count + ' 张' : row.status }}</td>
            <td><button type="button" class="row-link" :aria-label="'查看' + rowIdentity(row)" @click.stop="openRow(row)"><ArrowRight /></button></td>
          </tr></tbody></table></div>
      </template>
      <template v-else-if="records">
        <p class="note">{{ records.start_date }} 至 {{ records.end_date }}</p>
        <p v-if="!records.records.length" class="note">本期暂无收发记录。</p>
        <div v-else class="table-scroll"><table><thead><tr><th>生产任务单号</th><th>来源单号</th><th>车间 / 往来单位</th><th>办理日期</th><th>业务类型</th><th>收发明细</th></tr></thead>
          <tbody><tr v-for="record in records.records" :key="record.queue + record.kind + record.id">
            <td><b>{{ record.task_number || '—' }}</b></td><td>{{ record.number || '—' }}</td><td>{{ record.party || '—' }}</td>
            <td>{{ record.date }}</td><td>{{ queueLabels[record.queue].short }}</td><td>{{ record.description || '—' }}</td>
          </tr></tbody></table></div>
      </template>
      <footer v-if="meta && !loading && !error">共 {{ meta.total }} {{ view.type === 'activity' ? '笔记录' : taskList ? '个任务' : '张单据' }}
        <ElPagination v-if="meta.total_pages > 1" :current-page="current.page" :total="meta.total" :page-size="meta.page_size"
          layout="prev, pager, next" @update:current-page="current.page = $event" />
      </footer>
    </div>
  </AppWindowDialog>
</template>
