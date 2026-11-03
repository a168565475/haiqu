<script setup lang="ts">
import ProtectedImage from '@/components/common/ProtectedImage.vue'
import { computed, ref } from 'vue'
import SampleSection from './SampleSection.vue'
import SampleReadonlyField from './SampleReadonlyField.vue'
import type { SampleDetail } from '@/types/sample'

const props = withDefaults(defineProps<{ sample: SampleDetail; showCustomer?: boolean }>(), { showCustomer: true })
const selectedProductId = ref('')
const product = computed(() => props.sample.products?.find(item => item.id === selectedProductId.value) || props.sample.products?.[0])
const unit = computed(() => product.value?.product_selection_snapshot?.unit_name
  || props.sample.items?.find(item => item.sample_product === product.value?.id)?.unit_code || 'PCS')
const color = computed(() => (product.value?.details || [])
  .filter(detail => detail.color_card || detail.color_code || detail.color_name)
  .map(detail => [detail.color_card || '—', detail.color_code || '—', detail.color_name || '—'].join(' / '))
  .join('；') || product.value?.color || product.value?.product_selection_snapshot?.color_name || '—')
const basicFields = computed(() => [
  { label: '打样单号', value: props.sample.request_number },
  { label: props.sample.source_quotation_version ? '来源报价' : '来源询盘', value: props.sample.source_quotation_number || props.sample.source_inquiry_number },
  ...(props.showCustomer ? [
    { label: '客户', value: props.sample.customer_name },
    { label: '联系人', value: props.sample.customer_contact_name },
  ] : []),
  { label: '业务员', value: props.sample.owner?.display_name },
  { label: '样品类型', value: props.sample.sample_type_display },
  { label: '寄送方式', value: props.sample.shipping_method_display },
  { label: '交货方式', value: props.sample.delivery_batch_display },
  { label: '是否返单', value: props.sample.is_repeat_order == null ? '—' : props.sample.is_repeat_order ? '是' : '否' },
  { label: '下单日期', value: props.sample.order_date },
  { label: '期望样品完成日期', value: props.sample.sample_due_date || props.sample.requested_due_at?.slice(0, 10) },
])
const dimensionFields = computed(() => [
  { label: '长（cm）', value: product.value?.length_cm },
  { label: '扶手宽（cm）', value: product.value?.armrest_width_cm },
  { label: '坐宽（cm）', value: product.value?.seat_width_cm },
  { label: '背高（cm）', value: product.value?.back_height_cm },
  { label: '坐高（cm）', value: product.value?.seat_height_cm },
])
</script>

<template>
  <div class="application-summary">
    <SampleSection title="基础信息" class="summary-basic"><div class="basic-fields"><SampleReadonlyField v-for="field in basicFields" :key="field.label" :label="field.label" :value="field.value" /></div></SampleSection>
    <div class="summary-columns">
      <SampleSection title="样品信息" class="summary-product">
          <div class="product-fields">
            <SampleReadonlyField label="类别" :value="product?.category_name" />
            <div v-if="(sample.products?.length || 0) > 1" class="product-selector"><label for="review-product">品名</label><ElSelect id="review-product" aria-label="查看样品" :model-value="product?.id" @update:model-value="selectedProductId = $event"><ElOption v-for="item in sample.products" :key="item.id" :value="item.id" :label="item.product_name" /></ElSelect></div>
            <SampleReadonlyField v-else label="品名" :value="product?.product_name || sample.item_summary?.text" />
            <SampleReadonlyField label="规格" :value="product?.specification" />
            <SampleReadonlyField label="单位" :value="unit" />
            <SampleReadonlyField label="材质" :value="product?.material_snapshot || product?.product_selection_snapshot?.material" />
            <SampleReadonlyField label="色卡 / 色号 / 颜色" :value="color" />
            <SampleReadonlyField label="打样数量" :value="product ? `${product.total_sample_quantity} ${unit}` : '—'" />
            <div class="dimension-fields"><SampleReadonlyField v-for="field in dimensionFields" :key="field.label" :label="field.label" :value="field.value" /></div>
            <div class="requirements"><span>备注（选填）</span><p>{{ sample.purpose || '—' }}</p></div>
          </div>
      </SampleSection>
      <div class="summary-aside">
        <SampleSection title="参考图片" class="summary-reference"><ProtectedImage v-if="sample.reference_image" class="reference-image" :src="`/api/v1/sample-requests/${sample.id}/business-files/${sample.reference_image}/`" alt="申请参考图片" /><div v-else class="reference-empty"><strong>暂无参考图片</strong><span>本项为选填</span></div></SampleSection>
      </div>
    </div>
  </div>
</template>

<style scoped lang="scss">
@use '@/styles/crm/tokens' as token;
@use '@/styles/theme/detail';
.application-summary { display: flex; min-width: 0; flex-direction: column; gap: 12px; }
.summary-basic { min-width: 0; }
.summary-basic :deep(h2), .summary-product :deep(h2) { margin-bottom: 12px; }
.basic-fields { display: grid; max-width: 1330px; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 12px 20px; }
.application-summary :deep(.sample-readonly-field) { width: 250px; max-width: 100%; height: 58px; font-size: 13px; }
.application-summary :deep(.field-label), .product-selector label, .requirements > span { height: 20px; font-size: 12px; font-weight: 500; line-height: 20px; }
.summary-columns { display: grid; grid-template-columns: minmax(0, 1fr) 420px; align-items: start; gap: 12px; }
.summary-product { min-width: 0; }
.product-fields { display: grid; min-width: 0; grid-template-columns: repeat(auto-fit, minmax(min(250px, 100%), 250px)); align-items: start; gap: 12px 20px; }
.product-selector { min-width: 0; height: 58px; }
.product-selector label { display: block; margin-bottom: 6px; }
.product-selector :deep(.el-select) { width: 250px; max-width: 100%; }
.product-selector :deep(.el-select__wrapper) { min-height: 32px; }
.dimension-fields { display: contents; }
.requirements { grid-column: 1 / -1; font-size: 13px; line-height: 20px; }
.requirements p { @include detail.inset; box-sizing: border-box; min-height: 78px; margin: 6px 0 0; padding: 8px 12px; white-space: pre-wrap; overflow-wrap: anywhere; }
.summary-aside, .summary-reference { min-width: 0; }
.reference-image { display: block; width: 100%; height: 148px; object-fit: contain; }
.summary-reference :deep(h2) { margin-bottom: 12px; }
.reference-empty { display: flex; height: 148px; align-items: center; justify-content: center; flex-direction: column; gap: 4px; border: 1px dashed token.$crm-border-default; border-radius: 4px; background: transparent; line-height: 22px; }
.reference-empty strong { font-size: 14px; font-weight: 500; }
.reference-empty span { color: token.$crm-text-muted; font-size: 12px; line-height: 22px; }
@media (max-width: 1440px) { .product-fields { column-gap: 16px; } }
@media (max-width: 1200px) { .summary-columns { grid-template-columns: 1fr; } }
@media (max-width: 1100px) { .basic-fields { grid-template-columns: repeat(3, minmax(0, 250px)); } }
@media (max-width: 720px) { .basic-fields { grid-template-columns: minmax(0, 250px); } }
</style>
