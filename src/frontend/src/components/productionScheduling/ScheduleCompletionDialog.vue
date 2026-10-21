<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import type { CompleteScheduleResult, ScheduleCompletionPreview } from '@/types/productionScheduling'

const props = defineProps<{
  modelValue: boolean
  preview: ScheduleCompletionPreview | null
  submitting: boolean
  result: CompleteScheduleResult | null
  error: string
  uncertain: boolean
}>()
const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  confirm: [reason: string]
}>()
const reason = ref('')
const reasonError = ref('')
const confirmRequested = ref(false)
const busy = computed(() => props.submitting || confirmRequested.value)
const showProcess = computed(() => busy.value || props.result || props.error || props.uncertain)
const progressItems = [
  { key: 'MATERIAL', label: '材料入库' }, { key: 'METAL', label: '金工回货' },
  { key: 'SEWING', label: '车缝回货' }, { key: 'ASSEMBLY', label: '成品入库' },
] as const
const salesResultLabel = computed(() => ({
  COMPLETED: '已同步完成', ALREADY_COMPLETED: '已是完成状态',
  NOT_APPLICABLE: '无需同步', SKIPPED: '未同步',
})[props.result?.sales_sync.status || 'NOT_APPLICABLE'])
const salesResultTone = computed(() => {
  if (props.result?.sales_sync.status === 'SKIPPED') return 'warning'
  if (props.result?.sales_sync.status === 'NOT_APPLICABLE') return 'info'
  return 'success'
})
const statusNames: Record<string, string> = {
  DRAFT: '草稿', PENDING_VALIDATION: '待校验', READY: '已接单', IN_PRODUCTION: '生产中',
  CONFIRMED: '已确认', FULFILLING: '履约中', COMPLETED: '已完成', PAUSED: '已暂停', CANCELLED: '已取消',
}
function statusText(value: string | null | undefined) { return value ? statusNames[value] || value : '—' }
function statusTone(value: string | null | undefined) {
  if (value === 'COMPLETED') return 'success'
  if (value === 'PAUSED') return 'warning'
  if (value === 'CANCELLED') return 'neutral'
  return 'info'
}
function quantityText(value: number | null | undefined) {
  return typeof value === 'number' && Number.isFinite(value)
    ? value.toLocaleString('zh-CN', { maximumFractionDigits: 4 }) : '—'
}
function requestClose() { if (!busy.value) emit('update:modelValue', false) }
function beforeClose(done: () => void) { if (!busy.value) done() }
function updateVisible(value: boolean) { if (value || !busy.value) emit('update:modelValue', value) }
function confirm() {
  if (!props.preview || busy.value || props.result || props.uncertain) return
  const value = reason.value.trim()
  if (!value) { reasonError.value = '请填写完成说明。'; return }
  if (value.length > 500) { reasonError.value = '完成说明不能超过500字。'; return }
  reasonError.value = ''
  confirmRequested.value = true
  emit('confirm', value)
  void nextTick(() => { if (!props.submitting) confirmRequested.value = false })
}
watch(() => props.modelValue, visible => {
  if (visible) { reason.value = ''; reasonError.value = ''; confirmRequested.value = false }
})
watch(() => props.submitting, submitting => { if (!submitting) confirmRequested.value = false })
watch(() => [props.result, props.error, props.uncertain], () => {
  if (!props.submitting) confirmRequested.value = false
})
</script>

<template>
  <AppWindowDialog :model-value="modelValue" title="完成订单" width="960px" :before-close="beforeClose" :close-on-click-modal="!busy" :close-on-press-escape="!busy" :show-close="!busy" :minimizable="!busy" @update:model-value="updateVisible">
    <div class="schedule-completion" data-testid="schedule-completion-dialog">
      <template v-if="preview">
        <dl class="schedule-completion__identity">
          <div><dt>生产任务单</dt><dd><strong data-testid="completion-task-number">{{ preview.task.task_number || '—' }}</strong><span class="erp-list-tag" :class="`erp-list-tag--${statusTone(result ? result.production_sync.after_status : preview.task.status)}`" data-testid="completion-task-status">{{ result ? statusText(result.production_sync.after_status) : preview.task.status_display || '—' }}</span></dd></div>
          <div><dt>关联销售订单</dt><dd><strong>{{ preview.sales_order.order_number || '—' }}</strong><span class="erp-list-tag" :class="`erp-list-tag--${statusTone(result ? result.sales_sync.after_status : preview.sales_order.status)}`" data-testid="completion-sales-status">{{ result ? statusText(result.sales_sync.after_status) : preview.sales_order.status_display || '—' }}</span></dd><p v-if="preview.sales_order.reason" class="schedule-completion__note">{{ preview.sales_order.reason }}</p></div>
        </dl>
        <div class="schedule-completion__progress" aria-label="完成条件进度">
          <article v-for="item in progressItems" :key="item.key" :data-progress="item.key"><span>{{ item.label }}</span><strong>{{ preview.progress[item.key]?.display || '—' }}</strong><span class="erp-list-tag" :class="preview.progress[item.key]?.percentage === 100 ? 'erp-list-tag--success' : 'erp-list-tag--warning'">{{ preview.progress[item.key]?.percentage === 100 ? '达到完成条件' : '未达到完成条件' }}</span></article>
        </div>
        <section aria-label="产品数量核对">
          <h3>产品数量核对</h3>
          <div class="schedule-completion__table-scroll" tabindex="0" aria-label="产品数量核对表，可横向滚动">
            <table class="schedule-completion__table" data-testid="completion-products">
              <colgroup><col style="width: 140px"><col style="width: 140px"><col style="width: 80px"><col style="width: 80px"><col style="width: 140px"><col style="width: 140px"><col style="width: 64px"></colgroup>
              <thead><tr><th>产品</th><th>规格</th><th>颜色</th><th>材质</th><th class="is-number">订单要求（本任务）</th><th class="is-number">累计成品入库</th><th>单位</th></tr></thead>
              <tbody><tr v-for="product in preview.products" :key="product.schedule_product_id" :data-product-id="product.schedule_product_id"><td :title="product.product_name">{{ product.product_name || '—' }}</td><td :title="product.specification">{{ product.specification || '—' }}</td><td :title="product.color">{{ product.color || '—' }}</td><td :title="product.material">{{ product.material || '—' }}</td><td class="is-number">{{ quantityText(product.required_quantity) }}</td><td class="is-number">{{ quantityText(product.received_quantity) }}</td><td>{{ product.unit_name || '—' }}</td></tr><tr v-if="!preview.products.length"><td colspan="7" class="schedule-completion__empty">暂无产品数量信息</td></tr></tbody>
            </table>
          </div>
          <p class="schedule-completion__note">订单要求按本生产任务产品数量；入库量含已出库数量。</p>
        </section>
        <ElForm v-if="!result" label-position="top" @submit.prevent="confirm">
          <ElFormItem label="完成说明" required :error="reasonError"><ElInput v-model="reason" type="textarea" :rows="3" maxlength="500" show-word-limit placeholder="请填写完成说明" :disabled="busy || uncertain" data-testid="completion-reason" /></ElFormItem>
        </ElForm>
      </template>
      <p v-else class="schedule-completion__note">暂无可确认的排产信息，请关闭后刷新列表。</p>
      <ElAlert v-if="error" :type="uncertain ? 'warning' : 'error'" :title="uncertain ? '提交结果待核实' : '请求未提交'" :closable="false" show-icon data-testid="completion-error"><p>{{ error }}</p><p>{{ uncertain ? '生产任务和销售订单的更新结果待核实，请关闭窗口并刷新列表核实，暂不能重复提交。' : '生产任务和销售订单未更新。请修正后重试。' }}</p></ElAlert>
      <ElAlert v-else-if="uncertain" type="warning" title="提交结果待核实，请关闭窗口并刷新列表核实，暂不能重复提交。" :closable="false" show-icon />
      <section v-if="showProcess" class="schedule-completion__process" role="status" aria-live="polite" aria-label="更新过程" data-testid="completion-process">
        <h3>更新过程</h3>
        <ol>
          <li data-step="validation" data-testid="completion-step-validation"><strong>完成条件核验</strong><span class="erp-list-tag" :class="result ? 'erp-list-tag--success' : uncertain ? 'erp-list-tag--warning' : error ? 'erp-list-tag--danger' : 'erp-list-tag--info'">{{ result ? '校验通过' : uncertain ? '结果待核实' : error ? '请求未提交' : '核验并提交中' }}</span></li>
          <li data-step="production" data-testid="completion-step-production"><strong>生产任务更新</strong><span class="erp-list-tag" :class="result ? 'erp-list-tag--success' : uncertain ? 'erp-list-tag--warning' : 'erp-list-tag--info'">{{ result ? '已完成' : uncertain ? '结果待核实' : error ? '未更新' : '等待更新结果' }}</span><p v-if="result">{{ statusText(result.production_sync.before_status) }} → {{ statusText(result.production_sync.after_status) }}</p></li>
          <li data-step="sales" data-testid="completion-step-sales"><strong>销售订单同步</strong><template v-if="result"><span class="erp-list-tag" :class="`erp-list-tag--${salesResultTone}`">{{ salesResultLabel }}</span><p>{{ statusText(result.sales_sync.before_status) }} → {{ statusText(result.sales_sync.after_status) }}</p><p>{{ result.sales_sync.reason || '—' }}</p></template><span v-else class="erp-list-tag" :class="uncertain ? 'erp-list-tag--warning' : 'erp-list-tag--info'">{{ uncertain ? '结果待核实' : error ? '未更新' : '等待同步结果' }}</span></li>
        </ol>
      </section>
    </div>
    <template #footer><ElButton :disabled="busy" data-testid="completion-close" @click="requestClose">{{ result || uncertain ? '关闭' : '取消' }}</ElButton><ElButton v-if="!result && !uncertain" type="primary" :loading="busy" :disabled="!preview || busy" data-testid="completion-submit" @click="confirm">{{ error ? '重试提交' : '确认完成' }}</ElButton></template>
  </AppWindowDialog>
</template>

<style scoped lang="scss">
.schedule-completion {
  display: grid; gap: 18px; min-width: 0; color: var(--erp-color-text-primary);
  h3 { margin: 0 0 10px; font-size: 15px; line-height: 22px; font-weight: 600; }
  &__identity { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; margin: 0; }
  &__identity dt, &__note { color: var(--erp-color-text-secondary); font-size: 12px; line-height: 20px; }
  &__identity dd { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; margin: 6px 0 0; overflow-wrap: anywhere; }
  &__note { margin: 8px 0 0; }
  &__progress { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; }
  &__progress article { display: grid; justify-items: start; gap: 8px; padding: 12px; border: 1px solid var(--erp-table-border); border-radius: var(--erp-radius-control); }
  &__progress article > span:first-child { color: var(--erp-color-text-secondary); font-size: 12px; }
  &__progress article > strong { font-size: 20px; font-variant-numeric: tabular-nums; }
  &__table-scroll { min-width: 0; overflow-x: auto; border: 1px solid var(--erp-table-frame-border); border-radius: var(--erp-radius-control); }
  &__table { width: 100%; min-width: 784px; table-layout: fixed; border-spacing: 0; color: var(--erp-table-text); font-size: 13px; }
  &__table th, &__table td { height: 40px; padding: 0 10px; border-right: 1px solid var(--erp-table-border); border-bottom: 1px solid var(--erp-table-border); overflow: hidden; white-space: nowrap; text-overflow: ellipsis; text-align: left; }
  &__table th { color: var(--erp-table-header-text); background: var(--erp-table-header-background); font-size: 12px; font-weight: 500; }
  &__table td { background: var(--erp-table-background); }
  &__table th:last-child, &__table td:last-child { border-right: 0; }
  &__table tr:last-child td { border-bottom: 0; }
  &__table .is-number { text-align: right; font-variant-numeric: tabular-nums; }
  &__table &__empty { text-align: center; color: var(--erp-color-text-secondary); }
  &__process ol { display: grid; gap: 10px; margin: 0; padding: 0; list-style: none; }
  &__process li { display: flex; align-items: center; flex-wrap: wrap; gap: 8px 12px; padding: 12px; border: 1px solid var(--erp-table-border); border-radius: var(--erp-radius-control); font-size: 13px; }
  &__process li > strong { min-width: 100px; font-weight: 500; }
  &__process p { margin: 0; color: var(--erp-color-text-secondary); line-height: 20px; overflow-wrap: anywhere; }
  :deep(.el-form-item) { margin-bottom: 0; }
}
@media (max-width: 700px) {
  .schedule-completion__identity { grid-template-columns: minmax(0, 1fr); }
  .schedule-completion__progress { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
</style>
