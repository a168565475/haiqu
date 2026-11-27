<script setup lang="ts">
import { ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import { getPurchaseWorkbenchItems } from '@/api/purchaseWorkbench'
import { arrivalQuantity, coverageQuantity } from '@/utils/purchaseTrackingQuantities'
import { workbenchErrorMessage } from '@/utils/workbench'
import type { PurchaseWorkbenchCategory, PurchaseWorkbenchRow } from '@/types/purchaseWorkbench'

const props = defineProps<{ category: PurchaseWorkbenchCategory; title: string }>()
const emit = defineEmits<{ close: [] }>()
const page = ref(1), total = ref(0), rows = ref<PurchaseWorkbenchRow[]>([])
const loading = ref(false), error = ref(''), retry = ref(0)
watch([() => props.category, page, retry], ([category, number], _, cleanup) => {
  const request = new AbortController()
  cleanup(() => request.abort())
  error.value = ''
  rows.value = []
  loading.value = true
  getPurchaseWorkbenchItems(category, number, request.signal).then(result => {
    if (!request.signal.aborted) { rows.value = result.data; total.value = result.meta.total }
  }).catch(cause => {
    if (!request.signal.aborted) error.value = workbenchErrorMessage(cause, '加载采购明细')
  }).finally(() => { if (!request.signal.aborted) loading.value = false })
}, { immediate: true })

function destination(row: PurchaseWorkbenchRow) {
  if (props.category === 'unstarted') return { name: 'purchase-alerts', query: { production_task_id: row.production_task_id, purchase_scope: 'STANDARD' } }
  if ('purchase_order_id' in row && row.actions.some(a => a.kind === 'view_order')) return { name: 'purchase-order-detail', params: { id: row.purchase_order_id } }
  if (row.purchase_group_id && row.actions.some(a => a.kind === 'view_group')) return { name: 'purchase-group-detail', params: { id: row.purchase_group_id } }
  return { name: 'purchase_order_id' in row ? 'purchase-tracking' : 'purchase-alerts',
    query: { row_key: row.row_key, production_task_id: row.production_task_id, purchase_scope: 'STANDARD' } }
}
</script>

<template>
  <AppWindowDialog :model-value="true" :title="title" :width="1040" :min-width="300" :minimizable="false" @update:model-value="value => { if (!value) emit('close') }">
    <p v-if="error" role="alert">{{ error }} <ElButton link type="primary" @click="retry++">重试</ElButton></p>
    <p v-else-if="loading" role="status">正在加载…</p>
    <p v-else-if="!rows.length">当前没有这类待办。</p>
    <div v-else class="table-scroll">
      <table><thead><tr><th>生产任务单号</th>
        <template v-if="category === 'unstarted'"><th>待买物料</th></template>
        <template v-else><th>产品 / 物料</th>
          <template v-if="category === 'shortage' || category === 'bom_changed'"><th>需求量</th><th>已采购</th><th>还需采购</th><th>{{ category === 'bom_changed' ? '变更提示' : '最晚采购日' }}</th></template>
          <template v-else><th>供应商 / 采购单</th><th>采购量</th><th>已收 / 尚欠</th><th>供应商交期</th><th>排产材料入库日</th></template>
        </template></tr></thead><tbody>
        <tr v-for="row in rows" :key="row.row_key"><td><RouterLink :to="destination(row)">{{ row.task_number }}</RouterLink></td>
          <td v-if="category === 'unstarted'">{{ 'material_count' in row ? row.material_count : '—' }} 项</td>
          <template v-else><td>{{ row.product_name }}<small>{{ row.material_name }} {{ row.specification }}</small></td>
            <template v-if="'purchase_order_id' in row"><td>{{ row.supplier_name || '待核对' }}<small>{{ row.purchase_order_no }}</small></td><td>{{ arrivalQuantity(row, 'ordered') }}</td><td>{{ arrivalQuantity(row, 'received') }}<small>尚欠 {{ arrivalQuantity(row, 'unreceived') }}</small></td><td>{{ row.delivery_date || '待补' }}</td><td>{{ row.material_inbound_date || '待核对' }}</td></template>
            <template v-else><td>{{ coverageQuantity(row, 'required') }}</td><td>{{ coverageQuantity(row, 'purchased') }}</td><td>{{ coverageQuantity(row, 'remaining') }}</td><td>{{ category === 'bom_changed' ? row.verification_notes.join('、') || '需求变化待核对' : row.latest_purchase_date || '待核对' }}</td></template>
          </template>
        </tr>
      </tbody></table>
    </div>
    <footer v-if="!error && !loading"><span>共 {{ total }} {{ category === 'unstarted' ? '张任务' : '项' }}</span><ElPagination v-if="total > 20" v-model:current-page="page" :page-size="20" :total="total" layout="prev, pager, next" background /></footer>
  </AppWindowDialog>
</template>

<style scoped>
.table-scroll { overflow:auto; max-height:58vh; }.table-scroll table { width:100%; border-collapse:collapse; text-align:left; font-size:13px; }
th,td { padding:10px 12px; border-bottom:1px solid var(--erp-color-border-subtle); vertical-align:top; }th { position:sticky; top:0; white-space:nowrap; color:var(--erp-color-text-secondary); background:var(--erp-color-subtle); }
td:first-child { font-weight:600; white-space:nowrap; }td small { display:block; margin-top:3px; color:var(--erp-color-text-secondary); }td a { color:var(--erp-color-brand); text-decoration:none; }td a:hover { text-decoration:underline; }
footer { display:flex; justify-content:space-between; align-items:center; gap:12px; margin-top:14px; color:var(--erp-color-text-secondary); font-size:13px; }
</style>
