<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { completePurchaseGroup, fetchVersionedPurchaseGroup } from '@/api/purchaseGroups'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import { useAuthStore } from '@/stores/auth'
import { compactDecimal } from '@/utils/compactDecimal'
import { materialAttributeFields, materialSpecificationValue } from '@/utils/materialAttributes'
import type { PurchaseGroup, PurchaseGroupProgressLine } from '@/types/purchaseGroup'
import { formatTime } from './purchaseOrderDetailDisplay'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const canView = computed(() => auth.user?.is_superuser === true || auth.hasPermission('procurement.view_purchaseorder'))
const canAdd = computed(() => auth.user?.is_superuser === true || auth.hasPermission('procurement.add_purchaseorder'))
const canComplete = computed(() => auth.user?.is_superuser === true || auth.moduleCan('access_control.complete_purchaseorder', 'procurement.submit_purchaseorder'))
const group = ref<PurchaseGroup | null>(null)
const groupEtag = ref('')
const loading = ref(false)
const errorMessage = ref('')
const completionVisible = ref(false)
const completionLoading = ref(false)
const completionSubmitting = ref(false)
const completionRemark = ref('')
const completionError = ref('')
const completionSuccess = ref('')
const completionBlockedReason = computed(() => group.value?.completion?.can_complete === true ? '' : group.value?.completion?.blocked_reason || '采购完成条件待核对，请刷新后重试。')
const completionRemarkTooLong = computed(() => Array.from(completionRemark.value.trim()).length > 2000)
const hoveredLineId = ref('')
const focusedLineId = ref('')
let version = 0
const statusLabels = { PENDING: '待采购', PURCHASING: '采购中', COMPLETED: '采购完成', UNKNOWN: '来源待核对' }
const batchStatusLabels = { DRAFT: '草稿', SUBMITTED: '已确认', PURCHASING: '采购中', COMPLETED: '采购完成' }
const product = computed(() => group.value?.product)
const productColor = computed(() => [product.value?.color_card, product.value?.color_name, product.value?.color_code].filter(Boolean).join(' / ') || '—')
const orderQuantity = computed(() => product.value?.order_quantity ? [product.value.order_quantity, product.value.order_unit].filter(Boolean).join(' ') : '—')
function quantityText(line: PurchaseGroupProgressLine, quantity: string | null, barCount: string | number | null | undefined): string {
  const quantityWithUnit = `${compactDecimal(quantity)} ${line.source_unit_text}`.trim()
  if (line.source_snapshot.section_type_snapshot !== 'PROFILE') return quantityWithUnit
  return `${barCount === null || barCount === undefined ? '根数待核对' : `${compactDecimal(barCount)} 根`} / ${quantityWithUnit}`
}
async function load(): Promise<void> {
  if (completionSubmitting.value || completionLoading.value) return
  const current = ++version
  group.value = null
  groupEtag.value = ''
  errorMessage.value = ''
  completionError.value = ''
  completionSuccess.value = ''
  if (!canView.value) return
  loading.value = true
  try {
    const result = await fetchVersionedPurchaseGroup(String(route.params.id))
    if (current === version) { group.value = result.data; groupEtag.value = result.etag }
  } catch (error) {
    if (current === version) errorMessage.value = (error as { response?: { data?: { error?: { message?: string } } } }).response?.data?.error?.message || '采购总单加载失败，请重试。'
  } finally { if (current === version) loading.value = false }
}
async function openCompletion(): Promise<void> {
  if (!group.value || !canComplete.value || !group.value.completion?.can_complete || completionLoading.value || completionSubmitting.value) return
  const id = group.value.id
  const current = ++version
  completionLoading.value = true
  completionError.value = ''
  completionSuccess.value = ''
  try {
    const result = await fetchVersionedPurchaseGroup(id)
    if (current !== version) return
    group.value = result.data
    groupEtag.value = result.etag
    if (completionBlockedReason.value) { completionError.value = completionBlockedReason.value; return }
    if (!result.etag) { completionError.value = '未取得最新版本，请刷新后重试。'; return }
    completionVisible.value = true
  } catch (error) {
    if (current === version) completionError.value = (error as { response?: { data?: { error?: { message?: string } } } }).response?.data?.error?.message || '采购完成条件读取失败，请重试。'
  } finally { if (current === version) completionLoading.value = false }
}
function closeCompletion(): void {
  if (!completionSubmitting.value) completionVisible.value = false
}
async function submitCompletion(): Promise<void> {
  if (!completionVisible.value || !group.value || !canComplete.value || completionBlockedReason.value || !groupEtag.value || completionRemarkTooLong.value || completionSubmitting.value) return
  const id = group.value.id
  const current = version
  completionSubmitting.value = true
  completionError.value = ''
  try {
    const result = await completePurchaseGroup(id, completionRemark.value.trim(), groupEtag.value)
    if (current !== version) return
    group.value = result.data
    groupEtag.value = result.etag
    completionVisible.value = false
    completionRemark.value = ''
    completionSuccess.value = '采购总单已完成，材料进度保留实际入库情况，仍可新增采购批次。'
  } catch (error) {
    if (current !== version) return
    const response = (error as { response?: { status?: number; data?: { error?: { message?: string } } } }).response
    groupEtag.value = ''
    if (response?.status === 412 || response?.status === 409) {
      try {
        const latest = await fetchVersionedPurchaseGroup(id)
        if (current !== version) return
        group.value = latest.data
        groupEtag.value = latest.etag
        completionError.value = completionBlockedReason.value || '采购总单已更新，请核对最新信息后再次确认；备注已保留。'
      } catch {
        if (current === version) completionError.value = '采购总单已更新，但最新信息读取失败。请关闭弹窗并刷新后重试，备注已保留。'
      }
    } else {
      completionError.value = `${response?.data?.error?.message || '完成采购未成功。'} 请关闭弹窗并刷新后核对，备注已保留。`
    }
  } finally { if (current === version) completionSubmitting.value = false }
}
watch(() => route.params.id, () => {
  completionVisible.value = false
  completionLoading.value = false
  completionSubmitting.value = false
  completionRemark.value = ''
  void load()
}, { immediate: true })
onBeforeUnmount(() => { version++ })
</script>

<template>
  <section class="group-detail erp-glass-detail" data-testid="purchase-group-detail" v-loading="loading">
    <header><div><h1>采购总单</h1><span>{{ group?.group_number }}</span></div><div class="actions">
      <ElButton @click="router.push({ name: 'purchase-orders', query: { view: 'groups' } })">返回总单列表</ElButton>
      <ElButton v-if="canView" :disabled="completionLoading || completionSubmitting" @click="load">刷新进度</ElButton>
      <ElTooltip v-if="group?.completion && canComplete" :content="completionBlockedReason" :disabled="!completionBlockedReason" placement="bottom"><span><ElButton data-testid="purchase-group-complete" :loading="completionLoading" :disabled="!!completionBlockedReason || completionSubmitting" @click="openCompletion">完成采购</ElButton></span></ElTooltip>
      <ElButton v-if="group && canAdd" data-testid="purchase-group-add-batch" type="primary" :disabled="group.progress.status === 'UNKNOWN'" @click="router.push({ name: 'purchase-batch-create', params: { groupId: group.id } })">新增采购批次</ElButton>
    </div></header>
    <ElAlert v-if="!canView" title="当前账号无权查看采购总单。" type="warning" :closable="false" />
    <ElAlert v-if="errorMessage" :title="errorMessage" type="error" :closable="false"><ElButton link @click="load">重新加载</ElButton></ElAlert>
    <ElAlert v-if="completionError && !completionVisible" :title="completionError" type="error" :closable="false" />
    <ElAlert v-if="completionSuccess" :title="completionSuccess" type="success" :closable="false" />
    <template v-if="group">
      <dl class="group-summary">
        <div><dt>生产订单</dt><dd>{{ group.production_task_number_snapshot }}</dd></div>
        <div><dt>销售订单 / 客户</dt><dd>{{ group.sales_order_number_snapshot }} · {{ group.customer_name_snapshot }}</dd></div>
        <div><dt>产品</dt><dd>{{ product?.product_name || '来源待核对' }}</dd></div>
        <div><dt>规格</dt><dd>{{ product?.specification || '—' }}</dd></div>
        <div><dt>颜色</dt><dd>{{ productColor }}</dd></div>
        <div><dt>材质</dt><dd>{{ product?.material || '—' }}</dd></div>
        <div><dt>订单量</dt><dd>{{ orderQuantity }}</dd></div>
        <div><dt>订单交期</dt><dd>{{ group.order_delivery_date || '—' }}</dd></div>
        <div><dt>采购批次</dt><dd>{{ group.batches.length }} 批</dd></div>
        <div><dt>材料达标</dt><dd>{{ group.progress.satisfied_line_count }}/{{ group.progress.line_count }} 项 · {{ statusLabels[group.display_status ?? group.progress.status] }}</dd></div>
        <div v-if="group.manual_completed_at" class="group-completion-record"><dt>完成记录</dt><dd>{{ group.manual_completed_by_name || '—' }} · {{ formatTime(group.manual_completed_at) }}<span v-if="group.manual_completion_remark"> · {{ group.manual_completion_remark }}</span></dd></div>
      </dl>
      <ElAlert v-if="group.progress.status === 'UNKNOWN'" title="历史来源或数量存在缺口，进度待核对，暂不能追加批次。" type="warning" :closable="false" />
      <section class="group-content-card"><h2>材料采购进度</h2>
        <div class="group-table-frame"><table class="group-table progress-table"><colgroup><col v-for="(width, index) in [48,106,208,220,180,140,140,140,150]" :key="index" :style="{ width: `${width}px` }" /></colgroup>
          <thead><tr><th>序号</th><th>分类</th><th>物料信息</th><th>规格</th><th>BOM 建议量</th><th>累计采购</th><th>正在采购</th><th>合格入库</th><th>入库进度</th></tr></thead>
          <tbody><tr v-for="line in group.progress.lines" :key="line.id" :data-line-id="line.id" @mouseenter="hoveredLineId = line.id" @mouseleave="hoveredLineId = ''">
            <td>{{ line.line_number }}</td><td>{{ line.source_snapshot.category_snapshot || '—' }}</td><td><strong>{{ line.source_snapshot.part_name_snapshot || line.source_snapshot.material_snapshot || line.source_snapshot.raw_material_snapshot }}</strong><small>{{ line.source_snapshot.raw_material_snapshot }}</small></td>
            <td><ElTooltip placement="top" :show-after="80" :visible="hoveredLineId === line.id || focusedLineId === line.id" :teleported="true"><template #content><div class="material-attribute-tooltip"><div v-for="field in materialAttributeFields(line.source_snapshot)" :key="field.key"><span>{{ field.label }}</span><strong>{{ field.value }}</strong></div><div v-if="!materialAttributeFields(line.source_snapshot).length">暂无物料属性</div><div v-if="line.source_snapshot.section_type_snapshot === 'PROFILE'"><span>采购原长</span><strong>{{ line.source_snapshot.raw_bar_length_m == null ? '待核对' : `${compactDecimal(line.source_snapshot.raw_bar_length_m)} 米/根` }}</strong></div></div></template><span class="material-detail" tabindex="0" :aria-label="`查看材料属性：${materialSpecificationValue(line.source_snapshot)}`" @focus="focusedLineId = line.id" @blur="focusedLineId = ''" @keydown.esc="focusedLineId = ''; hoveredLineId = ''">{{ materialSpecificationValue(line.source_snapshot) }}</span></ElTooltip></td>
            <td>{{ quantityText(line, line.required_quantity, line.source_snapshot.suggested_bar_count) }}</td><td>{{ quantityText(line, line.purchased_quantity, line.purchased_bar_count) }}</td><td>{{ quantityText(line, line.in_progress_quantity ?? '待核对', line.in_progress_bar_count) }}</td><td>{{ quantityText(line, line.accepted_quantity, line.accepted_bar_count) }}</td>
            <td :class="{ satisfied: line.is_satisfied, unknown: line.progress_percent === null }"><strong>{{ line.progress_percent === null ? '来源待核对' : `${compactDecimal(line.progress_percent)}%` }}</strong></td>
          </tr><tr v-if="!group.progress.lines.length"><td colspan="9" class="empty">暂无材料明细，来源待核对</td></tr></tbody>
        </table></div>
      </section>
      <section class="group-content-card"><h2>采购批次 <small>{{ group.batches.length }} 批</small></h2><div class="group-table-frame"><table class="group-table batch-table"><thead><tr><th>批次</th><th>采购单号</th><th>批次类型</th><th>履约状态</th><th>采购金额</th><th>操作</th></tr></thead><tbody>
        <tr v-for="batch in group.batches" :key="batch.id"><td>第 {{ batch.batch_number }} 批</td><td>{{ batch.order_number }}</td><td>{{ batch.batch_type === 'SUPPLEMENT' ? '补料' : '正常采购' }}</td><td>{{ batchStatusLabels[batch.display_status ?? batch.status] }}</td><td>{{ compactDecimal(batch.total_amount) || '—' }} {{ batch.currency_code_snapshot }}</td><td><ElButton link type="primary" @click="router.push({ name: 'purchase-order-detail', params: { id: batch.id } })">查看明细</ElButton><ElButton v-if="batch.status === 'DRAFT'" link @click="router.push({ name: 'purchase-order-confirm', params: { id: batch.id } })">编辑 / 确认</ElButton></td></tr>
        <tr v-if="!group.batches.length"><td colspan="6" class="empty">暂无批次，可从本总单选择材料创建首批采购。</td></tr>
      </tbody></table></div></section>
    </template>
    <AppWindowDialog :model-value="completionVisible" title="完成采购" :width="680" :close-on-click-modal="false" :close-on-press-escape="!completionSubmitting" :minimizable="false" :before-close="closeCompletion" destroy-on-close @update:model-value="value => { if (!value) closeCompletion() }">
      <div class="group-completion-form">
        <p>确认完成采购总单 <strong>{{ group?.group_number }}</strong>？</p>
        <p>已有到货且已发起的质检、退货均处理完毕后，即使未全部到货或未达到 BOM 建议量，也可以完成采购。全部入库自动完成后，也可在此记录完成人、时间和备注。材料进度保留实际入库情况，完成后仍可新增采购批次。</p>
        <ElAlert v-if="completionError || completionBlockedReason" :title="completionError || completionBlockedReason" type="warning" :closable="false" />
        <ElForm label-position="top"><ElFormItem label="完成备注（可选）" :error="completionRemarkTooLong ? '完成备注不能超过 2000 个字符。' : ''"><ElInput v-model="completionRemark" data-testid="purchase-group-completion-remark" type="textarea" :rows="4" :maxlength="2000" show-word-limit :disabled="completionSubmitting" placeholder="可记录本次完成采购的说明" /></ElFormItem></ElForm>
      </div>
      <template #footer><ElButton :disabled="completionSubmitting" @click="closeCompletion">取消</ElButton><ElButton data-testid="purchase-group-completion-submit" type="primary" :loading="completionSubmitting" :disabled="!canComplete || !!completionBlockedReason || !groupEtag || completionRemarkTooLong" @click="submitCompletion">确认完成</ElButton></template>
    </AppWindowDialog>
  </section>
</template>

<style scoped lang="scss">
@use '@/styles/procurementGroups';
@use '@/styles/theme/detail' as detail;
.group-detail { padding: 14px; min-width: 0; color: var(--erp-color-text-primary); font-family: var(--erp-font-body); display: flex; flex-direction: column; gap: 14px; }
header, header > div, .actions { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; }
header { justify-content: space-between; }
h1 { margin: 0; font-size: 36px; line-height: 44px; font-weight: 700; }
h2 { margin: 0 0 10px; font-size: 16px; } h2 small { font-size: 12px; font-weight: 400; }
.group-summary { @include detail.surface; display: grid; grid-template-columns: repeat(5,minmax(0,1fr)); gap: 14px; padding: 16px; margin: 0; }
.group-content-card { @include detail.surface; padding: 14px 16px 16px; }
.group-completion-record { grid-column: 1 / -1; }
.group-completion-form { display: flex; flex-direction: column; gap: 16px; }
.group-completion-form p { margin: 0; line-height: 24px; }
dt { color: var(--erp-color-text-secondary); font-size: 12px; line-height: 18px; margin-bottom: 4px; } dd { margin: 0; font-size: 13px; line-height: 20px; overflow-wrap: anywhere; }
.progress-table { width: 1332px; min-width: 100%; }
.progress-table th:first-child, .progress-table td:first-child { padding-inline: 8px; white-space: nowrap; text-align: center; }
.material-detail { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--erp-color-text-secondary); }
.material-attribute-tooltip { min-width: 180px; line-height: 24px; font-size: 14px; }
.material-attribute-tooltip > div { display: flex; gap: 8px; }
.material-attribute-tooltip span { color: var(--erp-color-text-secondary); min-width: 42px; }
.batch-table { width: 100%; min-width: 900px; }
@media(max-width: 900px) { .group-summary { grid-template-columns: repeat(2,minmax(0,1fr)); } }
</style>
