<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { AxiosError } from 'axios'
import { ElMessage } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'

import { createSchedulesBatch, fetchSchedule, fetchScheduleOptions, fetchTaskCandidate, scheduleProductImageUrl, updateSchedule } from '@/api/productionScheduling'
import productImagePlaceholder from '@/assets/productionScheduling/product-image-placeholder.png'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import BatchScheduleFillDialog from '@/components/productionScheduling/BatchScheduleFillDialog.vue'
import ProductionTaskSelectDialog from '@/components/productionScheduling/ProductionTaskSelectDialog.vue'
import type { ScheduleOptions, ScheduleTaskCandidate, ScheduleWriteItem } from '@/types/productionScheduling'

interface Draft extends ScheduleWriteItem {
  selected: boolean
  source_quantity: number
  production_task_id: string
  task_number: string
  product: NonNullable<ScheduleTaskCandidate['products']>[number]
}
type BatchFillValue = Partial<ScheduleWriteItem> & { internal_craft_ids?: string[]; external_craft_ids?: string[] }

const route = useRoute()
const router = useRouter()
const scheduleId = computed(() => typeof route.params.scheduleId === 'string' ? route.params.scheduleId : '')
const isEditing = computed(() => Boolean(scheduleId.value))
const loading = ref(true)
const saving = ref(false)
const taskDialogVisible = ref(false)
const changeTaskConfirmVisible = ref(false)
const batchDialogVisible = ref(false)
const selectedTasks = ref<ScheduleTaskCandidate[]>([])
const selectedTask = computed(() => selectedTasks.value[0] || null)
const options = ref<ScheduleOptions>({ crafts: [], plan_categories: [], customers: [] })
const drafts = reactive<Draft[]>([])
const etag = ref('')
const errorMessage = ref('')
const createRequestIds = ref<Record<string, string>>({})
const selectedRows = computed(() => drafts.filter(item => item.selected))
const internalCrafts = computed(() => options.value.crafts.filter(item => item.craft_type === 'INTERNAL'))
const externalCrafts = computed(() => options.value.crafts.filter(item => item.craft_type === 'EXTERNAL'))

function errorText(error: unknown) {
  if (!(error instanceof AxiosError)) return error instanceof Error ? error.message : '保存排产失败。'
  const data = error.response?.data as { error?: { message?: string } } | undefined
  if (error.response?.status === 412) return '排产已被其他人修改，请刷新后重试。'
  return data?.error?.message || '保存排产失败。'
}
function blankDraft(task: ScheduleTaskCandidate, product: NonNullable<ScheduleTaskCandidate['products']>[number]): Draft {
  return { product_line_id: product.id, planned_quantity: product.quantity, material_inbound_date: '', metal_return_date: '', sewing_return_date: '', finished_inbound_date: '', craft_ids: [], selected: true, source_quantity: product.quantity, production_task_id: task.id, task_number: task.task_number, product }
}
function selectTasks(tasks: ScheduleTaskCandidate[]) {
  selectedTasks.value = tasks
  drafts.splice(0, drafts.length, ...tasks.flatMap(task => (task.products || []).map(product => blankDraft(task, product))))
  createRequestIds.value = Object.fromEntries(tasks.map(task => [task.id, createRequestIds.value[task.id] || window.crypto.randomUUID()]))
}
function openTaskDialog() {
  if (selectedTasks.value.length && drafts.length) {
    changeTaskConfirmVisible.value = true
    return
  }
  taskDialogVisible.value = true
}
function useProductImageFallback(event: Event) {
  const image = event.currentTarget as HTMLImageElement
  if (image.dataset.fallbackApplied === 'true') return
  image.dataset.fallbackApplied = 'true'
  image.src = productImagePlaceholder
  image.classList.add('is-placeholder')
}
function confirmChangeTask() {
  changeTaskConfirmVisible.value = false
  taskDialogVisible.value = true
}
function uniqueText(values: Array<string | null | undefined>) {
  const unique = [...new Set(values.filter((value): value is string => Boolean(value)))]
  if (!unique.length) return '—'
  return unique.length > 2 ? `${unique.slice(0, 2).join('、')}等 ${unique.length} 项` : unique.join('、')
}
function dateRange(values: Array<string | null | undefined>) {
  const unique = [...new Set(values.filter((value): value is string => Boolean(value)))].sort()
  if (!unique.length) return '—'
  return unique.length === 1 ? unique[0] : `${unique[0]} 至 ${unique[unique.length - 1]}`
}
const taskNumberText = computed(() => uniqueText(selectedTasks.value.map(task => task.task_number)))
const deliveryDateText = computed(() => dateRange(selectedTasks.value.map(task => task.delivery_date)))
const orderDateText = computed(() => dateRange(selectedTasks.value.map(task => task.order_date)))
const plannedStartText = computed(() => dateRange(selectedTasks.value.map(task => task.planned_start_date)))
const plannedEndText = computed(() => dateRange(selectedTasks.value.map(task => task.planned_end_date)))
const salespersonText = computed(() => uniqueText(selectedTasks.value.map(task => task.salesperson_name)))
const followerText = computed(() => uniqueText(selectedTasks.value.flatMap(task => task.follower_names)))
function craftSummary(item: Draft, type: 'INTERNAL' | 'EXTERNAL') {
  const names = options.value.crafts.filter(craft => craft.craft_type === type && item.craft_ids.includes(craft.id)).map(craft => craft.name)
  if (!names.length) return type === 'INTERNAL' ? '选择厂内工艺' : '选择厂外工艺'
  return names.length > 2 ? `${names.slice(0, 2).join('、')}等 ${names.length} 项` : names.join('、')
}
function craftIdsByType(item: Draft, type: 'INTERNAL' | 'EXTERNAL') {
  const allowed = new Set(options.value.crafts.filter(craft => craft.craft_type === type).map(craft => craft.id))
  return item.craft_ids.filter(id => allowed.has(id))
}
function updateCraftIds(item: Draft, type: 'INTERNAL' | 'EXTERNAL', ids: string[]) {
  const other = new Set(options.value.crafts.filter(craft => craft.craft_type !== type).map(craft => craft.id))
  item.craft_ids = [...item.craft_ids.filter(id => other.has(id)), ...ids]
}
function applyBatch(value: BatchFillValue) {
  selectedRows.value.forEach(item => {
    if (value.material_inbound_date) item.material_inbound_date = value.material_inbound_date
    if (value.metal_return_date) item.metal_return_date = value.metal_return_date
    if (value.sewing_return_date) item.sewing_return_date = value.sewing_return_date
    if (value.finished_inbound_date) item.finished_inbound_date = value.finished_inbound_date
    if (value.internal_craft_ids) updateCraftIds(item, 'INTERNAL', value.internal_craft_ids)
    if (value.external_craft_ids) updateCraftIds(item, 'EXTERNAL', value.external_craft_ids)
  })
}
function validate() {
  if (!selectedTasks.value.length) return '请选择生产任务单。'
  if (!selectedRows.value.length) return '请至少勾选一个产品。'
  const emptyTask = selectedTasks.value.find(task => (
    !selectedRows.value.some(item => item.production_task_id === task.id)
  ))
  if (emptyTask) return `生产任务单 ${emptyTask.task_number} 至少勾选一个产品。`
  for (const [index, item] of selectedRows.value.entries()) {
    if (!Number.isInteger(item.planned_quantity) || item.planned_quantity < 1 || item.planned_quantity > item.source_quantity) return `第 ${index + 1} 个产品的排产数量必须是 1 到 ${item.source_quantity} 的整数。`
    if (!item.material_inbound_date || !item.metal_return_date || !item.sewing_return_date || !item.finished_inbound_date) return `第 ${index + 1} 个产品的四个计划日期均为必填。`
    if (!item.craft_ids.length) return `第 ${index + 1} 个产品至少选择一项厂内或厂外工艺。`
  }
  return ''
}
function payloadItems(taskId: string): ScheduleWriteItem[] {
  return selectedRows.value
    .filter(item => item.production_task_id === taskId)
    .map(({ selected: _selected, source_quantity: _source, production_task_id: _taskId, task_number: _taskNumber, product: _product, ...item }) => ({ ...item, craft_ids: [...item.craft_ids] }))
}
async function save() {
  const message = validate()
  if (message) { ElMessage.warning(message); return }
  saving.value = true
  errorMessage.value = ''
  try {
    if (isEditing.value) {
      const result = await updateSchedule(scheduleId.value, { source_revision_hash: selectedTask.value!.source_revision_hash, items: payloadItems(selectedTask.value!.id) }, etag.value)
      ElMessage.success('排产计划已更新')
      void router.replace(`/workshop/scheduling/${result.data.id}`)
      return
    }
    const result = await createSchedulesBatch({
      schedules: selectedTasks.value.map(task => ({
        production_task_id: task.id,
        source_revision_hash: task.source_revision_hash,
        client_request_id: createRequestIds.value[task.id],
        items: payloadItems(task.id),
      })),
    })
    ElMessage.success(`已批量生成 ${result.data.length} 张排产计划`)
    void router.replace(result.data.length === 1 ? `/workshop/scheduling/${result.data[0].id}` : '/workshop/scheduling')
  } catch (error) { errorMessage.value = errorText(error) } finally { saving.value = false }
}
async function loadEditing() {
  const result = await fetchSchedule(scheduleId.value)
  etag.value = result.etag
  const task = await fetchTaskCandidate(result.data.production_task_id)
  selectedTasks.value = [task]
  const byLine = new Map(result.data.products.map(item => [item.product_line_id, item]))
  drafts.splice(0, drafts.length, ...(task.products || []).map(product => {
    const saved = byLine.get(product.id)
    return saved ? { product_line_id: product.id, planned_quantity: saved.planned_quantity, material_inbound_date: saved.material_inbound_date, metal_return_date: saved.metal_return_date, sewing_return_date: saved.sewing_return_date, finished_inbound_date: saved.finished_inbound_date, craft_ids: saved.crafts.map(craft => craft.id), selected: true, source_quantity: product.quantity, production_task_id: task.id, task_number: task.task_number, product } : { ...blankDraft(task, product), selected: false }
  }))
}
onMounted(async () => {
  try { options.value = await fetchScheduleOptions(); if (isEditing.value) await loadEditing() }
  catch (error) { errorMessage.value = errorText(error) }
  finally { loading.value = false }
})
</script>

<template>
  <section v-loading="loading" class="schedule-page schedule-form" data-testid="production-scheduling-form">
    <header class="schedule-heading"><div><h1>{{ isEditing ? '编辑排产' : '新增排产' }}</h1><span>按产品分别填写数量、日期和工艺</span></div></header>
    <ElAlert v-if="errorMessage" type="error" :title="errorMessage" show-icon :closable="false" />
    <section class="schedule-section basic-section">
      <header><h2>基本信息</h2></header>
      <div class="basic-grid">
        <label><span>生产任务单</span><div class="source-picker"><strong :title="taskNumberText">{{ taskNumberText }}</strong><ElButton v-if="!isEditing" link type="primary" @click="openTaskDialog">{{ selectedTasks.length ? '更换' : '选择任务单' }}</ElButton></div></label>
        <label><span>交货日期</span><strong>{{ deliveryDateText }}</strong></label>
        <label><span>下单日期</span><strong>{{ orderDateText }}</strong></label>
        <label><span>PMC 参考开工</span><strong>{{ plannedStartText }}</strong></label>
        <label><span>业务员</span><strong>{{ salespersonText }}</strong></label>
        <label><span>跟单员</span><strong>{{ followerText }}</strong></label>
        <label><span>PMC 参考完工</span><strong>{{ plannedEndText }}</strong></label>
      </div>
    </section>
    <section class="schedule-section detail-section">
      <header><div><h2>产品排产明细</h2><span>共 {{ selectedRows.length }} 项</span></div><ElButton :disabled="!selectedRows.length" @click="batchDialogVisible = true">批量填入（已选择 {{ selectedRows.length }} 项）</ElButton></header>
      <div class="schedule-entry-table">
        <table>
          <colgroup><col class="sequence-col" /><col class="product-col" /><col class="source-quantity-col" /><col class="planned-quantity-col" /><col class="specification-col" /><col class="date-col" span="4" /><col class="internal-craft-col" /><col class="external-craft-col" /></colgroup>
          <thead><tr><th>序号</th><th>产品信息</th><th>订单数量</th><th>排产数量</th><th>产品规格</th><th>材料入库时间</th><th>金工回货时间</th><th>车缝回货时间</th><th>成品入库时间</th><th>厂内工艺</th><th>厂外工艺</th></tr></thead><tbody>
          <tr v-for="(item, index) in selectedRows" :key="item.product_line_id">
            <td><span class="entry-sequence">{{ index + 1 }}</span></td>
            <td>
              <div class="entry-product" :title="`${item.product.item_number || '—'}｜${item.product.product_name || '—'}｜${item.product.specification || '—'}｜${item.product.color_name || '—'}`">
                <img
                  :src="item.product.image_file_id ? scheduleProductImageUrl(item.production_task_id, item.product.image_file_id) : productImagePlaceholder"
                  :class="{ 'is-placeholder': !item.product.image_file_id }"
                  :alt="`${item.product.product_name || '产品'}图片`"
                  @error="useProductImageFallback"
                />
                <div><strong>{{ item.product.item_number || '—' }}</strong><small>{{ item.task_number }} · {{ item.product.product_name || '—' }} · {{ item.product.color_name || '—' }}</small></div>
              </div>
            </td>
            <td><strong class="entry-source-quantity">{{ item.source_quantity.toLocaleString('zh-CN') }} {{ item.product.unit_name }}</strong></td>
            <td><ElInputNumber v-model="item.planned_quantity" :min="1" :max="item.source_quantity" :step="1" :precision="0" :controls="false" /><small class="quantity-limit">最多 {{ item.source_quantity }} {{ item.product.unit_name }}</small></td>
            <td><span class="entry-specification" :title="item.product.specification || '—'">{{ item.product.specification || '—' }}</span></td>
            <td><ElDatePicker v-model="item.material_inbound_date" value-format="YYYY-MM-DD" placeholder="选择日期" popper-class="schedule-date-popper" /></td>
            <td><ElDatePicker v-model="item.metal_return_date" value-format="YYYY-MM-DD" placeholder="选择日期" popper-class="schedule-date-popper" /></td>
            <td><ElDatePicker v-model="item.sewing_return_date" value-format="YYYY-MM-DD" placeholder="选择日期" popper-class="schedule-date-popper" /></td>
            <td><ElDatePicker v-model="item.finished_inbound_date" value-format="YYYY-MM-DD" placeholder="选择日期" popper-class="schedule-date-popper" /></td>
            <td><div class="craft-select"><ElSelect :model-value="craftIdsByType(item, 'INTERNAL')" multiple collapse-tags :max-collapse-tags="0" placeholder="选择厂内工艺" popper-class="schedule-craft-popper" @update:model-value="(value: string[]) => updateCraftIds(item, 'INTERNAL', value)"><ElOption v-for="craft in internalCrafts" :key="craft.id" :label="craft.name" :value="craft.id" /></ElSelect><span v-if="craftIdsByType(item, 'INTERNAL').length" class="craft-select__summary">{{ craftSummary(item, 'INTERNAL') }}</span></div></td>
            <td><div class="craft-select"><ElSelect :model-value="craftIdsByType(item, 'EXTERNAL')" multiple collapse-tags :max-collapse-tags="0" placeholder="选择厂外工艺" popper-class="schedule-craft-popper" @update:model-value="(value: string[]) => updateCraftIds(item, 'EXTERNAL', value)"><ElOption v-for="craft in externalCrafts" :key="craft.id" :label="craft.name" :value="craft.id" /></ElSelect><span v-if="craftIdsByType(item, 'EXTERNAL').length" class="craft-select__summary">{{ craftSummary(item, 'EXTERNAL') }}</span></div></td>
          </tr>
        </tbody></table>
        <ElEmpty v-if="!drafts.length" description="请先选择生产任务单" :image-size="72" />
      </div>
    </section>
    <footer class="schedule-form-actions"><p>{{ isEditing ? '本单保存不代表开工或入库。' : '每张生产任务单分别生成一张排产计划，保存不代表开工或入库。' }}</p><div><ElButton @click="router.push(isEditing ? `/workshop/scheduling/${scheduleId}` : '/workshop/scheduling')">取消</ElButton><ElButton type="primary" :disabled="!isEditing && !selectedTasks.length" :loading="saving" @click="save">{{ isEditing ? '保存排产' : `批量生成排产（${selectedTasks.length}）` }}</ElButton></div></footer>
    <ProductionTaskSelectDialog v-model="taskDialogVisible" :selected-tasks="selectedTasks" @select="selectTasks" />
    <BatchScheduleFillDialog v-model="batchDialogVisible" :crafts="options.crafts" :selected-count="selectedRows.length" @apply="applyBatch" />
    <AppWindowDialog v-model="changeTaskConfirmVisible" title="确认更换任务单" :width="480" :height="236" class="schedule-confirm-dialog" destroy-on-close>
      <p>更换生产任务单后，当前排产明细将被清空。是否继续？</p>
      <template #footer><ElButton @click="changeTaskConfirmVisible = false">取消</ElButton><ElButton type="primary" @click="confirmChangeTask">继续更换</ElButton></template>
    </AppWindowDialog>
  </section>
</template>

<style lang="scss">@use '@/styles/productionScheduling.scss';</style>
<style scoped lang="scss">
.schedule-form {
  height: calc(100dvh - 92px);
  min-height: 0;
  overflow-y: auto;
}
</style>
