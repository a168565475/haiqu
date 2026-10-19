<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'

import { fetchWorkReportTasks } from '@/api/workshopReporting'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import type { WorkReportTask } from '@/types/workshopReporting'

const props = defineProps<{
  modelValue: boolean
  initialTask?: WorkReportTask | null
  initialWorkshopId?: string
  submitting?: boolean
  selectionError?: string
}>()
const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  select: [value: { productionTaskId: string; workshopId: string }]
}>()

const visible = computed({
  get: () => props.modelValue,
  set: value => { if (!props.submitting) emit('update:modelValue', value) },
})
const tasks = ref<WorkReportTask[]>([])
const selectedTask = ref<WorkReportTask | null>(null)
const selectedTaskId = ref('')
const selectedWorkshopId = ref('')
const query = ref('')
const page = ref(0)
const totalPages = ref(0)
const loading = ref(false)
const loadError = ref('')
let requestSequence = 0

const taskOptions = computed(() => selectedTask.value && !tasks.value.some(item => item.id === selectedTask.value?.id)
  ? [selectedTask.value, ...tasks.value]
  : tasks.value)
const canConfirm = computed(() => !loading.value && !loadError.value && !props.submitting
  && Boolean(selectedTask.value?.workshops.some(item => item.id === selectedWorkshopId.value)))

async function loadTasks(append = false) {
  const requestId = ++requestSequence
  const requestedPage = append ? page.value + 1 : 1
  loading.value = true
  loadError.value = ''
  if (!append) {
    tasks.value = []
    page.value = 0
    totalPages.value = 0
  }
  try {
    const result = await fetchWorkReportTasks({ q: query.value || undefined, page: requestedPage, page_size: 20 })
    if (requestId !== requestSequence) return
    const merged = new Map((append ? tasks.value : []).map(item => [item.id, item]))
    result.data.forEach(item => merged.set(item.id, item))
    tasks.value = [...merged.values()]
    page.value = result.meta.page
    totalPages.value = result.meta.total_pages
  } catch (error) {
    if (requestId !== requestSequence) return
    loadError.value = (error as { response?: { data?: { error?: { message?: string } } } })
      ?.response?.data?.error?.message || '生产任务单加载失败，请重试。'
  } finally {
    if (requestId === requestSequence) loading.value = false
  }
}

function searchTasks(value: string) {
  query.value = value.trim()
  void loadTasks()
}

function selectTask(value: string) {
  selectedTask.value = taskOptions.value.find(item => item.id === value) || null
  selectedWorkshopId.value = ''
}

function confirm() {
  if (!canConfirm.value || !selectedTask.value) return
  emit('select', { productionTaskId: selectedTask.value.id, workshopId: selectedWorkshopId.value })
}

watch(() => props.modelValue, (isVisible) => {
  requestSequence += 1
  loading.value = false
  if (!isVisible) return
  selectedTask.value = props.initialTask || null
  selectedTaskId.value = selectedTask.value?.id || ''
  selectedWorkshopId.value = selectedTask.value?.workshops.some(item => item.id === props.initialWorkshopId)
    ? props.initialWorkshopId || '' : ''
  query.value = ''
  void loadTasks()
}, { immediate: true })

onBeforeUnmount(() => { requestSequence += 1 })
</script>

<template>
  <AppWindowDialog v-model="visible" title="选择报工记录" :width="560" :min-height="300" :minimizable="false" :show-close="!submitting" :close-on-press-escape="!submitting" :close-on-click-modal="false" destroy-on-close data-testid="work-report-task-dialog">
    <ElForm label-position="top" class="wr-report-task-selector">
      <ElFormItem label="生产任务单">
        <ElSelect
          v-model="selectedTaskId"
          data-testid="work-report-task-select"
          filterable remote clearable
          :remote-method="searchTasks"
          :loading="loading"
          :disabled="submitting"
          placeholder="搜索任务单号或生产订单号"
          no-data-text="暂无可查看的生产任务单"
          @change="selectTask"
        >
          <ElOption v-for="task in taskOptions" :key="task.id" :value="task.id" :label="`${task.task_number} · ${task.order_number}`" />
          <template v-if="page < totalPages" #footer>
            <ElButton link type="primary" :loading="loading" @click="loadTasks(true)">加载更多</ElButton>
          </template>
        </ElSelect>
      </ElFormItem>
      <ElFormItem label="车间">
        <ElSelect v-model="selectedWorkshopId" data-testid="work-report-task-workshop" :disabled="!selectedTask || submitting" placeholder="选择车间" no-data-text="当前任务暂无可查看的车间">
          <ElOption v-for="workshop in selectedTask?.workshops || []" :key="workshop.id" :label="workshop.name" :value="workshop.id" />
        </ElSelect>
      </ElFormItem>
      <ElAlert v-if="loadError || selectionError" type="error" :closable="false" show-icon :title="loadError || selectionError">
        <template v-if="loadError" #default><ElButton link type="primary" @click="loadTasks()">重试</ElButton></template>
      </ElAlert>
    </ElForm>
    <template #footer>
      <ElButton :disabled="submitting" @click="visible = false">取消</ElButton>
      <ElButton type="primary" data-testid="work-report-task-confirm" :disabled="!canConfirm" :loading="submitting" @click="confirm">查看报工记录</ElButton>
    </template>
  </AppWindowDialog>
</template>

<style scoped>
.wr-report-task-selector .el-select { width: 100%; }
</style>
