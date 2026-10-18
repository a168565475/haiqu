<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { ArrowLeft, Refresh } from '@element-plus/icons-vue'
import { useRoute } from 'vue-router'

import { fetchMaterialInventorySummary, fetchMaterialOrderIssues, fetchMaterialOrderPurchases } from '@/api/inventory'
import { router } from '@/router'
import type { MaterialInventorySummary, MaterialOrderIssue, MaterialOrderPurchase } from '@/types/inventory'

const route = useRoute()
const stockItemId = computed(() => String(route.params.stockItemId || ''))
const activeTab = ref(route.query.tab === 'purchases' ? 'purchases' : 'issues')
const summary = ref<MaterialInventorySummary | null>(null)
const purchases = ref<MaterialOrderPurchase[]>([])
const issues = ref<MaterialOrderIssue[]>([])
const loading = ref(false)
const apiMessage = (error: unknown) => (error as { response?: { data?: { error?: { message?: string } } } })?.response?.data?.error?.message || '材料库存详情加载失败。'
const numberText = (value: string) => Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 4 })
const dateText = (value: string) => value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '—'
async function load() {
  loading.value = true
  try {
    const [summaryData, purchaseData, issueData] = await Promise.all([
      fetchMaterialInventorySummary(stockItemId.value), fetchMaterialOrderPurchases(stockItemId.value), fetchMaterialOrderIssues(stockItemId.value),
    ])
    summary.value = summaryData; purchases.value = purchaseData; issues.value = issueData
  } catch (error) { ElMessage.error(apiMessage(error)) }
  finally { loading.value = false }
}
watch(activeTab, (tab) => { void router.replace({ query: { ...route.query, tab } }) })
onMounted(load)
</script>

<template>
  <section v-loading="loading" class="material-issue-page material-stock-detail erp-glass-detail" data-testid="material-inventory-detail">
    <header class="mi-page-head"><div><ElButton link :icon="ArrowLeft" @click="router.push({ name: 'material-inventory' })">返回材料库存</ElButton><h1>{{ summary?.material_number || '材料库存详情' }} · {{ summary?.material_name || '' }}</h1><p>{{ summary?.category }} · {{ summary?.specification || '无规格' }} · {{ summary?.color || '无颜色' }}</p></div><ElButton :icon="Refresh" @click="load">刷新</ElButton></header>
    <section v-if="summary" class="stock-cards"><article><span>当前合格库存</span><strong>{{ numberText(summary.current_quantity) }}</strong><small v-if="summary.measurement_kind === 'PIPE'">根 / {{ summary.meter_quantity }} 米</small><small v-else>{{ summary.unit }}</small></article><article><span>公共可用库存</span><strong>{{ numberText(summary.available_quantity) }}</strong><small>{{ summary.unit }}</small></article><article><span>累计入库</span><strong>{{ numberText(summary.cumulative_inbound_quantity) }}</strong><small>{{ summary.unit }}</small></article><article><span>累计确认发料</span><strong>{{ numberText(summary.cumulative_issued_quantity) }}</strong><small>{{ summary.unit }}</small></article></section>
    <section class="mi-surface stock-tabs"><ElTabs v-model="activeTab">
      <ElTabPane label="订单领用" name="issues"><ElTable :data="issues" empty-text="暂无已确认领料记录"><ElTableColumn prop="issue_number" label="领料单号" width="170"><template #default="{ row }"><ElButton link type="primary" @click="router.push({ name: 'material-issue-detail', params: { issueId: row.material_issue_id } })">{{ row.issue_number }}</ElButton></template></ElTableColumn><ElTableColumn prop="production_task_number" label="生产订单" width="160" /><ElTableColumn prop="workshop" label="车间" width="120" /><ElTableColumn prop="recipient" label="领料人" width="110" /><ElTableColumn label="确认数量" width="120" align="right"><template #default="{ row }">{{ numberText(row.issued_quantity) }} {{ row.unit }}</template></ElTableColumn><ElTableColumn prop="reviewer" label="仓库确认人" width="120" /><ElTableColumn label="确认时间" min-width="180"><template #default="{ row }">{{ dateText(row.reviewed_at) }}</template></ElTableColumn></ElTable></ElTabPane>
      <ElTabPane label="订单采购" name="purchases"><ElTable :data="purchases" empty-text="暂无关联采购记录"><ElTableColumn prop="purchase_order_number" label="采购单号" width="180" /><ElTableColumn prop="production_task_number" label="归属生产订单" min-width="170" /><ElTableColumn label="采购数量" width="120" align="right"><template #default="{ row }">{{ numberText(row.purchase_quantity) }} {{ row.unit }}</template></ElTableColumn><ElTableColumn label="实际入库" width="120" align="right"><template #default="{ row }">{{ numberText(row.actual_inbound_quantity) }} {{ row.unit }}</template></ElTableColumn><ElTableColumn label="待入库" width="120" align="right"><template #default="{ row }">{{ numberText(row.pending_inbound_quantity) }} {{ row.unit }}</template></ElTableColumn></ElTable></ElTabPane>
    </ElTabs></section>
    <section v-if="summary" class="mi-surface zones"><h2 class="mi-section-title">库区余额</h2><ElTable :data="summary.zones" empty-text="暂无库区余额"><ElTableColumn label="材料仓" min-width="180"><template #default="{ row }">{{ row.warehouse_number }} · {{ row.warehouse_name }}</template></ElTableColumn><ElTableColumn prop="zone_name" label="库区" min-width="140" /><ElTableColumn v-if="summary.measurement_kind === 'PIPE'" prop="raw_bar_length_m" label="原材料长度（米/根）" width="170" /><ElTableColumn v-if="summary.measurement_kind === 'PIPE'" prop="meter_quantity" label="库存米数" width="140" /><ElTableColumn prop="quality" label="品质" width="110" /><ElTableColumn label="数量" width="140" align="right"><template #default="{ row }">{{ numberText(row.quantity) }} {{ summary?.unit }}</template></ElTableColumn></ElTable></section>
  </section>
</template>

<style scoped lang="scss">
@use '@/styles/materialIssue';
@use '@/styles/theme/detail' as detail;
.material-stock-detail { display: flex; height: auto; overflow: visible; flex-direction: column; gap: 14px; }
.material-stock-detail > * { flex-shrink: 0; }
.mi-page-head { flex-wrap: wrap; gap: 14px; }
.mi-page-head > div { min-width: 0; }
.mi-page-head h1 { margin-top: 2px; overflow-wrap: anywhere; font: 700 36px/44px var(--erp-font-body); }
.stock-cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 180px), 1fr)); gap: 14px; }
.stock-cards article { @include detail.surface; display: flex; flex-direction: column; gap: 6px; padding: 16px; }
.stock-cards span,.stock-cards small { color: var(--erp-color-text-secondary); font-size: 13px; }
.stock-cards strong { font-size: 24px; line-height: 32px; font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
.stock-tabs { padding: 0 16px 16px; }
.stock-tabs :deep(.el-tabs__header) { margin-bottom: 14px; }
.stock-tabs :deep(.el-tabs__item) { color: var(--erp-color-text-secondary); font-size: 13px; }
.stock-tabs :deep(.el-tabs__item.is-active) { color: var(--erp-color-brand); }
.stock-tabs :deep(.el-tabs__nav-wrap::after) { height: 1px; background: var(--erp-color-border-subtle); }
.zones { padding: 0 16px 16px; }
.zones .mi-section-title { padding: 14px 0; font-size: 16px; line-height: 24px; }
.stock-tabs :deep(.el-table), .zones :deep(.el-table) { --el-table-border-color: var(--erp-table-grid); --el-table-header-bg-color: var(--erp-table-header-fill); --el-table-tr-bg-color: var(--erp-table-body-fill); --el-table-row-hover-bg-color: var(--erp-table-hover); color: var(--erp-table-text); border-radius: var(--erp-radius-control); font-size: 13px; }
</style>
