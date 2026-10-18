<script setup lang="ts">
import ElDialog from '@/components/common/AppWindowDialog.vue'
import { computed, ref, watch } from 'vue'
import { InfoFilled } from '@element-plus/icons-vue'
import type { PurchaseOrderDetail } from '@/types/purchaseOrder'

const props = defineProps<{ visible: boolean; record: PurchaseOrderDetail | null; submitting: boolean }>()
const emit = defineEmits<{ cancel: []; confirm: [remark: string] }>()
const remark = ref('')
const error = ref('')
const hasReturns = computed(() => props.record?.completion?.has_returns === true)
const eligible = computed(() => !!props.record && ['SUBMITTED', 'PURCHASING'].includes(props.record.status) && props.record.completion?.can_complete === true)
const characterCount = computed(() => Array.from(remark.value).length)
watch(() => props.visible, visible => { if (visible) { remark.value = ''; error.value = '' } })
function close() { if (!props.submitting) emit('cancel') }
function submit() {
  if (props.submitting || !eligible.value) return
  const value = hasReturns.value ? remark.value.trim() : ''
  if (hasReturns.value && !value) { error.value = '请填写完成备注'; return }
  if (Array.from(value).length > 2000) { error.value = '完成备注不能超过2000字'; return }
  error.value = ''
  emit('confirm', value)
}
</script>

<template>
  <ElDialog :model-value="visible" class="purchase-order-complete-dialog" :class="{ 'no-returns': !hasReturns }"
    modal-class="purchase-order-complete-backdrop" title="完成采购" width="944px"
    append-to-body destroy-on-close :close-on-click-modal="false" :close-on-press-escape="!submitting" :before-close="close" :aria-busy="submitting">
    <p class="purchase-complete-intro">{{ hasReturns ? '已发起的到货及退货流程均已完成。填写备注后完成采购。' : '已发起的到货流程均已完成，可直接完成采购。' }}</p>
    <section v-if="record" class="purchase-complete-summary" aria-label="采购完成条件">
      <dl><div><dt>采购单号</dt><dd>{{ record.order_number || '—' }}</dd></div><div><dt>到货流程</dt><dd><span class="complete-status">已完成</span></dd></div></dl>
      <dl><div><dt>当前状态</dt><dd><span class="complete-status is-confirmed" :class="{ 'is-purchasing': record.status === 'PURCHASING' }">{{ record.status_display }}</span></dd></div><div><dt>退货情况</dt><dd><span class="complete-status">{{ hasReturns ? '退货完成' : '无退货' }}</span></dd></div></dl>
    </section>
    <div v-if="hasReturns" class="purchase-complete-remark">
      <div class="remark-heading"><label for="purchase-completion-remark">完成备注</label><span class="required" aria-hidden="true">*</span><span>有退货的采购单必须填写</span></div>
      <div class="remark-field" :class="{ 'has-error': error }">
        <textarea id="purchase-completion-remark" v-model="remark" :disabled="submitting" required aria-required="true" :aria-invalid="!!error" aria-describedby="purchase-completion-help" placeholder="请填写本次采购完成说明" @input="error = ''" />
        <span class="remark-counter">{{ characterCount }} / 2000</span>
      </div>
      <p id="purchase-completion-help" class="remark-help" :class="{ 'is-error': error }" aria-live="polite">{{ error || '最多2000字，完成后保存到采购单。' }}</p>
    </div>
    <p class="purchase-complete-notice"><ElIcon><InfoFilled /></ElIcon><span>未到货数量或后续补货不影响本次采购完成。</span></p>
    <template #footer><ElButton :disabled="submitting" @click="close">取消</ElButton><ElButton type="primary" :loading="submitting" :disabled="submitting || !eligible" @click="submit">{{ submitting ? '正在完成…' : '确认完成采购' }}</ElButton></template>
  </ElDialog>
</template>

<style lang="scss">
@use '@/styles/crm/tokens' as token;
.purchase-order-complete-backdrop { background: color-mix(in srgb, var(--erp-overlay-scrim-color) 36%, transparent); }
.el-dialog.purchase-order-complete-dialog {
  box-sizing: border-box; height: 748px; padding: 0; margin-bottom: 0; border-radius: 7px; display: flex; flex-direction: column;
  color: token.$crm-text-primary; background: token.$crm-color-surface; box-shadow: 0 8px 24px color-mix(in srgb, var(--erp-shadow-color) 16.078%, transparent); font: 18px/24px token.$crm-font-body;
  --el-color-primary: #{token.$crm-primary}; --el-color-primary-light-3: #{token.$crm-primary-light-3}; --el-border-color: #{token.$crm-border-default}; --el-fill-color-blank: #{token.$crm-color-surface}; --el-text-color-regular: #{token.$crm-text-primary};
  .el-dialog__header { height: 136px; flex-shrink: 0; box-sizing: border-box; padding: 32px 32px 0; margin: 0; }
  .el-dialog__header h2 { margin: 0; font: 700 34px/44px token.$crm-font-display; }
  .el-dialog__header p { margin: 10px 0 0; color: token.$crm-text-secondary; }
  .el-dialog__headerbtn { top: 24px; right: 24px; width: 32px; height: 32px; font-size: 22px; }
  .el-dialog__close { color: token.$crm-text-secondary; }
  .el-dialog__body { flex: 1; min-height: 0; overflow: auto; padding: 0 32px; color: inherit; font: inherit; }
  .purchase-complete-intro { margin: 0 0 12px; color: token.$crm-text-secondary; font-size: 14px; line-height: 20px; }
  .purchase-complete-summary { display: grid; grid-template-columns: 390px 414px; gap: 24px; box-sizing: border-box; min-height: 136px; padding: 22px 26px; border-radius: 6px; background: token.$crm-color-subtle; }
  .purchase-complete-summary dl { margin: 0; min-width: 0; }
  .purchase-complete-summary dl + dl { padding-left: 28px; border-left: 1px solid token.$crm-border-default; box-sizing: border-box; }
  .purchase-complete-summary dl > div { display: grid; grid-template-columns: 134px minmax(0,1fr); align-items: center; min-height: 46px; }
  .purchase-complete-summary dt { color: token.$crm-text-secondary; } .purchase-complete-summary dd { margin: 0; overflow-wrap: anywhere; }
  .complete-status { width: 104px; height: 34px; display: inline-flex; justify-content: center; align-items: center; border-radius: 999px; color: token.$crm-text-inverse; background: token.$crm-success; }
  .complete-status.is-purchasing { background: token.$crm-primary; }
  .complete-status.is-confirmed:not(.is-purchasing) { background: token.$crm-info; }
  .purchase-complete-remark { margin-top: 38px; }
  .remark-heading { height: 32px; display: flex; align-items: center; gap: 12px; margin-bottom: 12px; }
  .remark-heading label { font-size: 24px; line-height: 32px; font-weight: 700; }
  .remark-heading span { color: token.$crm-text-secondary; font-size: 16px; } .remark-heading .required { color: token.$crm-primary; font-size: 20px; }
  .remark-field { position: relative; height: 188px; }
  .remark-field textarea { width: 100%; height: 100%; box-sizing: border-box; border: 1px solid token.$crm-border-default; border-radius: 4px; background: token.$crm-color-surface; color: inherit; font: inherit; resize: none; padding: 18px 18px 34px; }
  .remark-field textarea::placeholder { color: token.$crm-text-secondary; }
  .remark-field textarea:focus { outline: 1px solid token.$crm-primary; }
  .remark-field textarea:disabled { cursor: wait; }
  .remark-field.has-error textarea { border-color: token.$crm-primary; }
  .remark-counter { position: absolute; right: 14px; bottom: 6px; font-size: 14px; color: token.$crm-text-secondary; background: token.$crm-color-surface; pointer-events: none; }
  .remark-help { margin: 8px 0 0; font-size: 16px; line-height: 24px; color: token.$crm-text-secondary; } .remark-help.is-error { color: token.$crm-primary; }
  .purchase-complete-notice { display: flex; gap: 10px; margin: 22px 0 28px; min-height: 28px; color: token.$crm-text-secondary; }
  .purchase-complete-notice .el-icon { font-size: 22px; color: token.$crm-text-muted; flex-shrink: 0; margin-top: 1px; }
  .el-dialog__footer { height: 96px; margin: 0 32px; padding: 0; border-top: 1px solid token.$crm-border-default; box-sizing: border-box; flex-shrink: 0; display: flex; align-items: center; justify-content: flex-end; gap: 16px; }
  .el-dialog__footer .el-button { width: 112px; height: 54px; margin: 0; border-radius: 5px; font: 18px token.$crm-font-body; }
  .el-dialog__footer .el-button--primary { width: 192px; }
  &.no-returns { height: 480px; } &.no-returns .purchase-complete-notice { margin-top: 32px; }
}
</style>
