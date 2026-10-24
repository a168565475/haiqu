<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import axios from 'axios'
import { fetchFinanceSourceTasks } from '@/api/financeStatements'
import type { FinanceSourceTask } from '@/types/financeStatements'

const props = defineProps<{ modelValue?: FinanceSourceTask; disabled?: boolean }>()
const emit = defineEmits<{ task: [FinanceSourceTask] }>()
const options = ref<FinanceSourceTask[]>([]), selectedId = ref(props.modelValue?.id)
const loading = ref(false), error = ref(''), query = ref(''), page = ref(0), totalPages = ref(0), open = ref(false)
const visibleOptions = computed(() => props.modelValue && !options.value.some(row => row.id === props.modelValue?.id)
  ? [props.modelValue, ...options.value] : options.value)
let request = 0
let controller: AbortController | undefined
async function load(nextPage = 1) {
  const token = ++request
  controller?.abort(); controller = new AbortController(); loading.value = true; error.value = ''
  try {
    const response = await fetchFinanceSourceTasks({ q: query.value, page: nextPage, page_size: 20 }, controller.signal)
    if (token !== request || !open.value) return
    options.value = nextPage === 1 ? response.data : [...new Map([...options.value, ...response.data].map(row => [row.id, row])).values()]
    page.value = response.meta.page; totalPages.value = response.meta.total_pages
  } catch (failure) {
    if (token !== request || axios.isCancel(failure)) return
    error.value = axios.isAxiosError(failure) ? failure.response?.data?.error?.message || '任务加载失败，请重试。' : '任务加载失败，请重试。'
  } finally { if (token === request) loading.value = false }
}
function search(value: string) { query.value = value.trim(); page.value = 0; totalPages.value = 0; options.value = []; void load() }
function visibility(visible: boolean) {
  open.value = visible
  if (visible) search('')
  else { ++request; controller?.abort(); loading.value = false }
}
async function choose(id: string) {
  if (props.disabled || loading.value || error.value) return
  const value = visibleOptions.value.find(row => row.id === id)
  if (!value) return
  emit('task', value)
  // 父表单可能仍在确认更换来源；取消时保持原任务，不由下拉擅自回写。
  await nextTick(); selectedId.value = props.modelValue?.id
}
watch(() => props.modelValue?.id, id => { selectedId.value = id })
onBeforeUnmount(() => { ++request; controller?.abort() })
</script>

<template>
  <el-select v-model="selectedId" filterable remote remote-show-suffix :remote-method="search" :loading="loading" :disabled="disabled" placeholder="搜索生产任务单" aria-label="生产任务单" @visible-change="visibility" @change="choose">
    <el-option v-for="row in visibleOptions" :key="row.id" :label="row.task_number" :value="row.id" :disabled="loading || !!error"><span>{{row.task_number}}</span><span class="task-salesperson">{{row.salesperson.name}}</span></el-option>
    <template #empty><div class="task-select-state">{{loading ? '正在加载生产任务…' : error || '没有匹配的生产任务'}}</div></template>
    <template #footer><div v-if="error || page < totalPages" class="task-select-footer"><span v-if="error" role="alert">{{error}}</span><el-button link :loading="loading" @click.stop="load(error ? (page ? page + 1 : 1) : page + 1)">{{error ? '重试' : '加载更多'}}</el-button></div></template>
  </el-select>
</template>

<style scoped>
.task-salesperson { margin-left: 16px; color: var(--erp-color-text-secondary); font-size: 12px; }
.task-select-state { padding: 12px; color: var(--erp-color-text-secondary); text-align: center; }
.task-select-footer { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; font-size: 12px; }
</style>
