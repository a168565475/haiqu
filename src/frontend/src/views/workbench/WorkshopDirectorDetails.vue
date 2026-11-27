<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { getDirectorActivity, getDirectorDetail, getDirectorItems } from '@/api/workshopDirectorWorkbench'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import type { DirectorActivity, DirectorDetail, DirectorJob, DirectorPage, DirectorSelection, DirectorWorkshop } from '@/types/workshopDirectorWorkbench'
import { workbenchErrorMessage } from '@/utils/workbench'
import { amount, countdown, deadlineLabel, dueTone, stageLabel, workshopName } from './WorkshopDirectorDisplay'
import WorkshopDirectorRecords from './WorkshopDirectorRecords.vue'

const props = defineProps<{ workshop: DirectorWorkshop; selection: DirectorSelection }>()
const emit = defineEmits<{ close: [] }>()
const page = ref(1), retry = ref(0), selectedJob = ref<string | null>(null)
const jobs = ref<DirectorPage<DirectorJob[]> | null>(null), records = ref<DirectorPage<DirectorActivity> | null>(null)
const detail = ref<DirectorDetail | null>(null), error = ref('')
const detailId = computed(() => selectedJob.value ?? (props.selection.kind === 'detail' ? props.selection.id : null))
const title = computed(() => detailId.value ? workshopName[props.workshop] + '产品计划明细' : props.selection.kind !== 'detail' ? props.selection.title : '')
const meta = computed(() => jobs.value?.meta ?? records.value?.meta)

watch([() => props.selection, detailId, page, retry], async ([selection, id, currentPage], _, cleanup) => {
  const request = new AbortController()
  cleanup(() => request.abort())
  detail.value = null
  jobs.value = null
  records.value = null
  error.value = ''
  try {
    if (id) {
      const data = await getDirectorDetail(props.workshop, id, request.signal)
      if (!request.signal.aborted) detail.value = data
    } else if (selection.kind === 'items') {
      const result = await getDirectorItems(props.workshop, selection.category, selection.date, currentPage, request.signal)
      if (!request.signal.aborted) jobs.value = result
    } else if (selection.kind === 'records') {
      const result = await getDirectorActivity(props.workshop, selection.period, currentPage, request.signal)
      if (!request.signal.aborted) records.value = result
    }
  } catch (cause) {
    if (!request.signal.aborted) error.value = workbenchErrorMessage(cause, '加载车间明细')
  }
}, { immediate: true })
</script>

<template>
  <AppWindowDialog :model-value="true" :title="title" :width="960" :min-width="300" :minimizable="false" @update:model-value="open => { if (!open) emit('close') }">
    <div class="director-dialog">
      <button v-if="selectedJob" class="action back" @click="selectedJob = null">‹ 返回{{ selection.kind === 'records' ? '记录' : '排程' }}列表</button>
      <p v-if="error" role="alert">{{ error }} <button class="action" @click="retry++">重试</button></p>
      <template v-else-if="detail">
        <header class="detail-head"><strong>{{ detail.job.task_number }}</strong><span>{{ stageLabel[detail.job.stage] }}</span></header>
        <h3>{{ detail.job.product_name }}</h3>
        <p class="detail-meta">排产单 {{ detail.job.schedule_number }}<template v-if="detail.job.craft_name"> · {{ detail.job.craft_name }}</template></p>
        <div class="detail-due"><span>{{ deadlineLabel[workshop] }} <b>{{ detail.job.due_date }}</b></span><b v-if="detail.job.stage !== 'completed'" :class="dueTone(detail.job.days_remaining)">{{ countdown(detail.job.days_remaining) }}</b></div>
        <p v-if="detail.job.quantity.reason" class="detail-meta">{{ detail.job.quantity.reason }}</p>
        <div v-if="detail.job.quantity.target !== null || detail.job.quantity.done !== null" class="detail-qty">
          <span>{{ workshop === 'ASSEMBLY' ? '产品需求' : '该工序要求' }} <b>{{ amount(detail.job.quantity.target, detail.job.quantity.unit) }}</b></span>
          <span>{{ workshop === 'ASSEMBLY' ? '累计成品入库' : '该工序已报' }} <b>{{ amount(detail.job.quantity.done, detail.job.quantity.unit) }}</b></span>
          <span>还差 <b>{{ amount(detail.job.quantity.remaining, detail.job.quantity.unit) }}</b></span>
        </div>
        <template v-if="detail.operations.length"><h4>工序进度</h4>
          <div class="director-table-scroll"><table><thead><tr><th>工序</th><th>要求</th><th>已报工</th><th>还差</th></tr></thead>
            <tbody><tr v-for="(op, index) in detail.operations" :key="index"><td>{{ op.name }}<small v-if="op.reason">{{ op.reason }}</small></td><td>{{ amount(op.target, op.unit) }}</td><td>{{ amount(op.done, op.unit) }}</td><td>{{ amount(op.remaining, op.unit) }}</td></tr></tbody>
          </table></div>
        </template>
        <h4>报工记录</h4><p v-if="detail.reports === null">当前账号没有查看报工记录的权限。</p><p v-else-if="!detail.reports.length">暂无报工记录。</p><WorkshopDirectorRecords v-else :records="detail.reports" />
        <template v-if="workshop === 'ASSEMBLY'"><h4>成品入库记录</h4>
          <p v-if="detail.receipts === null">当前账号没有查看成品入库记录的权限。</p><p v-else-if="!detail.receipts.length">暂无成品入库记录。</p><WorkshopDirectorRecords v-else :records="detail.receipts" />
        </template>
      </template>
      <template v-else-if="jobs"><p v-if="!jobs.data.length">当前没有符合条件的产品计划。</p>
        <div v-else class="director-table-scroll"><table><thead><tr><th>生产任务单号</th><th>产品</th><th>{{ deadlineLabel[workshop] }}</th><th>离排产期限</th><th>进度</th></tr></thead>
          <tbody><tr v-for="job in jobs.data" :key="job.id"><td><button class="action" @click="selectedJob = job.id">{{ job.task_number }}</button></td><td>{{ job.product_name }}<small>{{ job.craft_name }}</small></td>
            <td>{{ job.due_date }}</td><td :class="dueTone(job.days_remaining)">{{ countdown(job.days_remaining) }}</td><td>{{ stageLabel[job.stage] }}</td></tr></tbody></table>
        </div>
      </template>
      <template v-else-if="records"><p v-if="!records.data.available">当前账号没有查看记录的权限。</p><p v-else-if="!records.data.records.length">本期没有记录。</p>
        <WorkshopDirectorRecords v-else :records="records.data.records" drill @open="selectedJob = $event" /></template>
      <p v-else role="status">正在加载明细…</p>
      <footer v-if="meta && (jobs || records?.data.available)">共 {{ meta.total }} {{ jobs ? '项产品计划' : '条明细' }}
        <ElPagination v-if="meta.total_pages > 1" v-model:current-page="page" :total="meta.total" :page-size="meta.page_size" layout="prev, pager, next" background />
      </footer>
    </div>
  </AppWindowDialog>
</template>
