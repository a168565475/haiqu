<script setup lang="ts">
import { computed } from 'vue'
import { ElTable, ElTableColumn } from 'element-plus'
import type { ReceiptRecordDetail } from '@/types/inventory'
import type { PurchaseReadInbound, PurchaseReadInboundLine, PurchaseReadLine } from '@/types/purchaseOrderReadDetail'
import { weighedProductionPipe } from '@/utils/pipeQuantities'
import { receiptMaterialAttributeColumnWidth, receiptMaterialTables } from '@/utils/receiptMaterialTables'
import { formatQuantity, quantityWithUnit } from '@/views/procurement/purchaseOrderDetailDisplay'

type QuantityKind = 'received' | 'return' | 'accepted'
type PurchaseReceipt = {
  source: 'PURCHASE'
  data: Pick<PurchaseReadInbound, 'status' | 'lines'>
  productionTaskNumber?: string
  fallbackColors?: Record<string, string>
  formatQuantity: (line: PurchaseReadInboundLine, kind: QuantityKind) => string
}
type OrderMaterials = {
  source: 'ORDER'
  data: { lines: PurchaseReadLine[] }
  formatQuantities: (line: PurchaseReadLine) => string[]
  totals: string[]
}
type DetailReceipt = PurchaseReceipt | Extract<ReceiptRecordDetail, { source: 'TRANSFER' }> | OrderMaterials
interface ReceiptDetailRow {
  line: DetailReceipt['data']['lines'][number] & { fallbackColor?: string }
  id: string
  name: string
  supplier: string
  quantities: string[]
  warehouse?: string
  zone?: string
  location?: string
  remark?: string
}
const props = defineProps<{ receipt: DetailReceipt }>()
const quantityColumns = {
  ORDER: ['采购数量', '累计到货', '退货数量', '合格入库数量'],
  PURCHASE: ['到货数量', '退货数量', '合格入库数量'],
  TRANSFER: ['入库数量', '实际重量（kg）'],
}
const widths = { index: 58, material: 180, supplier: 200, quantity: 124, remark: 172, warehouse: 138, zone: 126, location: 112 }
const quantityHeadings = computed(() => quantityColumns[props.receipt.source])
const tableLabel = computed(() => props.receipt.source === 'ORDER' ? '采购材料明细' : '入库材料明细')

const rows = computed<ReceiptDetailRow[]>(() => {
  const receipt = props.receipt
  if (receipt.source === 'ORDER') {
    return receipt.data.lines.map(line => ({
      line: { ...line, fallbackColor: line.color }, id: line.id,
      name: line.part_name || line.raw_material || '—', supplier: line.supplier_name,
      quantities: receipt.formatQuantities(line),
    }))
  }
  if (receipt.source === 'TRANSFER') {
    return receipt.data.lines.map(line => ({
      line, id: line.line_key, name: line.catalog_name || '—', supplier: '',
      quantities: [quantityWithUnit(line.quantity, line.unit_name), formatQuantity(line.weight_quantity)],
      warehouse: line.warehouse_name, zone: line.zone_name, location: '未登记', remark: '',
    }))
  }
  const confirmed = receipt.data.status === 'CONFIRMED'
  return receipt.data.lines.map(line => {
    const oldProductionPipe = weighedProductionPipe(line, receipt.productionTaskNumber)
    const quantity = (kind: QuantityKind) => {
      if (!oldProductionPipe) return receipt.formatQuantity(line, kind)
      const roots = line[`${kind}_bar_count`]
      return roots == null ? '根数未记录' : quantityWithUnit(String(roots), '根')
    }
    return {
      line: { ...line, fallbackColor: receipt.fallbackColors?.[line.purchase_order_line_id] },
      id: line.id, name: line.part_name_snapshot || line.material_snapshot || '—', supplier: line.supplier_name_snapshot,
      quantities: [quantity('received'), confirmed ? quantity('return') : '—', confirmed ? quantity('accepted') : '待质检'],
      warehouse: line.warehouse_name, zone: line.zone_name, location: line.location_number || '未登记', remark: line.quality_remark,
    }
  })
})

function textColumnWidth(values: string[], minimum: number) {
  // ERP 表格的单行文字为 12px，左右各留 16px，另预留边框和测量余量。
  return values.reduce((width, value) => {
    const textWidth = Array.from(value).reduce((total, character) => total + (/[^\x00-\xff]/u.test(character) ? 12 : 8), 36)
    return Math.max(width, textWidth)
  }, minimum)
}

const supplierWidth = computed(() => textColumnWidth(rows.value.map(row => row.supplier || ''), widths.supplier))
const quantityWidths = computed(() => quantityHeadings.value.map((_, index) => textColumnWidth(
  rows.value.map(row => row.quantities[index] || ''), widths.quantity,
)))
const tables = computed(() => receiptMaterialTables(rows.value).map(table => ({
  ...table,
  attributeColumns: table.columns.map(label => ({
    label,
    minWidth: Math.min(280, textColumnWidth(
      table.rows.map(row => row.attributes.get(label) || ''), receiptMaterialAttributeColumnWidth(label),
    )),
  })),
})))
</script>

<template>
  <div v-if="!receipt.data.lines.length" class="material-empty">暂无材料明细</div>
  <div v-else class="erp-glass-list receipt-material-tables" :aria-label="tableLabel">
    <section v-for="table in tables" :key="table.key" class="receipt-material-group" :data-material-category="table.key">
      <h3 v-if="tables.length > 1 || !['TUBE', 'OTHER'].includes(table.key)">{{ table.label }}</h3>
      <div class="erp-list-table-frame">
        <ElTable :data="table.rows" :row-key="entry => entry.row.id" :aria-label="table.label || tableLabel">
          <ElTableColumn prop="number" label="序号" :width="widths.index" align="center" />
          <ElTableColumn prop="row.name" label="物料信息" :width="widths.material" />
          <ElTableColumn v-if="receipt.source !== 'TRANSFER'" prop="row.supplier" label="供应商" :width="supplierWidth">
            <template #default="{ row }">{{ row.row.supplier || '—' }}</template>
          </ElTableColumn>
          <ElTableColumn v-for="column in table.attributeColumns" :key="column.label" :label="column.label" :min-width="column.minWidth">
            <template #default="{ row }">{{ row.attributes.get(column.label) ?? '—' }}</template>
          </ElTableColumn>
          <ElTableColumn v-for="(label, index) in quantityHeadings" :key="label" :label="label"
            :width="table.attributeColumns.length ? quantityWidths[index] : undefined"
            :min-width="table.attributeColumns.length ? undefined : quantityWidths[index]" align="right" class-name="receipt-quantity">
            <template #default="{ row }">{{ row.row.quantities[index] }}</template>
          </ElTableColumn>
          <ElTableColumn v-if="receipt.source === 'PURCHASE'" label="退货/质检说明" :width="widths.remark">
            <template #default="{ row }">{{ row.row.remark || '—' }}</template>
          </ElTableColumn>
          <template v-if="receipt.source !== 'ORDER'">
            <ElTableColumn prop="row.warehouse" label="材料仓" :width="widths.warehouse">
              <template #default="{ row }">{{ row.row.warehouse || '—' }}</template>
            </ElTableColumn>
            <ElTableColumn prop="row.zone" label="库区" :width="widths.zone">
              <template #default="{ row }">{{ row.row.zone || '未登记' }}</template>
            </ElTableColumn>
            <ElTableColumn prop="row.location" label="库位" :width="widths.location" />
          </template>
        </ElTable>
      </div>
    </section>
    <div v-if="receipt.source === 'ORDER'" class="material-quantity-totals" aria-label="采购材料合计">
      <strong>合计</strong>
      <span v-for="(label, index) in quantityHeadings" :key="label">{{ label }} {{ receipt.totals[index] }}</span>
    </div>
  </div>
</template>

<style scoped>
.receipt-material-tables { height: auto; gap: 10px; }
.receipt-material-group { flex: none; min-width: 0; }
.receipt-material-group .erp-list-table-frame { box-sizing: border-box; }
.receipt-material-group h3 { margin: 0; padding: 5px 0; color: var(--erp-table-header-text); font-size: 13px; }
.receipt-material-group :deep(.el-table .cell) { white-space: nowrap; }
.material-quantity-totals { display: flex; flex-wrap: wrap; gap: 6px 20px; padding: 0 12px; color: var(--erp-table-text); font-size: 12px; }
.material-empty { padding: 28px 20px; text-align: center; color: var(--erp-color-text-secondary); }
</style>
