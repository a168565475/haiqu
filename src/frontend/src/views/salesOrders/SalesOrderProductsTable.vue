<script setup lang="ts">
import ProductImage from '@/components/products/ProductImage.vue'
import { salesOrderLineProductImageUrl } from '@/api/salesOrders'
import type { ProductCategory, ProductionUnit } from '@/types/productionData'
import type { SalesOrder, SalesOrderLine } from '@/types/salesOrder'

const props = defineProps<{
  order: SalesOrder
  categories: ProductCategory[]
  units: ProductionUnit[]
  catalogError: string
}>()

function productName(line: SalesOrderLine): string {
  return line.customer_product_name_snapshot || line.product_name_snapshot || '—'
}
function categoryName(line: SalesOrderLine): string {
  return props.categories.find(category => category.id === line.product_category_id)?.category_name || '—'
}
function unitName(line: SalesOrderLine): string {
  const unit = props.units.find(item => item.id === line.product_unit_id && item.unit_code === line.unit_code_snapshot)
  return unit?.unit_name || line.unit_code_snapshot || '—'
}
function expectedDate(line: SalesOrderLine): string {
  const activeBatches = props.order.delivery_batches.filter(batch => batch.status === 'ACTIVE')
  const dates = [...new Set(activeBatches
    .filter(batch => batch.lines.some(item => item.sales_order_line_id === line.id && Number(item.quantity) > 0))
    .map(batch => batch.planned_delivery_date)
    .filter(Boolean))]
  if (dates.length === 1) return dates[0]!
  if (dates.length > 1) return '多批次'
  return activeBatches.length === 1 ? activeBatches[0]!.planned_delivery_date || '—' : '—'
}
function numberText(value: string | number | null | undefined): string {
  if (value == null || value === '') return '—'
  return Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 4 })
}
</script>

<template>
  <p v-if="catalogError" class="catalog-error" role="alert">{{ catalogError }}</p>
  <div class="products-table-scroll" role="region" aria-label="销售订单产品明细" tabindex="0">
    <table class="products-table">
      <thead><tr><th scope="col">产品信息</th><th scope="col">数量 / 单位</th><th scope="col">期望日期</th><th scope="col">图片</th><th scope="col">单价 ({{ order.currency_code }})</th><th scope="col">金额</th><th scope="col">价格备注</th></tr></thead>
      <tbody>
        <tr v-for="line in order.lines" :key="line.id">
          <td class="product-details">
            <dl><dt>类别</dt><dd>{{ categoryName(line) }}</dd><dt>品名</dt><dd><strong>{{ productName(line) }}</strong><small v-if="line.product_number_snapshot">品号：{{ line.product_number_snapshot }}</small><small v-if="line.product_code_snapshot">产品编码：{{ line.product_code_snapshot }}</small><small v-if="line.item_number_snapshot">货号：{{ line.item_number_snapshot }}</small></dd><dt>规格</dt><dd>{{ line.specification_display || line.customer_specification_snapshot || line.specification_snapshot || '—' }}</dd><dt>颜色</dt><dd>{{ line.customer_color_snapshot || '—' }}</dd><dt>材质</dt><dd>{{ line.material_snapshot || '—' }}</dd></dl>
          </td>
          <td>{{ numberText(line.quantity) }} {{ unitName(line) }}</td>
          <td>{{ expectedDate(line) }}</td>
          <td><ProductImage v-if="line.product_image_id" :src="salesOrderLineProductImageUrl(order.id, line.id)" :name="productName(line)"/><span v-else class="muted">无图</span></td>
          <td><dl class="price-values"><template v-if="order.source_type === 'QUOTATION'"><dt>报价单价</dt><dd>{{ line.quoted_unit_price === null ? '—' : numberText(line.quoted_unit_price) }}</dd></template><dt>订单单价</dt><dd>{{ numberText(line.unit_price) }}</dd><template v-if="order.source_type === 'QUOTATION'"><dt>价差</dt><dd>{{ line.quoted_unit_price === null ? '—' : numberText(line.price_difference) }}</dd></template></dl></td>
          <td><dl class="price-values"><dt>行金额 ({{ order.currency_code }})</dt><dd>{{ numberText(line.line_total) }}</dd><dt>人民币单价</dt><dd>{{ numberText(line.unit_price_cny) }}</dd><dt>人民币金额 (CNY)</dt><dd>{{ numberText(line.line_total_cny) }}</dd></dl></td>
          <td class="price-note">{{ line.lower_price_reason || '—' }}</td>
        </tr>
        <tr v-if="!order.lines.length"><td colspan="7" class="empty-cell">暂无产品</td></tr>
      </tbody>
    </table>
  </div>
</template>

<style scoped>
.products-table-scroll{max-width:100%;overflow-x:auto;border-radius:5px}
.products-table{width:100%;min-width:900px;border-collapse:collapse;table-layout:fixed;font-size:13px;line-height:1.6}
.products-table th{padding:12px;text-align:left;background:#f0eadf;color:#6f6a61;font-weight:500}
.products-table td{padding:12px;vertical-align:top;border-bottom:1px solid #ddd6c9;overflow-wrap:anywhere}
.products-table th:nth-child(1){width:29%}.products-table th:nth-child(2){width:10%}.products-table th:nth-child(3){width:11%}.products-table th:nth-child(4){width:6%}.products-table th:nth-child(5){width:14%}.products-table th:nth-child(6){width:17%}.products-table th:nth-child(7){width:13%}
.product-details dl{display:grid;grid-template-columns:30px minmax(0,1fr);gap:5px 8px;margin:0}
.products-table dt,.muted{color:#6f6a61}.products-table dd{margin:0;min-width:0;white-space:pre-wrap}
.product-details small{display:block;color:#6f6a61;font-size:11px;line-height:1.5}
.price-values{display:grid;gap:2px;margin:0}.price-values dt:not(:first-child){margin-top:6px}
.price-note{white-space:pre-wrap}.catalog-error{margin:0 0 12px;color:#ad6b05;font-size:13px}.empty-cell{text-align:center;color:#6f6a61}
</style>
