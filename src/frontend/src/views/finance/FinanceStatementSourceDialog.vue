<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import axios from 'axios'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import { fetchFinanceSourceTasks } from '@/api/financeStatements'
import type { FinanceSourceTask } from '@/types/financeStatements'

const props = defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [boolean]; task: [FinanceSourceTask] }>()
const rows = ref<FinanceSourceTask[]>([])
const selectedTask = ref<FinanceSourceTask>()
const page = ref(1), total = ref(0), search = ref(''), applied = ref(''), error = ref('')
const loading = ref(false), forbidden = ref(false)
let request = 0
let controller: AbortController | undefined

async function load() {
  const token = ++request
  controller?.abort(); controller = new AbortController()
  loading.value = true; error.value = ''; forbidden.value = false
  try {
    const response = await fetchFinanceSourceTasks({ q: applied.value, page: page.value, page_size: 20 }, controller.signal)
    if (token !== request) return
    rows.value = response.data; total.value = response.meta.total; page.value = response.meta.page
  } catch (failure) {
    if (token !== request || axios.isCancel(failure)) return
    forbidden.value = axios.isAxiosError(failure) && [401, 403].includes(failure.response?.status || 0)
    if (forbidden.value) { rows.value = []; selectedTask.value = undefined }
    error.value = axios.isAxiosError(failure) ? failure.response?.data?.error?.message || '加载失败，请重试。' : '加载失败，请重试。'
  } finally { if (token === request) loading.value = false }
}
function confirm() {
  if (loading.value || error.value || forbidden.value || !selectedTask.value) return
  emit('task', selectedTask.value)
  emit('update:modelValue', false)
}
watch(() => props.modelValue, open => {
  ++request; controller?.abort()
  if (!open) return
  rows.value = []; total.value = 0; selectedTask.value = undefined
  page.value = 1; search.value = ''; applied.value = ''
  void load()
})
onBeforeUnmount(() => { ++request; controller?.abort() })
</script>

<template>
  <AppWindowDialog :model-value="modelValue" title="选择生产任务单" :width="1080" :min-width="280" :minimizable="false" destroy-on-close modal-class="finance-statement-overlay" @update:model-value="emit('update:modelValue', $event)">
    <div class="source-dialog">
      <div class="source-search"><el-input v-model="search" aria-label="搜索生产任务" placeholder="任务号 / 业务员姓名" clearable @keyup.enter="applied = search; page = 1; load()"/><el-button @click="applied = search; page = 1; load()">查询</el-button></div>
      <el-alert v-if="error" :title="error" type="error" :closable="false"><el-button @click="load">重试</el-button></el-alert>
      <div v-loading="loading" class="embedded-table erp-glass-list" :aria-busy="loading"><div class="erp-list-table-frame">
        <el-table :data="rows" row-key="id" border>
          <el-table-column label="选择" width="70"><template #default="{row}"><el-radio :model-value="selectedTask?.id" :value="row.id" :aria-label="`选择任务${row.task_number}`" @update:model-value="selectedTask = row"><span/></el-radio></template></el-table-column>
          <el-table-column prop="task_number" label="生产任务单" min-width="180"/>
          <el-table-column label="业务员" min-width="220"><template #default="{row}">{{row.salesperson.name}}</template></el-table-column>
          <el-table-column prop="source_order_date" label="来源日期" min-width="130"/>
          <el-table-column label="状态" min-width="100"><template #default="{row}">{{({READY:'已接单',IN_PRODUCTION:'生产中',PAUSED:'已暂停',COMPLETED:'已完成'} as Record<string,string>)[row.status]}}</template></el-table-column>
          <template #empty>{{loading ? '正在加载…' : error ? '来源尚未成功加载' : applied ? '没有匹配的可对账任务' : '暂无可对账生产任务'}}</template>
        </el-table>
      </div></div>
      <div v-if="total > 20" class="source-footer"><el-pagination v-model:current-page="page" :total="total" :page-size="20" hide-on-single-page layout="prev, pager, next" @current-change="load"/></div>
    </div>
    <template #footer><el-button @click="emit('update:modelValue', false)">取消</el-button><el-button type="primary" :disabled="loading || !!error || !selectedTask" @click="confirm">确认选择</el-button></template>
  </AppWindowDialog>
</template>

<style scoped>
.source-dialog { display: grid; gap: 16px; min-width: 0; }
.source-search { display: flex; gap: 12px; }.source-search .el-input { max-width: 400px; }
.source-footer { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; font-size: 12px; color: var(--erp-color-text-secondary); }
.source-footer .el-pagination { margin-left: auto; }
.embedded-table { min-height: 0; }.embedded-table .erp-list-table-frame { flex: none; border-radius: 8px; }
@media (prefers-reduced-motion: reduce) { .source-dialog, .source-dialog :deep(*) { animation: none !important; transition: none !important; } }
</style>
