<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import axios from 'axios'
import { fetchFinanceSourceTasks, fetchFinanceStatements } from '@/api/financeStatements'
import type { FinanceSourceTask, FinanceStatement } from '@/types/financeStatements'

const props = defineProps<{
  mode: 'task' | 'statement'
  taskId?: string
  selectedTask?: Pick<FinanceSourceTask, 'id' | 'task_number' | 'salesperson'>
  selectedStatement?: FinanceStatement | null
  disabled?: boolean
}>()
const emit = defineEmits<{ task: [value: FinanceSourceTask]; statement: [value: FinanceStatement] }>()
const tasks = ref<FinanceSourceTask[]>([]), statements = ref<FinanceStatement[]>([])
const query = ref(''), page = ref(0), totalPages = ref(0), loading = ref(false), error = ref(''), open = ref(false)
const current = computed(() => props.mode === 'task' ? props.selectedTask : props.selectedStatement)
const selectedId = ref(current.value?.id)
function taskLabel(task: Pick<FinanceSourceTask, 'task_number' | 'salesperson'>) {
  return `${task.task_number} · ${task.salesperson.name || '—'}`
}
const options = computed(() => {
  const rows = props.mode === 'task'
    ? tasks.value.map(row => ({ id: row.id, label: taskLabel(row) }))
    : statements.value.map(row => ({ id: row.id, label: row.number }))
  if (current.value && !rows.some(row => row.id === current.value?.id)) {
    rows.unshift({ id: current.value.id, label: props.mode === 'task' ? taskLabel(props.selectedTask!) : props.selectedStatement!.number })
  }
  return rows
})
let generation = 0
let controller: AbortController | undefined
function cancel() { ++generation; controller?.abort(); loading.value = false }
async function load(nextPage = 1) {
  if (!open.value || props.disabled || (props.mode === 'statement' && !props.taskId)) return
  const request = ++generation; controller?.abort(); controller = new AbortController()
  loading.value = true; error.value = ''
  try {
    const params = { q: query.value, page: nextPage, page_size: 20 }
    if (props.mode === 'task') {
      const result = await fetchFinanceSourceTasks({ ...params, mode: 'receipt' }, controller.signal)
      if (request !== generation) return
      tasks.value = nextPage === 1 ? result.data : [...new Map([...tasks.value, ...result.data].map(row => [row.id, row])).values()]
      page.value = result.meta.page; totalPages.value = result.meta.total_pages
    } else {
      const result = await fetchFinanceStatements({ ...params, task_id: props.taskId, status: 'ACTIVE' }, controller.signal)
      if (request !== generation) return
      statements.value = nextPage === 1 ? result.data : [...new Map([...statements.value, ...result.data].map(row => [row.id, row])).values()]
      page.value = result.meta.page; totalPages.value = result.meta.total_pages
    }
  } catch (failure) {
    if (request !== generation || axios.isCancel(failure)) return
    error.value = axios.isAxiosError(failure) ? failure.response?.data?.error?.message || '来源加载失败，请重试。' : '来源加载失败，请重试。'
  } finally { if (request === generation) loading.value = false }
}
function search(value: string) {
  query.value = value.trim(); page.value = 0; totalPages.value = 0; tasks.value = []; statements.value = []
  void load()
}
function visibility(visible: boolean) { open.value = visible; if (visible) search(''); else cancel() }
async function choose(id: string) {
  if (!props.disabled && !loading.value && !error.value) {
    if (props.mode === 'task') {
      const value = tasks.value.find(row => row.id === id)
      if (value) emit('task', value)
    } else {
      const value = statements.value.find(row => row.id === id)
      if (value) emit('statement', value)
    }
  }
  // 来源由父表单确认后回填；取消更换时仍显示原值。
  await nextTick(); selectedId.value = current.value?.id
}
watch(() => current.value?.id, id => { selectedId.value = id })
watch(() => props.taskId, () => { cancel(); search('') })
watch(() => props.disabled, value => { if (value) cancel() })
onBeforeUnmount(cancel)
</script>

<template>
  <el-select v-model="selectedId" filterable remote remote-show-suffix :remote-method="search" :loading="loading" :disabled="disabled || (mode === 'statement' && !taskId)" :placeholder="mode === 'task' ? '搜索生产任务单' : '搜索该任务的有效对账单'" :aria-label="mode === 'task' ? '生产任务单' : '所属对账单'" popper-class="finance-receipt-popper" @visible-change="visibility" @change="choose">
    <el-option v-for="row in options" :key="row.id" :label="row.label" :value="row.id" :disabled="loading || !!error"/>
    <template #empty><div class="source-select-state">{{ loading ? '正在加载…' : error || (mode === 'task' ? '暂无包含有效对账单的任务' : '该任务暂无匹配的有效对账单') }}</div></template>
    <template #footer><div v-if="error || page < totalPages" class="source-select-footer"><span v-if="error" role="alert">{{ error }}</span><el-button link :loading="loading" @click.stop="load(page + 1)">{{ error ? '重试' : '加载更多' }}</el-button></div></template>
  </el-select>
</template>

<style scoped>
.source-select-state { padding: 12px; color: var(--erp-color-text-secondary); text-align: center; }
.source-select-footer { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; font-size: 12px; }
</style>
