<script setup lang="ts">
import SampleProductImage from '@/components/samples/SampleProductImage.vue'
import { computed, ref } from 'vue'
import SampleSection from './SampleSection.vue'
import SampleReadonlyField from './SampleReadonlyField.vue'
import type { SampleDetail } from '@/types/sample'

const props = defineProps<{ sample: SampleDetail }>()
const selectedProductId = ref('')
const product = computed(() => props.sample.products?.find(item => item.id === selectedProductId.value) || props.sample.products?.[0])
const basicFields = computed(() => [
  { label: props.sample.source_quotation_version ? '来源报价' : '来源询盘', value: props.sample.source_quotation_number || props.sample.source_inquiry_number },
  { label: '客户', value: props.sample.customer_name },
  { label: '联系人', value: props.sample.customer_contact_name },
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
        <div class="product-body">
          <SampleProductImage class="product-image" :src="sample.reference_image ? `/api/v1/sample-requests/${sample.id}/business-files/${sample.reference_image}/` : ''" />
          <div class="product-fields">
            <div v-if="(sample.products?.length || 0) > 1" class="product-selector"><label for="review-product">产品名称</label><ElSelect id="review-product" :model-value="product?.id" @update:model-value="selectedProductId = $event"><ElOption v-for="item in sample.products" :key="item.id" :value="item.id" :label="item.product_name" /></ElSelect></div>
            <SampleReadonlyField v-else label="产品名称" :value="product?.product_name || sample.item_summary?.text" />
            <SampleReadonlyField label="规格" :value="product?.specification" />
            <div class="dimension-fields"><SampleReadonlyField v-for="field in dimensionFields" :key="field.label" :label="field.label" :value="field.value" /></div>
            <div class="requirements"><span>特殊要求</span><p>{{ sample.purpose || '—' }}</p></div>
          </div>
        </div>
      </SampleSection>
      <div class="summary-aside">
        <SampleSection title="参考图片" class="summary-reference"><img v-if="sample.reference_image" class="reference-image" :src="`/api/v1/sample-requests/${sample.id}/business-files/${sample.reference_image}/`" alt="申请参考图片" /><div v-else class="reference-empty"><strong>暂无参考图片</strong><span>本项为选填</span></div></SampleSection>
        <SampleSection title="打样数量" class="summary-quantity"><p>{{ product ? `${product.total_sample_quantity} PCS` : '—' }}</p><span>业务员申请数量</span></SampleSection>
      </div>
    </div>
  </div>
</template>

<style scoped lang="scss">
@use '@/styles/crm/tokens' as token;
.application-summary { display: flex; flex-direction: column; gap: 18px; }
.summary-basic { height: 230px; }
.summary-basic :deep(h2), .summary-product :deep(h2) { margin-bottom: 12px; }
.basic-fields { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 12px 28px; }
.summary-columns { display: grid; grid-template-columns: minmax(0, 1042fr) minmax(0, 572fr); gap: 20px; }
.summary-product { height: 382px; }
.product-body { display: grid; grid-template-columns: 226px minmax(0, 1fr); gap: 28px; }
.product-image { display: grid; height: 238px; place-items: center; border: 1px solid token.$crm-border-subtle; border-radius: 4px; color: token.$crm-text-muted; background: token.$crm-color-page; font-size: 12px; }
.product-fields { display: flex; min-width: 0; flex-direction: column; gap: 8px; }
.product-selector { height: 60px; font-size: 14px; }
.product-selector label { display: block; margin-bottom: 6px; }
.product-selector :deep(.el-select__wrapper) { min-height: 32px; }
.dimension-fields { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 16px; }
.requirements { font-size: 14px; line-height: 22px; }
.requirements p { height: 52px; margin: 6px 0 0; padding: 8px; overflow: auto; border-radius: 4px; background: token.$crm-color-page; font-size: 13px; }
.summary-aside { display: flex; flex-direction: column; gap: 14px; }
.summary-reference { height: 234px; }
.reference-image { display: block; width: 100%; height: 136px; object-fit: contain; }
.summary-reference :deep(h2) { margin-bottom: 12px; }
.reference-empty { display: flex; height: 136px; align-items: center; justify-content: center; flex-direction: column; gap: 4px; border: 1px dashed token.$crm-border-default; border-radius: 4px; background: token.$crm-color-page; line-height: 22px; }
.reference-empty strong { font-size: 14px; font-weight: 500; }
.reference-empty span, .summary-quantity > span { color: token.$crm-text-muted; font-size: 12px; line-height: 22px; }
.summary-quantity { height: 134px; padding: 16px 24px; }
.summary-quantity :deep(h2) { margin-bottom: 4px; }
.summary-quantity p { height: 32px; margin: 0 0 4px; padding: 5px 12px; background: token.$crm-color-page; font-size: 14px; line-height: 22px; }
@media (max-width: 1440px) { .basic-fields { gap: 12px 16px; } .product-body { grid-template-columns: 160px minmax(0, 1fr); gap: 20px; } .dimension-fields { gap: 8px; } }
@media (max-width: 1200px) { .summary-basic, .summary-product { height: auto; } .basic-fields { grid-template-columns: repeat(3, minmax(0, 1fr)); } .summary-columns { grid-template-columns: 1fr; } .summary-aside { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); } }
</style>
