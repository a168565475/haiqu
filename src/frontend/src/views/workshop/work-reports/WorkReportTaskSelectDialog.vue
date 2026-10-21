<script setup lang="ts">
import { Check, Picture, Search } from '@element-plus/icons-vue'
import { computed, onBeforeUnmount, ref, watch } from 'vue'

import { fetchWorkReportTasks } from '@/api/workshopReporting'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import type { WorkReportTask, WorkReportTaskProgress } from '@/types/workshopReporting'
import WorkshopChoiceIcon from './WorkshopChoiceIcon.vue'

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
const workshopNames = ['金工车间', '车缝车间', '装配车间', '敲布孔'] as const
const tasks = ref<WorkReportTask[]>([])
const selectedTask = ref<WorkReportTask | null>(null)
const selectedWorkshopId = ref('')
const draftQuery = ref('')
const query = ref('')
const page = ref(0)
const totalPages = ref(0)
const loading = ref(false)
const loadError = ref('')
const failedImageUrls = ref(new Set<string>())
const previewWorkshop = ref('')
let requestSequence = 0

const taskOptions = computed(() => selectedTask.value && !tasks.value.some(item => item.id === selectedTask.value?.id)
  ? [selectedTask.value, ...tasks.value]
  : tasks.value)
const workshopChoices = computed(() => workshopNames.map(name => ({
  name,
  workshop: selectedTask.value?.workshops.find(item => item.name === name),
})))
const canConfirm = computed(() => !loading.value && !loadError.value && !props.submitting
  && Boolean(selectedTask.value?.workshops.some(item => item.id === selectedWorkshopId.value)))
const taskCards = computed(() => taskOptions.value.map(task => {
  const workshop = task.id === selectedTask.value?.id
    ? task.workshops.find(item => item.id === selectedWorkshopId.value) : undefined
  const stats = workshop || task
  const percentage = progressPercentage(stats.progress)
  return {
    task,
    amount: amountText(stats.reported_amount),
    scope: workshop ? workshop.name : '可查看车间',
    percentage,
    progressText: percentage === null
      ? stats.progress?.status === 'UNAVAILABLE' || stats.progress?.status === 'READY' ? '暂无进度' : '待配置'
      : `${percentage}%`,
  }
}))

function progressPercentage(progress?: WorkReportTaskProgress) {
  if (progress?.status !== 'READY' || typeof progress.percentage !== 'number' || !Number.isFinite(progress.percentage)) return null
  return Math.min(100, Math.max(0, progress.percentage))
}

function amountText(value?: string) {
  if (typeof value !== 'string' || !value.trim() || !Number.isFinite(Number(value))) return '—'
  return `¥${Number(value).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

async function loadTasks(append = false, restoreSelection?: { taskId: string; workshopId: string }) {
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
    let restoredTask = restoreSelection ? result.data.find(item => item.id === restoreSelection.taskId) : undefined
    // 初始任务可能在后续分页，重新验证其权限及统计，不沿用上次打开的缓存。
    if (restoreSelection && !restoredTask) {
      const restored = await fetchWorkReportTasks({ production_task_id: restoreSelection.taskId, page: 1, page_size: 1 })
      if (requestId !== requestSequence) return
      restoredTask = restored.data.find(item => item.id === restoreSelection.taskId)
    }
    const merged = new Map((append ? tasks.value : []).map(item => [item.id, item]))
    result.data.forEach(item => merged.set(item.id, item))
    tasks.value = [...merged.values()]
    if (restoreSelection) {
      selectedTask.value = restoredTask || null
      selectedWorkshopId.value = restoredTask?.workshops.some(item => item.id === restoreSelection.workshopId)
        ? restoreSelection.workshopId : ''
    } else if (selectedTask.value) {
      const refreshedTask = result.data.find(item => item.id === selectedTask.value?.id)
      if (refreshedTask) {
        selectedTask.value = refreshedTask
        if (!refreshedTask.workshops.some(item => item.id === selectedWorkshopId.value)) selectedWorkshopId.value = ''
      }
    }
    page.value = result.meta.page
    totalPages.value = result.meta.total_pages
  } catch (error) {
    if (requestId !== requestSequence) return
    tasks.value = []
    selectedTask.value = null
    selectedWorkshopId.value = ''
    loadError.value = (error as { response?: { data?: { error?: { message?: string } } } })
      ?.response?.data?.error?.message || '生产任务单加载失败，请重试。'
  } finally {
    if (requestId === requestSequence) loading.value = false
  }
}

function searchTasks() {
  if (props.submitting) return
  selectedTask.value = null
  selectedWorkshopId.value = ''
  query.value = draftQuery.value.trim()
  void loadTasks()
}

function clearSearch() {
  draftQuery.value = ''
  searchTasks()
}

function selectTask(task: WorkReportTask) {
  if (loading.value || props.submitting || task.id === selectedTask.value?.id) return
  selectedTask.value = task
  selectedWorkshopId.value = ''
}

function selectWorkshop(id?: string) {
  if (loading.value || props.submitting || !id || !selectedTask.value?.workshops.some(item => item.id === id)) return
  selectedWorkshopId.value = id
}

function confirm() {
  if (!canConfirm.value || !selectedTask.value) return
  emit('select', { productionTaskId: selectedTask.value.id, workshopId: selectedWorkshopId.value })
}

watch(() => props.modelValue, (isVisible) => {
  requestSequence += 1
  loading.value = false
  if (!isVisible) return
  selectedTask.value = null
  selectedWorkshopId.value = ''
  previewWorkshop.value = ''
  failedImageUrls.value = new Set()
  draftQuery.value = ''
  query.value = ''
  void loadTasks(false, props.initialTask ? { taskId: props.initialTask.id, workshopId: props.initialWorkshopId || '' } : undefined)
}, { immediate: true })

onBeforeUnmount(() => { requestSequence += 1 })
</script>

<template>
  <AppWindowDialog v-model="visible" class="wr-report-task-dialog" title="选择报工记录" :width="1360" :height="650" :min-height="360" :minimizable="false" :show-close="!submitting" :close-on-press-escape="!submitting" :close-on-click-modal="false" destroy-on-close data-testid="work-report-task-dialog">
    <div class="wr-report-task-selector">
      <form class="wr-task-search" @submit.prevent="searchTasks">
        <ElInput v-model="draftQuery" data-testid="work-report-task-search" :prefix-icon="Search" :disabled="submitting" placeholder="搜索任务单号或生产订单号" aria-label="搜索生产任务单" />
        <ElButton native-type="submit" :disabled="submitting">搜索</ElButton>
        <ElButton data-testid="work-report-task-clear" :disabled="submitting || (!draftQuery && !query)" @click="clearSearch">清空</ElButton>
      </form>
      <ElAlert v-if="loadError || selectionError" type="error" :closable="false" show-icon :title="loadError || selectionError">
        <template v-if="loadError" #default><ElButton link type="primary" :disabled="submitting" @click="loadTasks()">重试</ElButton></template>
      </ElAlert>
      <div class="wr-task-results" :aria-busy="loading" aria-label="生产任务单">
        <div v-if="!taskCards.length" class="wr-task-empty" role="status">
          {{ loading ? '正在加载生产任务单…' : loadError ? '生产任务单加载失败，请重试。' : '暂无可查看的生产任务单' }}
        </div>
        <div v-else class="wr-task-grid">
          <button v-for="card in taskCards" :key="card.task.id" type="button" class="wr-task-card" :class="{ 'is-selected': selectedTask?.id === card.task.id }" data-testid="work-report-task-card" :data-task-id="card.task.id" :aria-pressed="selectedTask?.id === card.task.id" :aria-label="`选择生产任务单 ${card.task.task_number}`" :disabled="loading || submitting" @click="selectTask(card.task)">
            <span class="wr-task-card__main">
              <span class="wr-task-card__image">
                <img v-if="card.task.product?.image_url && !failedImageUrls.has(card.task.product.image_url)" :src="card.task.product.image_url" :alt="card.task.product.name" loading="lazy" @error="failedImageUrls.add(card.task.product.image_url)" />
                <span v-else data-testid="task-image-placeholder" :aria-label="card.task.product?.image_url ? '图片暂不可用' : '暂无产品图片'" role="img"><ElIcon><Picture /></ElIcon></span>
              </span>
              <span class="wr-task-card__info">
                <strong class="wr-task-card__number">{{ card.task.task_number }}<ElIcon v-if="selectedTask?.id === card.task.id" class="wr-task-card__check"><Check /></ElIcon></strong>
                <span class="wr-task-card__product" :title="card.task.product ? `${card.task.product.name}（${card.task.product.number}）` : ''">{{ card.task.product?.name || '暂无产品信息' }}<small v-if="card.task.product_count && card.task.product_count > 1">共 {{ card.task.product_count }} 条产品明细</small></span>
                <span class="wr-task-card__order" :title="card.task.order_number">{{ card.task.order_number }}</span>
              </span>
              <span class="wr-task-card__amount"><small>{{ card.scope }}已报工</small><strong>{{ card.amount }}</strong></span>
            </span>
            <span class="wr-task-card__progress">
              <span class="wr-task-card__progress-label"><span>{{ card.scope }}进度</span><strong>{{ card.progressText }}</strong></span>
              <span v-if="card.percentage !== null" class="wr-task-progress" role="progressbar" :aria-label="`${card.task.task_number} ${card.scope}进度`" :aria-valuenow="card.percentage" :aria-valuemin="0" :aria-valuemax="100"><span class="wr-task-progress__fill" :style="{ width: `${card.percentage}%` }" /></span>
              <span v-else class="wr-task-progress is-unavailable" aria-hidden="true" />
            </span>
          </button>
        </div>
        <div v-if="page < totalPages" class="wr-task-more"><ElButton data-testid="work-report-task-more" link type="primary" :loading="loading" :disabled="loading || submitting" @click="loadTasks(true)">加载更多</ElButton></div>
      </div>
      <section class="wr-workshop-section" aria-label="选择车间">
        <div class="wr-workshop-section__heading"><strong>选择车间</strong><span>{{ selectedTask ? `已选任务 ${selectedTask.task_number}` : '请先选择生产任务单' }}</span></div>
        <div class="wr-workshop-grid">
          <button v-for="choice in workshopChoices" :key="choice.name" type="button" class="wr-workshop-choice" data-testid="work-report-workshop-choice" :data-workshop-name="choice.name" :aria-pressed="Boolean(choice.workshop && selectedWorkshopId === choice.workshop.id)" :disabled="!choice.workshop || loading || submitting" :title="!choice.workshop ? selectedTask ? '当前不可查看' : '请先选择生产任务单' : choice.name" @click="selectWorkshop(choice.workshop?.id)" @mouseenter="previewWorkshop = choice.name" @mouseleave="previewWorkshop = ''" @focus="previewWorkshop = choice.name" @blur="previewWorkshop = ''">
            <WorkshopChoiceIcon :name="choice.name" :active="Boolean(choice.workshop && !loading && !submitting && (selectedWorkshopId === choice.workshop.id || previewWorkshop === choice.name))" />
            <span class="wr-workshop-choice__label">{{ choice.name }}<small v-if="selectedTask && !choice.workshop">当前不可查看</small></span>
            <ElIcon v-if="choice.workshop && selectedWorkshopId === choice.workshop.id" class="wr-workshop-choice__check"><Check /></ElIcon>
          </button>
        </div>
      </section>
    </div>
    <template #footer>
      <ElButton :disabled="submitting" @click="visible = false">取消</ElButton>
      <ElButton type="primary" data-testid="work-report-task-confirm" :disabled="!canConfirm" :loading="submitting" @click="confirm">查看报工记录</ElButton>
    </template>
  </AppWindowDialog>
</template>

<style scoped>
:global(.wr-report-task-dialog .app-window-dialog__body) { display: flex; overflow: hidden; }
.wr-report-task-selector { display: flex; flex: 1; flex-direction: column; gap: 16px; min-width: 0; min-height: 0; container: wr-task-selector / inline-size; }
.wr-task-search { display: flex; flex: none; gap: 8px; }
.wr-task-search .el-input { min-width: 0; }
.wr-task-search .el-button { margin-left: 0; }
.wr-task-results { flex: 1; min-height: 0; overflow: auto; padding: 2px; }
.wr-task-empty { display: flex; align-items: center; justify-content: center; height: 100%; min-height: 100px; color: var(--erp-color-text-secondary); font-size: 13px; }
.wr-task-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 300px), 1fr)); align-items: start; gap: 12px; }
.wr-task-card { min-width: 0; padding: 12px; border: 1px solid var(--erp-color-border); border-radius: 8px; background: var(--erp-color-surface); color: var(--erp-color-text-primary); font: inherit; text-align: left; cursor: pointer; transition: border-color 160ms, background-color 160ms; }
.wr-task-card:hover:not(:disabled) { border-color: var(--erp-color-brand); }
.wr-task-card.is-selected { border-color: var(--erp-color-brand); background: color-mix(in srgb, var(--erp-color-brand) 5%, var(--erp-color-surface)); }
.wr-task-card:focus-visible, .wr-workshop-choice:focus-visible { outline: 2px solid var(--erp-color-brand); outline-offset: 2px; }
.wr-task-card:disabled { cursor: wait; }
.wr-task-card__main { display: grid; grid-template-columns: 56px minmax(0, 1fr); align-items: center; gap: 10px; }
.wr-task-card__image { display: grid; place-items: center; width: 56px; height: 56px; border-radius: 5px; overflow: hidden; background: var(--erp-color-subtle); }
.wr-task-card__image img { width: 100%; height: 100%; object-fit: contain; }
.wr-task-card__image .el-icon { font-size: 27px; color: var(--erp-color-text-muted); }
.wr-task-card__info { display: flex; min-width: 0; flex-direction: column; gap: 4px; }
.wr-task-card__number { display: flex; align-items: center; gap: 6px; font-size: 15px; line-height: 22px; font-weight: 600; }
.wr-task-card__check { flex: none; color: var(--erp-color-brand); font-size: 15px; }
.wr-task-card__product, .wr-task-card__order { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; line-height: 18px; }
.wr-task-card__product small { display: block; font-size: 11px; color: var(--erp-color-text-secondary); }
.wr-task-card__order { color: var(--erp-color-text-secondary); }
.wr-task-card__amount { grid-column: 1 / -1; display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 8px; }
.wr-task-card__amount small { color: var(--erp-color-text-secondary); font-size: 11px; line-height: 18px; white-space: nowrap; }
.wr-task-card__amount strong { color: var(--erp-color-brand); font-size: 17px; line-height: 24px; font-weight: 600; font-variant-numeric: tabular-nums; white-space: nowrap; }
.wr-task-card__progress { display: flex; flex-direction: column; gap: 7px; margin-top: 12px; }
.wr-task-card__progress-label { display: flex; justify-content: space-between; gap: 8px; color: var(--erp-color-text-secondary); font-size: 11px; line-height: 16px; }
.wr-task-card__progress-label strong { font-weight: 500; }
.wr-task-progress { display: block; height: 6px; border-radius: 4px; overflow: hidden; background: var(--erp-color-border-subtle); }
.wr-task-progress__fill { display: block; position: relative; height: 100%; border-radius: inherit; background: var(--erp-color-brand); overflow: hidden; transition: width 460ms ease-out; }
.wr-task-progress__fill::after { content: ''; position: absolute; inset: 0; opacity: 0; background: linear-gradient(100deg, transparent, color-mix(in srgb, var(--erp-color-surface) 65%, transparent), transparent); }
.wr-task-card.is-selected .wr-task-progress__fill::after { animation: wr-task-progress-sheen 1100ms ease-out 3; }
.wr-task-more { display: flex; justify-content: center; padding-top: 10px; }
.wr-workshop-section { flex: none; width: 100%; max-width: 950px; }
.wr-workshop-section__heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 10px; line-height: 20px; }
.wr-workshop-section__heading strong { font-size: 14px; font-weight: 600; }
.wr-workshop-section__heading span { color: var(--erp-color-text-secondary); font-size: 12px; }
.wr-workshop-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
.wr-workshop-choice { position: relative; display: flex; align-items: center; justify-content: center; gap: 10px; min-width: 0; min-height: 88px; padding: 10px; border: 1px solid var(--erp-color-border); border-radius: 8px; background: var(--erp-color-surface); color: var(--erp-color-text-primary); font: inherit; cursor: pointer; transition: border-color 160ms, background-color 160ms; }
.wr-workshop-choice:hover:not(:disabled), .wr-workshop-choice[aria-pressed="true"] { border-color: var(--erp-color-brand); background: color-mix(in srgb, var(--erp-color-brand) 6%, var(--erp-color-surface)); }
.wr-workshop-choice:disabled { background: var(--erp-color-subtle); color: var(--erp-color-text-muted); cursor: not-allowed; }
.wr-workshop-choice__label { display: flex; flex-direction: column; gap: 4px; font-size: 14px; font-weight: 500; white-space: nowrap; }
.wr-workshop-choice__label small { font-size: 11px; font-weight: 400; }
.wr-workshop-choice__check { position: absolute; top: 7px; right: 7px; color: var(--erp-color-brand); font-size: 13px; }
@keyframes wr-task-progress-sheen { 0% { opacity: 0; transform: translateX(-100%); } 20%, 70% { opacity: .7; } 100% { opacity: 0; transform: translateX(100%); } }
@container wr-task-selector (max-width: 760px) {
  .wr-workshop-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
  .wr-workshop-choice { min-height: 62px; padding: 6px 10px; }
  .wr-workshop-choice :deep(.workshop-choice-icon) { width: 42px; height: 42px; }
}
@container wr-task-selector (max-width: 460px) {
  .wr-task-card { padding: 10px; }
  .wr-task-card__main { gap: 9px; }
  .wr-workshop-section__heading span { font-size: 11px; }
}
@media (prefers-reduced-motion: reduce) {
  .wr-task-card, .wr-workshop-choice, .wr-task-progress__fill { transition: none; }
  .wr-task-card.is-selected .wr-task-progress__fill::after { animation: none; }
}
</style>
