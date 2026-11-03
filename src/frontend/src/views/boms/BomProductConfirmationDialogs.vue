<script setup lang="ts">
import InquiryProductDialog from '@/components/inquiries/InquiryProductDialog.vue'
import type { InquiryItem } from '@/types/inquiry'
import type { BomDetail } from '@/types/bom'

const props = defineProps<{
  bom: BomDetail
  modelValue: boolean
  productConfirmItem: InquiryItem
  productConfirmLoading: boolean
  productConfirmError: string
  formatNumber: (value: string | number | null | undefined) => string
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  confirm: [payload: { item: InquiryItem }]
}>()

</script>

<template>
  <InquiryProductDialog

    :model-value="props.modelValue"
    scene="bom"
    :item="props.productConfirmItem"
    :context-title="`${props.bom.production_task_number} · ${props.bom.product_name_snapshot}`"
    :reviewed="props.bom.product_information_confirmed"
    :categories="[]"
    :units="[]"
    :colors="[]"
    :currencies="[]"
    :can-upload="false"
    :busy="props.productConfirmLoading"
    :close-on-confirm="false"
    :save-error="props.productConfirmError"
    @update:model-value="emit('update:modelValue', $event)"
    @confirm="emit('confirm', $event)"
  >
    <template #business>
      <div class="bom-review-context">
        <h3>本条生产任务</h3>
        <div class="bom-review-context__fields">
          <label><span>数量（只读）</span><ElInput :model-value="`${props.formatNumber(props.bom.order_quantity)} ${props.bom.product_unit_name}`" readonly aria-label="任务数量" /></label>
          <label><span>要求日期（只读）</span><ElInput :model-value="props.bom.planned_end_date || '—'" readonly aria-label="任务要求日期" /></label>
        </div>
        <h3>来源明细</h3>
        <dl>
          <div><dt>生产任务</dt><dd>{{ props.bom.production_task_number }}</dd></div>
          <div><dt>销售订单</dt><dd>{{ props.bom.source_sales_order_number || '未关联销售订单' }}</dd></div>
          <div><dt>当前 BOM</dt><dd>{{ props.bom.bom_number }}</dd></div>
        </dl>
        <h3>产品图片</h3>
        <p>沿用业务单据中的图片，本次核对不修改或覆盖图片。</p>
        <p class="bom-review-context__rule">{{ props.bom.status === 'VERIFIED' ? '当前 BOM 已确认；本次修改仅保存当前 BOM，不再次覆盖上游。' : '确认 BOM 后，按首次确认规则更新询盘、报价、销售和生产产品信息。样品、数量、价格及日期保持原值。' }}</p>
      </div>
    </template>
  </InquiryProductDialog>

</template>

<style scoped lang="scss">
@use '@/styles/crm/tokens' as token;

.bom-review-context { font-size: 13px; color: token.$crm-text-regular; h3 { margin: 20px 0 12px; font-size: 13px; line-height: 20px; color: token.$crm-text-primary; &:first-child { margin-top: 0; } } p { margin: 0; line-height: 20px; } dl { margin: 0; } dl > div { margin: 0 0 12px; } dt { color: token.$crm-text-secondary; margin-bottom: 4px; } dd { margin: 0; overflow-wrap: anywhere; } }
.bom-review-context__fields { display: grid; gap: 12px; label > span { display: block; margin-bottom: 8px; color: token.$crm-text-secondary; } :deep(.el-input__wrapper) { height: 32px; min-height: 32px; box-sizing: border-box; background: token.$crm-color-subtle; } }
.bom-review-context .bom-review-context__rule { margin-top: 20px; padding-top: 16px; border-top: 1px solid token.$crm-border-default; color: token.$crm-text-secondary; }
</style>
