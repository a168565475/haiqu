<script setup lang="ts">
import { onMounted, ref } from 'vue'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import { fetchMaterialReceipts } from '@/api/inventory'
import type { MaterialInbound } from '@/types/inventory'

const props = defineProps<{ inboundId: string }>()
const emit = defineEmits<{ close: [] }>()
const receipt = ref<MaterialInbound>()
const error = ref('')
const loading = ref(false)
const receiptQuantities = [{ key: 'received', label: '收货数量' }, { key: 'return', label: '退货数量' }, { key: 'accepted', label: '合格数量' }]

async function readReceipt() {
  error.value = ''
  loading.value = true
  try {
    const [record] = await fetchMaterialReceipts({ inbound_id: props.inboundId })
    receipt.value = record
    if (!record) error.value = '该入库单不存在或不在可查看范围内。'
  } catch {
    error.value = '入库单加载失败，请重试。'
  } finally {
    loading.value = false
  }
}

onMounted(readReceipt)
</script>

<template>
  <AppWindowDialog :model-value="true" :title="receipt?.inbound_number ?? '入库单'" :width="1040" :min-width="290"
    :minimizable="false" @update:model-value="emit('close')">
    <section v-loading="loading" class="receipt-content">
      <ElAlert v-if="error" :title="error" type="error" :closable="false">
        <ElButton link @click="readReceipt">重试</ElButton>
      </ElAlert>
      <template v-if="receipt">
        <dl class="receipt-fields">
          <div><dt>入库日期</dt><dd>{{ receipt.inbound_date }}</dd></div>
          <div><dt>采购单号</dt><dd :title="receipt.purchase_order_number ?? undefined">{{ receipt.purchase_order_number || '—' }}</dd></div>
          <div><dt>收货人</dt><dd>{{ receipt.received_by_name }}</dd></div>
          <div><dt>品质确认人</dt><dd>{{ receipt.quality_confirmed_by_name || '—' }}</dd></div>
          <div><dt>状态</dt><dd>{{ receipt.status_display }}</dd></div>
        </dl>
        <div class="erp-glass-list receipt-lines">
          <div class="erp-list-table-frame">
            <ElTable :data="receipt.lines" row-key="id" max-height="400" aria-label="入库明细">
              <ElTableColumn prop="material_snapshot" label="材料名称" min-width="144" show-overflow-tooltip />
              <ElTableColumn prop="specification_snapshot" label="规格" width="152" show-overflow-tooltip />
              <ElTableColumn v-for="column in receiptQuantities" :key="column.key" :label="column.label" width="100" align="right">
                <template #default="{ row }">{{ row.calculation_snapshot?.receipt_quantity_mode === 'ROOTS' ? row[column.key + '_bar_count'] : row[column.key + '_quantity'] }}</template>
              </ElTableColumn>
              <ElTableColumn label="单位" width="98"><template #default="{ row }">{{ row.calculation_snapshot?.receipt_quantity_mode === 'ROOTS' ? '根' : row.source_unit_text_snapshot }}</template></ElTableColumn>
              <ElTableColumn v-if="receipt.lines.some(line => line.calculation_snapshot?.receipt_quantity_mode !== 'ROOTS')" label="合格实重（KG）" width="132" align="right">
                <template #default="{ row }">{{ row.accepted_weight_kg ?? '—' }}</template>
              </ElTableColumn>
            </ElTable>
          </div>
        </div>
      </template>
    </section>
    <template #footer><ElButton @click="emit('close')">关闭</ElButton></template>
  </AppWindowDialog>
</template>

<style scoped lang="scss">
.receipt-content { min-height: 48px; }
.receipt-fields {
  display: flex; gap: 16px; margin: 0 0 12px; overflow-x: auto; white-space: nowrap; font-size: 13px;
  div { display: flex; gap: 8px; }
  dt { color: var(--erp-color-text-secondary); }
  dd { margin: 0; }
}
.receipt-lines { height: auto; }
.receipt-lines :deep(.el-table .cell) { white-space: nowrap; text-overflow: ellipsis; }
.receipt-lines :deep(.el-table__header th.el-table__cell) { font-weight: 500; }
</style>
