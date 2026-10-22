<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { AxiosError } from 'axios'
import { ElMessage } from 'element-plus'
import { useRouter } from 'vue-router'

import { createSchedule, fetchScheduleOptions, fetchTaskCandidate, scheduleProductImageUrl } from '@/api/productionScheduling'
import productImagePlaceholder from '@/assets/productionScheduling/product-image-placeholder.png'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import BatchScheduleFillDialog from '@/components/productionScheduling/BatchScheduleFillDialog.vue'
import type { ProductionTask } from '@/types/productionTask'
import type { ScheduleCraftOption, ScheduleTaskCandidate, ScheduleTaskProduct, ScheduleWriteItem } from '@/types/productionScheduling'

interface ProductDraft extends ScheduleWriteItem {
  selected: boolean
  product: ScheduleTaskProduct
}

type BatchFillValue = Partial<ScheduleWriteItem> & {
  internal_craft_ids?: string[]
  external_craft_ids?: string[]
}

const props = defineProps<{
  modelValue: boolean
  task: ProductionTask | null
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  saved: [scheduleId: string]
}>()

const router = useRouter()
const loading = ref(false)
const saving = ref(false)
const errorMessage = ref('')
const candidate = ref<ScheduleTaskCandidate | null>(null)
const crafts = ref<ScheduleCraftOption[]>([])
const activeProductId = ref('')
const drafts = reactive<ProductDraft[]>([])
const batchVisible = ref(false)
const clientRequestId = ref('')
let loadRequest = 0

const selectedDrafts = computed(() => drafts.filter(item => item.selected))
const activeDraft = computed(() => (
  drafts.find(item => item.product_line_id === activeProductId.value)
  || selectedDrafts.value[0]
  || drafts[0]
  || null
))
const internalCrafts = computed(() => crafts.value.filter(item => item.craft_type === 'INTERNAL'))
const externalCrafts = computed(() => crafts.value.filter(item => item.craft_type === 'EXTERNAL'))
const verifiedBomCount = computed(() => drafts.filter(item => item.product.bom_status === 'VERIFIED').length)
const bomSummary = computed(() => {
  if (!drafts.length) return '未建立'
  if (verifiedBomCount.value === drafts.length) return `已确认（${verifiedBomCount.value}/${drafts.length}）`
  if (verifiedBomCount.value > 0) return `部分确认（${verifiedBomCount.value}/${drafts.length}）`
  return drafts.some(item => item.product.bom_status !== 'NOT_CREATED') ? '待确认' : '未建立'
})
const purchaseSummary = computed(() => {
  const labels = [...new Set(drafts.map(item => item.product.purchase_status_display).filter(Boolean))]
  if (!labels.length) return props.task?.purchase_status_display || '未发起'
  return labels.length === 1 ? labels[0] : '多状态'
})
const schedulingReady = computed(() => candidate.value?.scheduling_ready === true)
const schedulingBlockerText = computed(() => (
  candidate.value?.scheduling_blockers?.length
    ? `${candidate.value.scheduling_blockers.join('；')}后才能排产。`
    : ''
))

function apiError(error: unknown, fallback = '排产资料加载失败，请稍后重试。') {
  if (!(error instanceof AxiosError)) return error instanceof Error ? error.message : fallback
  const data = error.response?.data as { error?: { message?: string }; detail?: string } | undefined
  if (error.response?.status === 403) return '当前账号没有创建排产计划的权限。'
  if (error.response?.status === 409) return data?.error?.message || '该生产任务单已经存在有效排产计划。'
  return data?.error?.message || data?.detail || fallback
}

function blankDraft(product: ScheduleTaskProduct): ProductDraft {
  return {
    product_line_id: product.id,
    planned_quantity: product.quantity,
    material_inbound_date: '',
    metal_return_date: '',
    sewing_return_date: '',
    finished_inbound_date: '',
    craft_ids: [],
    selected: true,
    product,
  }
}

async function loadDialog() {
  const taskId = props.task?.id
  if (!taskId) return
  const requestId = ++loadRequest
  loading.value = true
  errorMessage.value = ''
  candidate.value = null
  drafts.splice(0)
  activeProductId.value = ''
  clientRequestId.value = window.crypto.randomUUID()
  try {
    const [taskCandidate, options] = await Promise.all([
      fetchTaskCandidate(taskId),
      fetchScheduleOptions(),
    ])
    if (requestId !== loadRequest) return
    candidate.value = taskCandidate
    crafts.value = options.crafts
    drafts.push(...(taskCandidate.products || []).map(blankDraft))
    activeProductId.value = drafts[0]?.product_line_id || ''
    if (taskCandidate.existing_schedule_id) {
      errorMessage.value = '该生产任务单已经存在有效排产计划，请查看原计划。'
    }
  } catch (error) {
    if (requestId === loadRequest) errorMessage.value = apiError(error)
  } finally {
    if (requestId === loadRequest) loading.value = false
  }
}

watch(() => props.modelValue, visible => {
  if (visible) void loadDialog()
  else loadRequest += 1
})

function close() {
  if (saving.value) return
  emit('update:modelValue', false)
}

function updateVisibility(value: boolean) {
  if (!value && saving.value) return
  emit('update:modelValue', value)
}

function selectProduct(item: ProductDraft) {
  activeProductId.value = item.product_line_id
}

function toggleProduct(item: ProductDraft, selected: boolean) {
  item.selected = selected
  if (selected) activeProductId.value = item.product_line_id
  else if (activeProductId.value === item.product_line_id) {
    activeProductId.value = selectedDrafts.value[0]?.product_line_id || drafts[0]?.product_line_id || ''
  }
}

function imageFallback(event: Event) {
  const image = event.currentTarget as HTMLImageElement
  if (image.dataset.fallbackApplied === 'true') return
  image.dataset.fallbackApplied = 'true'
  image.src = productImagePlaceholder
  image.classList.add('is-placeholder')
}

function quantity(value: number) {
  return new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 4 }).format(value)
}

function craftIdsByType(item: ProductDraft, type: 'INTERNAL' | 'EXTERNAL') {
  const allowed = new Set(crafts.value.filter(craft => craft.craft_type === type).map(craft => craft.id))
  return item.craft_ids.filter(id => allowed.has(id))
}

function updateCraftIds(item: ProductDraft, type: 'INTERNAL' | 'EXTERNAL', ids: string[]) {
  const opposite = craftIdsByType(item, type === 'INTERNAL' ? 'EXTERNAL' : 'INTERNAL')
  item.craft_ids = [...opposite, ...ids]
}

function craftSummary(item: ProductDraft, type: 'INTERNAL' | 'EXTERNAL') {
  const ids = new Set(craftIdsByType(item, type))
  return crafts.value.filter(craft => ids.has(craft.id)).map(craft => craft.name).join('、')
}

function statusTone(status: string) {
  if (status === 'VERIFIED' || status === 'ORDER_COMPLETED' || status === 'REQUEST_FULLY_ALLOCATED') return 'success'
  if (status === 'REQUEST_CANCELLED') return 'danger'
  if (status === 'NOT_CREATED' || status === 'NOT_STARTED' || status.endsWith('_DRAFT')) return 'neutral'
  return 'warning'
}

function applyBatch(value: BatchFillValue) {
  selectedDrafts.value.forEach(item => {
    if (value.material_inbound_date) item.material_inbound_date = value.material_inbound_date
    if (value.metal_return_date) item.metal_return_date = value.metal_return_date
    if (value.sewing_return_date) item.sewing_return_date = value.sewing_return_date
    if (value.finished_inbound_date) item.finished_inbound_date = value.finished_inbound_date
    if (value.internal_craft_ids) updateCraftIds(item, 'INTERNAL', value.internal_craft_ids)
    if (value.external_craft_ids) updateCraftIds(item, 'EXTERNAL', value.external_craft_ids)
  })
}

function validate() {
  if (!candidate.value) return '排产来源尚未加载完成。'
  if (candidate.value.existing_schedule_id) return '该生产任务单已经存在有效排产计划。'
  if (!schedulingReady.value) return schedulingBlockerText.value || 'BOM 已确认且采购已完成后才能排产。'
  if (!selectedDrafts.value.length) return '请至少选择一个订单产品。'
  for (const item of selectedDrafts.value) {
    if (!Number.isInteger(item.planned_quantity) || item.planned_quantity < 1 || item.planned_quantity > item.product.quantity) {
      return `${item.product.product_name} 的排产数量必须是 1 到 ${item.product.quantity} 的整数。`
    }
    if (!item.material_inbound_date || !item.metal_return_date || !item.sewing_return_date || !item.finished_inbound_date) {
      return `${item.product.product_name} 的四个计划时间均为必填。`
    }
    if (!item.craft_ids.length) return `${item.product.product_name} 至少选择一项厂内或厂外工艺。`
  }
  return ''
}

async function save() {
  const message = validate()
  if (message) {
    ElMessage.warning(message)
    return
  }
  saving.value = true
  errorMessage.value = ''
  try {
    const result = await createSchedule({
      production_task_id: candidate.value!.id,
      source_revision_hash: candidate.value!.source_revision_hash,
      client_request_id: clientRequestId.value,
      items: selectedDrafts.value.map(item => ({
        product_line_id: item.product_line_id,
        planned_quantity: item.planned_quantity,
        material_inbound_date: item.material_inbound_date,
        metal_return_date: item.metal_return_date,
        sewing_return_date: item.sewing_return_date,
        finished_inbound_date: item.finished_inbound_date,
        craft_ids: [...item.craft_ids],
      })),
    })
    ElMessage.success('排产计划已保存。')
    emit('saved', result.data.id)
    emit('update:modelValue', false)
  } catch (error) {
    errorMessage.value = apiError(error, '保存排产失败，请稍后重试。')
  } finally {
    saving.value = false
  }
}

function viewExistingSchedule() {
  const scheduleId = candidate.value?.existing_schedule_id
  if (!scheduleId) return
  emit('update:modelValue', false)
  void router.push(`/workshop/scheduling/${scheduleId}`)
}
</script>

<template>
  <AppWindowDialog
    :model-value="modelValue"
    :title="`计划排产${task?.task_number ? ` · ${task.task_number}` : ''}`"
    :width="1480"
    :height="820"
    :close-on-click-modal="!saving"
    :close-on-press-escape="!saving"
    :show-close="!saving"
    modal-class="production-task-schedule-overlay"
    class="production-task-schedule-dialog"
    destroy-on-close
    @update:model-value="updateVisibility"
  >
    <div v-loading="loading" class="task-schedule-dialog__content">
      <ElAlert v-if="errorMessage" class="task-schedule-dialog__error" type="error" :closable="false" :title="errorMessage">
        <ElButton v-if="candidate?.existing_schedule_id" link type="primary" @click="viewExistingSchedule">查看原计划</ElButton>
        <ElButton v-else link type="primary" @click="loadDialog">重新加载</ElButton>
      </ElAlert>

      <section class="schedule-readiness" aria-label="排产前检查">
        <header><strong>排产前检查</strong><span>BOM 已确认且采购已完成后才能排产。</span></header>
        <div class="schedule-readiness__items">
          <div><span>PMC确认</span><ElTag class="readiness-tag is-success" effect="dark">已确认</ElTag></div>
          <div><span>BOM状态</span><ElTag class="readiness-tag" :class="verifiedBomCount === drafts.length && drafts.length ? 'is-success' : 'is-warning'" effect="dark">{{ bomSummary }}</ElTag></div>
          <div><span>采购状态</span><ElTag class="readiness-tag" :class="`is-${statusTone(drafts[0]?.product.purchase_status || task?.purchase_status || 'NOT_STARTED')}`" effect="dark">{{ purchaseSummary }}</ElTag></div>
        </div>
        <p v-if="candidate && !schedulingReady" class="schedule-readiness__blocker">{{ schedulingBlockerText }}</p>
      </section>

      <div v-if="candidate && drafts.length" class="schedule-workspace">
        <aside class="schedule-products">
          <header><div><strong>订单内产品</strong><span>{{ drafts.length }} 项 · 已选 {{ selectedDrafts.length }} 项</span></div></header>
          <div class="schedule-products__list">
            <article
              v-for="item in drafts"
              :key="item.product_line_id"
              class="schedule-product-row"
              :class="{ 'is-active': activeDraft?.product_line_id === item.product_line_id }"
              @click="selectProduct(item)"
            >
              <ElCheckbox :model-value="item.selected" :aria-label="`选择${item.product.product_name}`" @click.stop @update:model-value="toggleProduct(item, Boolean($event))" />
              <img
                :src="item.product.image_file_id ? scheduleProductImageUrl(candidate.id, item.product.image_file_id) : productImagePlaceholder"
                :class="{ 'is-placeholder': !item.product.image_file_id }"
                :alt="`${item.product.product_name}图片`"
                @error="imageFallback"
              />
              <div class="schedule-product-row__info">
                <strong :title="item.product.product_name">{{ item.product.product_name || '未命名产品' }}</strong>
                <span :title="[item.product.item_number || item.product.product_code, item.product.color_name].filter(Boolean).join(' · ')">{{ [item.product.item_number || item.product.product_code, item.product.color_name].filter(Boolean).join(' · ') || '—' }}</span>
                <small>订单数量</small>
                <b>{{ quantity(item.product.quantity) }} {{ item.product.unit_name }}</b>
              </div>
              <div class="schedule-product-row__status">
                <span>BOM</span>
                <ElTag class="product-status-tag" :class="`is-${statusTone(item.product.bom_status)}`" effect="dark">{{ item.product.bom_status_display }}</ElTag>
              </div>
              <div class="schedule-product-row__status">
                <span>采购</span>
                <ElTag class="product-status-tag" :class="`is-${statusTone(item.product.purchase_status)}`" effect="dark">{{ item.product.purchase_status_display }}</ElTag>
              </div>
            </article>
          </div>
        </aside>

        <main v-if="activeDraft" class="schedule-editor">
          <header class="schedule-editor__heading">
            <div><h2>{{ activeDraft.product.product_name }} · 排产信息</h2><span>订单数量 {{ quantity(activeDraft.product.quantity) }} {{ activeDraft.product.unit_name }}</span></div>
            <ElButton :disabled="!selectedDrafts.length" @click="batchVisible = true">批量填入已选产品</ElButton>
          </header>

          <section class="schedule-editor__section quantity-section">
            <label><span>排产数量</span><div><ElInputNumber v-model="activeDraft.planned_quantity" :min="1" :max="activeDraft.product.quantity" :step="1" :precision="0" :controls="false" /><em>{{ activeDraft.product.unit_name }}</em></div></label>
          </section>

          <section class="schedule-editor__section">
            <h3>计划关键时间</h3>
            <div class="schedule-date-grid">
              <label><span>材料入库时间</span><ElDatePicker v-model="activeDraft.material_inbound_date" value-format="YYYY-MM-DD" placeholder="选择日期" popper-class="schedule-date-popper" /></label>
              <label><span>金工回货时间</span><ElDatePicker v-model="activeDraft.metal_return_date" value-format="YYYY-MM-DD" placeholder="选择日期" popper-class="schedule-date-popper" /></label>
              <label><span>车缝回货时间</span><ElDatePicker v-model="activeDraft.sewing_return_date" value-format="YYYY-MM-DD" placeholder="选择日期" popper-class="schedule-date-popper" /></label>
              <label><span>成品入库时间</span><ElDatePicker v-model="activeDraft.finished_inbound_date" value-format="YYYY-MM-DD" placeholder="选择日期" popper-class="schedule-date-popper" /></label>
            </div>
          </section>

          <section class="schedule-editor__section">
            <h3>工艺选择</h3>
            <div class="schedule-craft-grid">
              <label><span>厂内工艺</span><div class="schedule-craft-field"><ElSelect :model-value="craftIdsByType(activeDraft, 'INTERNAL')" multiple collapse-tags :max-collapse-tags="0" placeholder="选择厂内工艺" popper-class="schedule-craft-popper" @update:model-value="(value: string[]) => updateCraftIds(activeDraft, 'INTERNAL', value)"><ElOption v-for="craft in internalCrafts" :key="craft.id" :label="craft.name" :value="craft.id" /></ElSelect><strong v-if="craftIdsByType(activeDraft, 'INTERNAL').length">{{ craftSummary(activeDraft, 'INTERNAL') }}</strong></div></label>
              <label><span>厂外工艺</span><div class="schedule-craft-field"><ElSelect :model-value="craftIdsByType(activeDraft, 'EXTERNAL')" multiple collapse-tags :max-collapse-tags="0" placeholder="选择厂外工艺" popper-class="schedule-craft-popper" @update:model-value="(value: string[]) => updateCraftIds(activeDraft, 'EXTERNAL', value)"><ElOption v-for="craft in externalCrafts" :key="craft.id" :label="craft.name" :value="craft.id" /></ElSelect><strong v-if="craftIdsByType(activeDraft, 'EXTERNAL').length">{{ craftSummary(activeDraft, 'EXTERNAL') }}</strong></div></label>
            </div>
          </section>
          <p class="schedule-editor__tip">切换产品会保留已填写内容。</p>
        </main>
      </div>
    </div>

    <template #footer>
      <div class="task-schedule-dialog__footer"><p>保存后任务进入生产中，不代表入库或回货。</p><div><ElButton :disabled="saving" @click="close">取消</ElButton><ElButton type="primary" :loading="saving" :disabled="loading || !candidate || !!candidate.existing_schedule_id || !schedulingReady" @click="save">保存排产</ElButton></div></div>
    </template>

    <BatchScheduleFillDialog v-model="batchVisible" :crafts="crafts" :selected-count="selectedDrafts.length" @apply="applyBatch" />
  </AppWindowDialog>
</template>

<style scoped lang="scss">
.task-schedule-dialog__content { box-sizing: border-box; min-height: 0; height: 100%; display: flex; flex-direction: column; padding: 16px 20px 14px; color: var(--erp-color-text-primary); background: var(--erp-color-surface); }
.task-schedule-dialog__error { margin-bottom: 12px; }
.schedule-readiness { border: 1px solid var(--erp-color-border); border-radius: 5px; background: var(--erp-color-surface); }
.schedule-readiness header { min-height: 32px; display: flex; align-items: center; justify-content: space-between; padding: 0 14px; border-bottom: 1px solid var(--erp-color-border-subtle); }
.schedule-readiness header strong { font-family: 'Noto Serif SC', serif; font-size: 18px; }
.schedule-readiness header span { color: var(--erp-color-text-secondary); font-size: 12px; }
.schedule-readiness__items { height: 42px; display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); align-items: center; }
.schedule-readiness__items > div { height: 24px; display: flex; align-items: center; gap: 10px; padding: 0 18px; border-right: 1px solid var(--erp-color-border); }
.schedule-readiness__items > div:last-child { border-right: 0; }
.schedule-readiness__items > div > span:first-child { color: var(--erp-color-text-regular); font-size: 13px; }
.schedule-readiness__blocker { margin: 0; padding: 7px 14px; border-top: 1px solid var(--erp-color-warning-border); color: var(--erp-color-warning); background: var(--erp-color-warning-soft); font-size: 12px; line-height: 18px; }
.readiness-tag, .product-status-tag { --el-tag-text-color: var(--erp-color-text-inverse); box-sizing: border-box; min-width: 56px; height: 24px; justify-content: center; padding: 0 8px; border: 0; border-radius: 999px; color: var(--erp-color-text-inverse); font-family: 'Noto Sans SC', sans-serif; font-size: 12px; line-height: 18px; font-weight: 500; white-space: nowrap; }
.product-status-tag { max-width: 100%; overflow: hidden; text-overflow: ellipsis; }
.product-status-tag :deep(.el-tag__content) { color: var(--erp-color-text-inverse); }
.is-success { background: var(--erp-tag-success-background) !important; }
.is-warning { background: var(--erp-tag-warning-background) !important; }
.is-danger { background: var(--erp-tag-danger-background) !important; }
.is-neutral { background: var(--erp-tag-neutral-background) !important; }
.schedule-workspace { min-height: 0; flex: 1; display: grid; grid-template-columns: minmax(470px, 0.95fr) minmax(620px, 1.45fr); gap: 14px; margin-top: 14px; }
.schedule-products, .schedule-editor { min-height: 0; overflow: hidden; border: 1px solid var(--erp-color-border); border-radius: 5px; background: var(--erp-color-surface); }
.schedule-products { display: flex; flex-direction: column; }
.schedule-products > header { height: 48px; flex: none; display: flex; align-items: center; padding: 0 16px; border-bottom: 1px solid var(--erp-color-border-subtle); }
.schedule-products > header > div { display: flex; align-items: baseline; gap: 14px; }
.schedule-products > header strong { font-family: 'Noto Serif SC', serif; font-size: 18px; }
.schedule-products > header span { color: var(--erp-color-text-secondary); font-size: 12px; }
.schedule-products__list { min-height: 0; flex: 1; overflow: auto; }
.schedule-product-row { box-sizing: border-box; min-height: 116px; display: grid; grid-template-columns: 22px 64px minmax(118px, 1fr) 72px 78px; align-items: center; column-gap: 10px; padding: 12px 12px; border-bottom: 1px solid var(--erp-color-border-subtle); cursor: pointer; }
.schedule-product-row:hover { background: var(--erp-color-hover); }
.schedule-product-row.is-active { box-shadow: inset 3px 0 var(--erp-color-border); background: var(--erp-color-selected); }
.schedule-product-row > img { width: 64px; height: 64px; object-fit: cover; border: 1px solid var(--erp-color-border); border-radius: 4px; background: var(--erp-color-readonly); }
.schedule-product-row > img.is-placeholder { object-fit: contain; padding: 8px; box-sizing: border-box; }
.schedule-product-row__info { min-width: 0; display: flex; flex-direction: column; align-items: flex-start; }
.schedule-product-row__info strong, .schedule-product-row__info span { width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.schedule-product-row__info strong { font-size: 14px; line-height: 22px; }
.schedule-product-row__info span { color: var(--erp-color-text-secondary); font-size: 12px; line-height: 20px; }
.schedule-product-row__info small { margin-top: 5px; color: var(--erp-color-text-muted); font-size: 11px; }
.schedule-product-row__info b { font-size: 14px; line-height: 22px; }
.schedule-product-row__status { width: 100%; display: flex; flex-direction: column; align-items: center; gap: 7px; }
.schedule-product-row__status > span:first-child { color: var(--erp-color-text-secondary); font-size: 11px; }
.schedule-editor { display: flex; flex-direction: column; padding: 0 18px; }
.schedule-editor__heading { height: 76px; flex: none; display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid var(--erp-color-border-subtle); }
.schedule-editor__heading h2 { margin: 0; font-family: 'Noto Serif SC', serif; font-size: 22px; line-height: 30px; }
.schedule-editor__heading span { color: var(--erp-color-text-secondary); font-size: 12px; }
.schedule-editor :deep(.el-button), .schedule-editor :deep(.el-input__wrapper), .schedule-editor :deep(.el-select__wrapper), .schedule-editor :deep(.el-date-editor), .schedule-editor :deep(.el-input-number) { height: 32px; min-height: 32px; }
.schedule-editor__section { padding: 18px 0; border-bottom: 1px solid var(--erp-color-border-subtle); }
.schedule-editor__section h3 { margin: 0 0 14px; font-family: 'Noto Serif SC', serif; font-size: 17px; }
.quantity-section label { display: grid; grid-template-columns: 120px 240px; align-items: center; }
.quantity-section label > span, .schedule-date-grid label > span, .schedule-craft-grid label > span { color: var(--erp-color-text-regular); font-size: 13px; }
.quantity-section label > div { display: grid; grid-template-columns: minmax(0, 1fr) 42px; }
.quantity-section :deep(.el-input-number) { width: 100%; }
.quantity-section em { display: grid; place-items: center; border: 1px solid var(--erp-color-border); border-left: 0; border-radius: 0 4px 4px 0; color: var(--erp-color-text-regular); background: var(--erp-color-subtle); font-size: 12px; font-style: normal; }
.schedule-date-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px 28px; }
.schedule-date-grid label, .schedule-craft-grid label { min-width: 0; display: grid; grid-template-columns: 110px minmax(0, 1fr); align-items: center; }
.schedule-date-grid :deep(.el-date-editor), .schedule-craft-grid :deep(.el-select) { width: 100%; }
.schedule-craft-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 28px; }
.schedule-craft-field { position: relative; min-width: 0; }
.schedule-craft-field > strong { position: absolute; z-index: 1; top: 1px; right: 34px; bottom: 1px; left: 12px; display: flex; align-items: center; overflow: hidden; color: var(--erp-color-text-primary); background: var(--erp-color-surface); font-size: 13px; font-weight: 400; text-overflow: ellipsis; white-space: nowrap; pointer-events: none; }
.schedule-editor__tip { margin: 16px 0 0; color: var(--erp-color-text-secondary); font-size: 12px; }
.task-schedule-dialog__footer { width: 100%; display: flex; align-items: center; justify-content: space-between; gap: 24px; }
.task-schedule-dialog__footer p { margin: 0; color: var(--erp-color-text-secondary); font-size: 12px; }
.task-schedule-dialog__footer > div { display: flex; gap: 10px; }
.task-schedule-dialog__footer :deep(.el-button) { height: 32px; margin: 0; }
.task-schedule-dialog__footer :deep(.el-button--primary) { border-color: var(--erp-button-primary-border); background: var(--erp-button-primary-surface); }
</style>

<style lang="scss">
.production-task-schedule-dialog {
  --el-color-primary: var(--erp-color-brand);
  font-family: 'Noto Sans SC', sans-serif;
}
.production-task-schedule-dialog .app-window-dialog__body { min-height: 0; flex: 1; padding: 0; overflow: hidden; }
.production-task-schedule-dialog .app-window-dialog__footer { height: 58px; display: flex; align-items: center; padding: 0 20px; border-top: 1px solid var(--erp-color-border-subtle); background: var(--erp-color-surface); }
.production-task-schedule-dialog .el-dialog__title { font-family: 'Noto Serif SC', serif; font-size: 20px; }
</style>
