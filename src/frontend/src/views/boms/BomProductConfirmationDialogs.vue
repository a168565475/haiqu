<script setup lang="ts">
import { ref } from 'vue'
import InquiryProductDialog from '@/components/inquiries/InquiryProductDialog.vue'
import ProductCreateDialog from '@/components/products/ProductCreateDialog.vue'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import type { InquiryItem } from '@/types/inquiry'
import type { BomDetail } from '@/types/bom'
import type { ProductOptions, ProductInformation, ProductInformationInput } from '@/types/product'
import type { ProductColor } from '@/types/productionData'

interface ProductColorDraft {
  color_card: string
  color_code: string
  color_name: string
}

const props = defineProps<{
  bom: BomDetail
  modelValue: boolean
  createProductVisible: boolean
  createColorVisible: boolean
  productConfirmItem: InquiryItem
  productConfirmOptions: ProductOptions
  productConfirmColors: ProductColor[]
  canCreateProduct: boolean
  canCreateProductColor: boolean
  productConfirmLoading: boolean
  productConfirmCatalogError: string
  productConfirmCatalogLoading: boolean
  productConfirmError: string
  productCreateInitial: Partial<ProductInformationInput>
  productCreateUnitCode: string
  productCreateItemNumber: string
  productColorDraft: ProductColorDraft
  formatNumber: (value: string | number | null | undefined) => string
  submitProduct: (input: ProductInformationInput) => Promise<ProductInformation>
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  'update:createProductVisible': [value: boolean]
  'update:createColorVisible': [value: boolean]
  confirm: [payload: { item: InquiryItem }]
  'retry-catalog': []
  'create-product': [item: InquiryItem]
  'create-color': [name: string]
  created: []
  'save-color': []
}>()

const productConfirmDialog = ref<InstanceType<typeof InquiryProductDialog>>()

function applyCreatedColor(color: Pick<ProductColor, 'id' | 'color_name'>) {
  productConfirmDialog.value?.applyCreatedColor(color)
}

defineExpose({ applyCreatedColor })
</script>

<template>
  <InquiryProductDialog
    ref="productConfirmDialog"
    :model-value="props.modelValue"
    scene="bom"
    :item="props.productConfirmItem"
    :context-title="`${props.bom.production_task_number} · ${props.bom.product_name_snapshot}`"
    :reviewed="props.bom.product_information_confirmed"
    :categories="props.productConfirmOptions.categories"
    :units="props.productConfirmOptions.units"
    :colors="props.productConfirmColors"
    :currencies="[]"
    :can-upload="false"
    :can-create-product="props.canCreateProduct"
    :can-create-color="props.canCreateProductColor"
    :busy="props.productConfirmLoading"
    :close-on-confirm="false"
    :catalog-error="props.productConfirmCatalogError"
    :catalog-loading="props.productConfirmCatalogLoading"
    :save-error="props.productConfirmError"
    @update:model-value="emit('update:modelValue', $event)"
    @confirm="emit('confirm', $event)"
    @retry-catalog="emit('retry-catalog')"
    @create-product="emit('create-product', $event)"
    @create-color="emit('create-color', $event)"
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

  <ProductCreateDialog
    :model-value="props.createProductVisible"
    :initial-values="props.productCreateInitial"
    :initial-unit-code="props.productCreateUnitCode"
    :initial-item-number="props.productCreateItemNumber"
    :submit-product="props.submitProduct"
    @update:model-value="emit('update:createProductVisible', $event)"
    @created="emit('created')"
  />

  <AppWindowDialog
    :model-value="props.createColorVisible"
    title="新增颜色"
    :width="520"
    :close-on-click-modal="false"
    :close-on-press-escape="!props.productConfirmLoading"
    :show-close="!props.productConfirmLoading"
    @update:model-value="emit('update:createColorVisible', $event)"
  >
    <ElForm label-position="top" class="bom-color-create-form">
      <ElFormItem label="色卡" required><ElInput v-model="props.productColorDraft.color_card" maxlength="100" placeholder="例如：A卡" /></ElFormItem>
      <ElFormItem label="色号" required><ElInput v-model="props.productColorDraft.color_code" maxlength="100" placeholder="例如：001" /></ElFormItem>
      <ElFormItem label="颜色名称" required><ElInput v-model="props.productColorDraft.color_name" maxlength="200" placeholder="例如：黑色" /></ElFormItem>
    </ElForm>
    <template #footer><ElButton :disabled="props.productConfirmLoading" @click="emit('update:createColorVisible', false)">取消</ElButton><ElButton type="primary" :loading="props.productConfirmLoading" @click="emit('save-color')">保存颜色</ElButton></template>
  </AppWindowDialog>
</template>

<style scoped lang="scss">
@use '@/styles/crm/tokens' as token;

.bom-review-context { font-size: 13px; color: token.$crm-text-regular; h3 { margin: 20px 0 12px; font-size: 13px; line-height: 20px; color: token.$crm-text-primary; &:first-child { margin-top: 0; } } p { margin: 0; line-height: 20px; } dl { margin: 0; } dl > div { margin: 0 0 12px; } dt { color: token.$crm-text-secondary; margin-bottom: 4px; } dd { margin: 0; overflow-wrap: anywhere; } }
.bom-review-context__fields { display: grid; gap: 12px; label > span { display: block; margin-bottom: 8px; color: token.$crm-text-secondary; } :deep(.el-input__wrapper) { height: 32px; min-height: 32px; box-sizing: border-box; background: token.$crm-color-subtle; } }
.bom-review-context .bom-review-context__rule { margin-top: 20px; padding-top: 16px; border-top: 1px solid token.$crm-border-default; color: token.$crm-text-secondary; }
</style>
