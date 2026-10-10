<script setup lang="ts">
import ElDialog from '@/components/common/AppWindowDialog.vue'
import { computed, ref } from 'vue'
import { Check, InfoFilled } from '@element-plus/icons-vue'
import type { PurchaseReturn } from '@/types/purchaseReturn'
import { materialAttributeFields, materialSpecificationValue } from '@/utils/materialAttributes'

const props = defineProps<{ visible: boolean; record: PurchaseReturn | null; submitting: boolean; action?: 'confirm' | 'complete' | 'view' }>()
const isComplete = computed(() => props.action === 'complete')
const isView = computed(() => props.action === 'view')
const confirmationDone = computed(() => !!props.record && props.record.status !== 'QUALITY_GENERATED')
const completionDone = computed(() => !!props.record && props.record.status === 'COMPLETED')
const hoveredRowId = ref('')
const title = computed(() => isView.value ? '退货明细' : isComplete.value ? '完成退货' : '确认退货')
const emit = defineEmits<{ cancel: []; confirm: [] }>()
function close() { if (!props.submitting) emit('cancel') }
function quantity(value: string): string {
  if (!/^\d{1,14}(\.\d{1,4})?$/.test(value)) return '—'
  const [whole = '0', decimal = ''] = value.split('.')
  const fraction = decimal.replace(/0+$/, '')
  return BigInt(whole).toLocaleString('zh-CN') + (fraction ? '.' + fraction : '')
}
function time(value: string | null): string {
  const date = value ? new Date(value) : null
  return date && Number.isFinite(date.getTime()) ? new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }).format(date) : '—'
}
</script>

<template>
  <ElDialog :model-value="visible" class="purchase-return-detail-confirm" :class="{ 'is-complete': isComplete, 'is-view': isView }" modal-class="purchase-return-detail-backdrop"
    :title="title" width="min(1540px, calc(100vw - 32px))" :center-on-resize="true" align-center append-to-body destroy-on-close
    :close-on-click-modal="false" :close-on-press-escape="!submitting" :before-close="close" :aria-busy="submitting">
    <template v-if="record">
      <div class="return-detail-layout">
        <aside class="return-status-rail" aria-label="退货处理流程">
          <ol>
            <li class="done"><span class="step-circle"><ElIcon><Check /></ElIcon></span><div><strong>品质生成</strong><small>{{ record.generated_by_name || '—' }}</small><time>{{ time(record.created_at) }}</time></div></li>
            <li :class="{ done: confirmationDone, current: !isView && !isComplete }" :aria-current="!isView && !isComplete ? 'step' : undefined"><span class="step-circle"><ElIcon v-if="confirmationDone"><Check /></ElIcon><template v-else>2</template></span><div><strong>确认退货</strong><small>{{ record.confirmed_by_name || '待采购确认' }}</small><time>{{ time(record.confirmed_at) }}</time></div></li>
            <li :class="{ done: completionDone, current: isComplete }" :aria-current="isComplete ? 'step' : undefined"><span class="step-circle"><ElIcon v-if="completionDone"><Check /></ElIcon><template v-else>3</template></span><div><strong>退货完成</strong><small>{{ record.completed_by_name || '待完成' }}</small><time>{{ time(record.completed_at) }}</time></div></li>
          </ol>
        </aside>
        <section class="return-detail-content">
          <section class="return-confirm-summary" aria-label="退货基础信息">
            <header><div><h3>基础信息</h3><span>{{ record.return_number || '—' }}</span></div><span class="return-confirm-status" :class="`status-${record.status}`">{{ record.status_display || '—' }}</span></header>
            <dl>
              <div><dt>采购单号</dt><dd>{{ record.order_number || '—' }}</dd></div>
              <div><dt>入库单号</dt><dd>{{ record.inbound_number || '—' }}</dd></div>
              <div><dt>生产任务单</dt><dd>{{ record.production_task_number || '—' }}</dd></div>
              <div class="supplier-field"><dt>供应商</dt><dd>{{ record.supplier_name || '—' }}</dd></div>
              <div><dt>采购确认</dt><dd>{{ record.confirmed_by_name || '—' }}　{{ time(record.confirmed_at) }}</dd></div>
              <div><dt>完成退货</dt><dd>{{ record.completed_by_name || '—' }}　{{ time(record.completed_at) }}</dd></div>
            </dl>
          </section>
          <section class="return-material-section">
            <div class="return-confirm-materials-title"><h3>退货材料</h3><span>共 {{ record.lines.length }} 项</span></div>
            <div class="return-confirm-materials" tabindex="0" aria-label="只读退货材料">
              <table><colgroup><col v-for="(width,i) in [250,220,200,120,80,220]" :key="i" :style="{ width: width / 1090 * 100 + '%' }" /></colgroup><thead><tr><th v-for="label in ['材料名称','规格','品名','退货数量','单位','品质备注']" :key="label" scope="col">{{ label }}</th></tr></thead>
                <tbody><tr v-for="line in record.lines" :key="line.id" @mouseenter="hoveredRowId = line.id" @mouseleave="hoveredRowId = ''"><td><span>{{ line.part_name || line.material || '未命名物料' }}</span></td><td class="specification-cell"><ElTooltip placement="top" :show-after="80" :visible="hoveredRowId === line.id" :teleported="true"><template #content><div class="material-attribute-tooltip"><div v-for="field in materialAttributeFields(line)" :key="field.key"><span>{{ field.label }}</span><strong>{{ field.value }}</strong></div></div></template><span>{{ materialSpecificationValue(line) }}</span></ElTooltip></td><td>{{ line.product_name || '—' }}</td><td class="return-confirm-quantity">{{ line.return_bar_count != null ? `${line.return_bar_count} 根 / ` : '' }}{{ quantity(line.quantity) }}<small v-if="line.raw_bar_length_m" style="display:block">{{ line.raw_bar_length_m }} 米/根</small></td><td>{{ line.unit || '—' }}</td><td>{{ line.quality_remark || '—' }}</td></tr><tr v-if="!record.lines.length"><td colspan="6">暂无退货材料明细</td></tr></tbody>
              </table>
            </div>
          </section>
          <p class="return-confirm-notice"><ElIcon><InfoFilled /></ElIcon><span>{{ isView ? '此弹窗仅展示退货记录，不会修改入库数量或退货状态。' : isComplete ? '请确认上述材料已实际退回供应商；完成后将记录操作人和完成时间。' : '本次确认仅更新退货状态，不改变已入库数量。' }}</span></p>
        </section>
      </div>
    </template>
    <template #footer><ElButton :disabled="submitting" @click="close">{{ isView ? '关闭' : '取消' }}</ElButton><ElButton v-if="!isView" type="primary" :loading="submitting" :disabled="submitting || !record || record.status !== (isComplete ? 'PROCUREMENT_CONFIRMED' : 'QUALITY_GENERATED') || !record.lines.length" @click="emit('confirm')">{{ submitting ? '正在确认…' : isComplete ? '确认退货完成' : '确认退货' }}</ElButton></template>
  </ElDialog>
</template>

<style lang="scss">
@use '@/styles/crm/tokens' as token;
.purchase-return-detail-backdrop { background: rgb(31 29 24 / 36%); }
.el-dialog.purchase-return-detail-confirm {
  box-sizing: border-box; height: min(720px, calc(100dvh - 48px)); max-height: calc(100dvh - 48px); padding: 0; margin: auto; border-radius: 7px; display: flex; flex-direction: column;
  background: token.$crm-color-surface; color: token.$crm-text-primary; box-shadow: 0 8px 24px #00000029; font: 14px/20px token.$crm-font-body;
  --el-color-primary: #{token.$crm-primary}; --el-color-primary-light-3: #{token.$crm-primary-light-3}; --el-border-color: #{token.$crm-border-default}; --el-fill-color-blank: #{token.$crm-color-surface}; --el-text-color-regular: #{token.$crm-text-primary};
  &[aria-busy=true] .el-dialog__headerbtn { cursor: wait; }
  .el-dialog__body { flex: 1; min-height: 0; overflow: auto; padding: 18px 20px 0; color: inherit; font: inherit; }
  .return-detail-layout { display: grid; grid-template-columns: 168px minmax(0, 1fr); gap: 18px; height: 100%; min-height: 0; }
  .return-status-rail { box-sizing: border-box; min-height: 0; padding: 24px 14px; border-right: 1px solid token.$crm-border-default; border-radius: 5px; background: token.$crm-color-subtle; }
  .return-status-rail ol { height: 100%; padding: 0; margin: 0; list-style: none; }
  .return-status-rail li { position: relative; display: grid; grid-template-columns: 28px minmax(0, 1fr); column-gap: 12px; min-height: 132px; color: token.$crm-text-muted; }
  .return-status-rail li:not(:last-child)::before { position: absolute; top: 28px; bottom: 0; left: 13px; width: 2px; background: token.$crm-border-default; content: ''; }
  .return-status-rail li.done::before { background: token.$crm-info; }
  .step-circle { position: relative; z-index: 1; width: 28px; height: 28px; border-radius: 50%; display: inline-flex; align-items: center; justify-content: center; background: token.$crm-text-muted; color: token.$crm-text-inverse; font-size: 13px; }
  .step-circle .el-icon { font-size: 16px; }
  .return-status-rail li > div { min-width: 0; padding-top: 2px; }
  .return-status-rail strong { display: block; color: token.$crm-text-secondary; font-size: 14px; font-weight: 600; line-height: 22px; }
  .return-status-rail small, .return-status-rail time { display: block; overflow: hidden; color: token.$crm-text-muted; font-size: 12px; line-height: 20px; text-overflow: ellipsis; white-space: nowrap; }
  .return-status-rail small { margin-top: 6px; }
  .return-status-rail .done strong { color: token.$crm-info; } .return-status-rail .done .step-circle { background: token.$crm-info; }
  .return-status-rail .current strong { color: token.$crm-primary; } .return-status-rail .current .step-circle { background: token.$crm-primary; }
  .return-detail-content { min-width: 0; min-height: 0; display: flex; flex-direction: column; gap: 16px; }
  .material-attribute-tooltip { min-width: 180px; line-height: 24px; font-size: 14px; }
  .return-confirm-materials .specification-cell { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .return-confirm-materials .specification-cell > span { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .material-attribute-tooltip > div { display: flex; gap: 8px; }
  .material-attribute-tooltip span { color: #b9c0cc; min-width: 42px; }
  .return-confirm-summary { box-sizing: border-box; flex: none; padding: 16px 18px 8px; border: 1px solid token.$crm-border-default; border-radius: 5px; background: token.$crm-color-surface; }
  .return-confirm-summary > header { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding-bottom: 12px; border-bottom: 1px solid token.$crm-border-subtle; }
  .return-confirm-summary > header > div { min-width: 0; display: flex; align-items: baseline; gap: 14px; }
  .return-confirm-summary h3 { margin: 0; font-size: 18px; line-height: 24px; }
  .return-confirm-summary header div > span { overflow: hidden; color: token.$crm-text-secondary; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
  .return-confirm-status { display: inline-flex; align-items: center; justify-content: center; min-width: 176px; max-width: 260px; height: 24px; padding: 0 12px; border-radius: 999px; background: token.$crm-info; color: token.$crm-text-inverse; font-size: 12px; line-height: 18px; white-space: nowrap; }
  .return-confirm-summary dl { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 0 22px; margin: 8px 0 0; }
  .return-confirm-summary dl > div { min-width: 0; display: grid; grid-template-columns: 86px minmax(0, 1fr); align-items: center; min-height: 42px; border-bottom: 1px solid token.$crm-border-subtle; }
  .return-confirm-summary dl > div:nth-last-child(-n + 3) { border-bottom: 0; }
  .return-confirm-summary dt { color: token.$crm-text-secondary; font-size: 12px; }
  .return-confirm-summary dd { min-width: 0; overflow: hidden; margin: 0; font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }
  .return-material-section { min-height: 0; flex: 1; display: flex; flex-direction: column; }
  .return-confirm-materials-title { height: 26px; flex: none; margin: 0 0 10px; display: flex; align-items: center; gap: 12px; }
  .return-confirm-materials-title h3 { margin: 0; font-size: 18px; line-height: 24px; }
  .return-confirm-materials-title span { color: token.$crm-text-secondary; font-size: 12px; }
  .return-confirm-materials { box-sizing: border-box; min-height: 116px; flex: 1; overflow: auto; border: 1px solid token.$crm-border-default; border-radius: 5px; }
  .return-confirm-materials table { width: 100%; table-layout: fixed; border-collapse: separate; border-spacing: 0; }
  .return-confirm-materials th, .return-confirm-materials td { box-sizing: border-box; padding: 0 12px; text-align: left; overflow-wrap: anywhere; border-right: 1px solid token.$crm-border-subtle; border-bottom: 1px solid token.$crm-border-subtle; }
  .return-confirm-materials th { position: sticky; top: 0; z-index: 1; height: 34px; color: token.$crm-text-secondary; background: token.$crm-color-subtle; font-size: 12px; font-weight: 400; }
  .return-confirm-materials td { height: 40px; font-size: 13px; } .return-confirm-materials th:last-child,.return-confirm-materials td:last-child { border-right: 0; }
  .return-confirm-materials tbody tr:last-child td { border-bottom: 0; }
  .return-confirm-notice { min-height: 20px; flex: none; display: flex; align-items: flex-start; gap: 8px; margin: 0 0 14px; color: token.$crm-text-secondary; font-size: 12px; line-height: 20px; }
  .return-confirm-notice .el-icon { flex-shrink: 0; margin-top: 2px; color: token.$crm-text-muted; font-size: 16px; }
  .el-dialog__footer { box-sizing: border-box; height: 56px; flex-shrink: 0; display: flex; align-items: center; justify-content: flex-end; gap: 12px; padding: 0; margin: 0 20px; border-top: 1px solid token.$crm-border-default; }
  .el-dialog__footer .el-button { min-width: 88px; height: 32px; margin: 0; border-radius: 5px; font: 14px token.$crm-font-body; }
  .el-dialog__footer .el-button--primary { min-width: 112px; }
  .return-confirm-status.status-PROCUREMENT_CONFIRMED { background: token.$crm-primary; }
  .return-confirm-status.status-COMPLETED { background: token.$crm-success; }
  &.is-complete .el-dialog__footer .el-button--primary { min-width: 132px; }
}
@media (max-width: 980px) {
  .el-dialog.purchase-return-detail-confirm {
    .el-dialog__body { padding-right: 16px; padding-left: 16px; }
    .return-detail-layout { grid-template-columns: 148px minmax(0, 1fr); gap: 14px; }
    .return-status-rail { padding-right: 10px; padding-left: 10px; }
    .return-confirm-summary dl { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .return-confirm-summary dl > div:nth-last-child(-n + 3) { border-bottom: 1px solid token.$crm-border-subtle; }
    .return-confirm-summary dl > div:nth-last-child(-n + 2) { border-bottom: 0; }
    .return-confirm-materials table { min-width: 760px; }
  }
}
</style>
