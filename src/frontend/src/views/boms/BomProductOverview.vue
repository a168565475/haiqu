<script setup lang="ts">
import BomProductImage from '@/components/boms/BomProductImage.vue'
import type { BomDetail } from '@/types/bom'

defineProps<{ bom: BomDetail }>()

function number(value: string | number | null | undefined) {
  if (value === null || value === undefined || value === '') return '—'
  const parsed = Number(value)
  return Number.isFinite(parsed) ? new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 4 }).format(parsed) : String(value)
}
</script>

<template>
  <div class="product-overview">
    <BomProductImage
      :task-id="bom.production_task_id || ''"
      :product-line-id="bom.production_task_product_id || ''"
    />
    <div class="product-details">
      <section>
        <h3>基本信息</h3>
        <dl>
          <div><dt>BOM 编号</dt><dd>{{ bom.bom_number }}</dd></div>
          <div><dt>订单号</dt><dd>{{ bom.order_number || '—' }}</dd></div>
          <div><dt>产品编号</dt><dd>{{ bom.product_code_snapshot || bom.product_number_snapshot || '—' }}</dd></div>
          <div><dt>货号</dt><dd>{{ bom.item_number_snapshot || '—' }}</dd></div>
        </dl>
      </section>
      <section>
        <h3>产品属性</h3>
        <dl>
          <div><dt>产品名称</dt><dd>{{ bom.product_name_snapshot }}</dd></div>
          <div><dt>产品规格</dt><dd>{{ bom.specification_snapshot || '—' }}</dd></div>
          <div><dt>单位</dt><dd>{{ bom.product_unit_name || '—' }}</dd></div>
          <div><dt>颜色</dt><dd>{{ bom.product_color_snapshot || '—' }}</dd></div>
          <div><dt>材质</dt><dd>{{ bom.material_snapshot || '—' }}</dd></div>
        </dl>
      </section>
      <section>
        <h3>数量信息</h3>
        <dl>
          <div><dt>当前订单数量</dt><dd class="quantity-value">{{ number(bom.current_order_quantity) }}</dd></div>
          <div><dt>BOM 订单数量</dt><dd>{{ number(bom.order_quantity) }}</dd></div>
          <div><dt>原表数量</dt><dd>{{ number(bom.source_quantity) }}</dd></div>
          <div><dt>批次合计</dt><dd>{{ number(bom.batch_quantity) }}</dd></div>
        </dl>
      </section>
    </div>
  </div>
</template>

<style scoped lang="scss">
@use '@/styles/crm/tokens' as token;

.product-overview { display: grid; grid-template-columns: minmax(240px, 32%) minmax(0, 1fr); align-items: start; gap: 24px; margin-top: 16px; }
.product-details { min-width: 0; }
.product-details section + section { margin-top: 16px; padding-top: 16px; border-top: 1px solid token.$crm-border-default; }
.product-details h3 { margin: 0 0 8px; font-size: 13px; font-weight: 600; line-height: 20px; }
.product-details dl { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px 24px; margin: 0; }
.product-details dl > div { display: grid; grid-template-columns: 96px minmax(0, 1fr); gap: 8px; min-width: 0; font-size: 13px; line-height: 24px; }
.product-details dt { color: token.$crm-text-secondary; }
.product-details dd { margin: 0; color: token.$crm-text-primary; overflow-wrap: anywhere; }
.product-details .quantity-value { color: token.$crm-primary; font-weight: 600; }

@media (max-width: 1400px) {
  .product-details dl { grid-template-columns: 1fr; }
}
</style>
