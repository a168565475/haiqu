<script setup lang="ts">
import { vGlassSpotlight } from '@/directives/glassSpotlight'
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh, Search } from '@element-plus/icons-vue'
import { useRoute } from 'vue-router'

import { fetchMaterialIssueOptions, fetchMaterialIssues } from '@/api/materialIssues'
import { router } from '@/router'
import type { MaterialIssue, MaterialIssueOptions, MaterialIssueStatus } from '@/types/materialIssue'

const route = useRoute()
const rows = ref<MaterialIssue[]>([])
const total = ref(0)
const loading = ref(false)
const options = ref<MaterialIssueOptions>({ production_tasks: [], workshops: [], recipients: [] })
const filters = reactive({
  search: String(route.query.search || ''),
  status: String(route.query.status || ''),
  workshop_id: String(route.query.workshop_id || ''),
  recipient_id: String(route.query.recipient_id || ''),
  production_task_id: String(route.query.production_task_id || ''),
  product_line_id: String(route.query.product_line_id || ''),
  ordering: String(route.query.ordering || '-created_at'),
  page: Math.max(Number(route.query.page) || 1, 1),
  page_size: Math.min(Math.max(Number(route.query.page_size) || 20, 10), 100),
})
const hasPlanContext = computed(() => Boolean(route.query.production_task_id || route.query.product_line_id))

const statusOptions: { value: MaterialIssueStatus; label: string }[] = [
  { value: 'DRAFT', label: '草稿' }, { value: 'PENDING_REVIEW', label: '待仓库审核' },
  { value: 'RETURNED', label: '已退回' }, { value: 'ISSUED', label: '已出库' },
]
const recipients = () => options.value.recipients.filter((item) => !filters.workshop_id || item.workshop_id === filters.workshop_id)
const apiMessage = (error: unknown) => (error as { response?: { data?: { error?: { message?: string } } } })?.response?.data?.error?.message || '生产领料列表加载失败。'
const dateText = (value: string | null) => value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '—'

async function load() {
  loading.value = true
  try {
    const data = await fetchMaterialIssues(filters)
    rows.value = data.data
    total.value = data.meta.total
  } catch (error) { ElMessage.error(apiMessage(error)) }
  finally { loading.value = false }
}
function apply(resetPage = true) {
  if (resetPage) filters.page = 1
  void router.replace({ query: Object.fromEntries(Object.entries(filters).filter(([, value]) => value !== '')) })
  void load()
}
function reset() {
  Object.assign(filters, { search: '', status: '', workshop_id: '', recipient_id: '', production_task_id: '', product_line_id: '', ordering: '-created_at', page: 1, page_size: 20 })
  apply()
}
function open(row: MaterialIssue) { void router.push({ name: 'material-issue-detail', params: { issueId: row.id }, query: route.query }) }
function statusTone(status: MaterialIssueStatus) {
  return status === 'ISSUED' ? 'is-success' : status === 'RETURNED' ? 'is-danger' : status === 'PENDING_REVIEW' ? 'is-info' : 'is-neutral'
}
watch(() => filters.workshop_id, () => { if (!recipients().some((item) => item.id === filters.recipient_id)) filters.recipient_id = '' })
watch(
  () => [route.query.production_task_id, route.query.product_line_id],
  ([productionTaskId, productLineId]) => {
    const nextTaskId = String(productionTaskId || '')
    const nextProductLineId = String(productLineId || '')
    if (filters.production_task_id === nextTaskId && filters.product_line_id === nextProductLineId) return
    filters.production_task_id = nextTaskId
    filters.product_line_id = nextProductLineId
    filters.page = 1
    void load()
  },
)
onMounted(async () => {
  try { options.value = await fetchMaterialIssueOptions() } catch (error) { ElMessage.error(apiMessage(error)) }
  await load()
})
</script>

<template>
  <section class="material-issue-page material-issue-list erp-glass-list" :class="{ 'has-plan-context': hasPlanContext }" data-testid="material-issue-list">
    <section v-glass-spotlight class="erp-list-filter">
    <header class="mi-page-head erp-list-heading">
      <div><h1>生产领料</h1></div>
    </header>
    <section v-if="!hasPlanContext" class="mi-filter-row erp-list-filters">
      <ElInput v-model="filters.search" clearable placeholder="搜索领料单号、订单或领料人" :prefix-icon="Search" @keyup.enter="apply" />
      <ElSelect v-model="filters.status" clearable placeholder="状态：全部" @change="apply"><ElOption v-for="item in statusOptions" :key="item.value" :label="item.label" :value="item.value" /></ElSelect>
      <ElSelect v-model="filters.workshop_id" clearable placeholder="车间：全部" @change="apply"><ElOption v-for="item in options.workshops" :key="item.id" :label="item.name" :value="item.id" /></ElSelect>
      <ElSelect v-model="filters.recipient_id" clearable filterable placeholder="领料人：全部" @change="apply"><ElOption v-for="item in recipients()" :key="item.id" :label="item.name" :value="item.id" /></ElSelect>
      <ElSelect v-model="filters.ordering" aria-label="排序" @change="apply"><ElOption label="最新创建" value="-created_at" /><ElOption label="最早创建" value="created_at" /><ElOption label="最近领料时间" value="-issue_at" /></ElSelect>
      <div class="erp-list-filter-actions"><ElButton class="erp-button-motion" @click="reset">重置</ElButton><ElButton class="erp-button-motion" type="primary" @click="apply">应用筛选</ElButton></div>
    </section>
    </section>
    <section class="erp-list-data">
    <section class="mi-toolbar erp-list-toolbar" aria-label="列表工具栏"><span>领料申请从金工、裁剪、车缝或装配作业计划发起。</span><ElButton class="erp-button-motion" :icon="Refresh" :loading="loading" @click="load">刷新</ElButton></section>
    <section class="mi-table-panel erp-list-table-frame">
      <ElTable v-loading="loading" :data="rows" row-key="id" height="100%" empty-text="暂无生产领料单" @row-dblclick="open">
        <ElTableColumn prop="issue_number" label="领料单号" min-width="160" />
        <ElTableColumn label="状态" width="116"><template #default="{ row }"><span class="mi-status-tag erp-list-tag" :class="statusTone(row.status).replace('is-', 'erp-list-tag--')">{{ row.status_display }}</span></template></ElTableColumn>
        <ElTableColumn label="生产订单" min-width="160"><template #default="{ row }">{{ row.production_task?.task_number || '—' }}</template></ElTableColumn>
        <ElTableColumn label="产品" min-width="180"><template #default="{ row }">{{ row.product?.product_name || '—' }}</template></ElTableColumn>
        <ElTableColumn label="规格" min-width="160"><template #default="{ row }">{{ (row.product?.specification_display ?? row.product?.specification) || '—' }}</template></ElTableColumn>
        <ElTableColumn label="颜色" min-width="110"><template #default="{ row }">{{ row.product?.color || '—' }}</template></ElTableColumn>
        <ElTableColumn label="材质" min-width="110"><template #default="{ row }">{{ row.product?.material || '—' }}</template></ElTableColumn>
        <ElTableColumn label="车间" width="120"><template #default="{ row }">{{ row.workshop?.name || '—' }}</template></ElTableColumn>
        <ElTableColumn label="领料人" width="110"><template #default="{ row }">{{ row.recipient?.name || '—' }}</template></ElTableColumn>
        <ElTableColumn prop="line_count" label="材料项" width="80" align="right" />
        <ElTableColumn label="领料时间" width="180"><template #default="{ row }">{{ dateText(row.issue_at) }}</template></ElTableColumn>
        <ElTableColumn label="操作" width="88" fixed="right"><template #default="{ row }"><ElButton link type="primary" @click.stop="open(row)">查看</ElButton></template></ElTableColumn>
      </ElTable>
    </section>
    <footer class="mi-pagination erp-list-footer"><span>共 {{ total }} 条</span><ElPagination v-model:current-page="filters.page" v-model:page-size="filters.page_size" background layout="sizes, prev, pager, next" :total="total" :page-sizes="[20, 50, 100]" @current-change="apply(false)" @size-change="filters.page = 1; apply(false)" /></footer>
    </section>
  </section>
</template>

<style scoped lang="scss">
.mi-filter-row :deep(.el-input) { width: min(100%, 250px); }
.mi-filter-row :deep(.el-select) { width: 180px; }
.mi-toolbar { justify-content: space-between; }
.mi-toolbar > span { font-size: 12px; color: var(--erp-color-text-secondary); }
</style>
