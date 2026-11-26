<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { isAxiosError } from 'axios'
import { fetchPrintOrders } from '@/api/cutPiecePrinting'
import type { UnifiedOutsourcingOrder } from '@/types/unifiedOutsourcing'
import { unifiedQuantityText } from '@/utils/unifiedOutsourcingDisplay'

const rows = ref<UnifiedOutsourcingOrder[]>([])
const search = ref(''), appliedSearch = ref(''), page = ref(1), total = ref(0)
const loading = ref(false), error = ref('')
const pageSize = 20
let sequence = 0

async function load(target = 1) {
  const current = ++sequence
  page.value = target
  loading.value = true
  error.value = ''
  try {
    const result = await fetchPrintOrders({ page: target, page_size: pageSize, search: appliedSearch.value })
    if (current !== sequence) return
    rows.value = result.data
    total.value = result.meta.total
  } catch (cause) {
    if (current !== sequence) return
    rows.value = []
    total.value = 0
    error.value = (isAxiosError(cause) && cause.response?.data?.error?.message) || '丝印外发单读取失败，请重新查询。'
  } finally {
    if (current === sequence) loading.value = false
  }
}
function searchOrders() {
  appliedSearch.value = search.value.trim()
  void load()
}
function quantity(row: UnifiedOutsourcingOrder, field: 'transferred_quantity' | 'receivable_quantity') {
  return row.plan_summary?.quantity_totals?.filter(item => item[field] !== undefined)
    .map(item => `${item[field]} ${item.unit}`).join(' / ') || '—'
}
onMounted(() => load())
</script>

<template>
  <section class="outsourcing-list-page erp-list-page">
    <header class="erp-list-heading"><h1>裁片丝印外发</h1></header>
    <form class="erp-list-toolbar" @submit.prevent="searchOrders">
      <ElInput v-model="search" aria-label="生产任务单号或外发单号" placeholder="生产任务单号 / 外发单号" clearable @clear="searchOrders" />
      <ElButton native-type="submit">查询</ElButton>
      <RouterLink class="el-button el-button--primary" :to="{ name: 'cut-piece-printing-new' }">新建丝印外发单</RouterLink>
    </form>
    <ElAlert v-if="error" :title="error" type="error" :closable="false" />
    <ElTable v-else v-loading="loading" :data="rows" row-key="id" empty-text="暂无丝印外发单">
      <ElTableColumn prop="production_task_number" label="生产任务单号" min-width="130" />
      <ElTableColumn label="丝印外发单号" min-width="150"><template #default="{ row }"><RouterLink :to="{ name: 'cut-piece-printing-detail', params: { id: row.id } }">{{ row.order_number }}</RouterLink></template></ElTableColumn>
      <ElTableColumn label="产品" min-width="140"><template #default="{ row }">{{ row.product.product_name || '—' }}</template></ElTableColumn>
      <ElTableColumn label="丝印厂" min-width="140"><template #default="{ row }">{{ row.factory_names.join('、') }}</template></ElTableColumn>
      <ElTableColumn label="累计发出" align="right" width="110"><template #default="{ row }">{{ unifiedQuantityText(row, 'sent') }}</template></ElTableColumn>
      <ElTableColumn label="累计回仓" align="right" width="110"><template #default="{ row }">{{ unifiedQuantityText(row, 'received') }}</template></ElTableColumn>
      <ElTableColumn label="直送车缝厂" align="right" width="110"><template #default="{ row }">{{ quantity(row, 'transferred_quantity') }}</template></ElTableColumn>
      <ElTableColumn label="丝印厂待交" align="right" width="110"><template #default="{ row }">{{ quantity(row, 'receivable_quantity') }}</template></ElTableColumn>
      <ElTableColumn prop="status_display" label="状态" width="110" />
    </ElTable>
    <ElPagination v-if="total > pageSize" :current-page="page" :page-size="pageSize" :total="total" layout="prev, pager, next" @current-change="load" />
  </section>
</template>

<style scoped>
.erp-list-toolbar { display: flex; gap: 10px; margin-bottom: 14px; }
.erp-list-toolbar .el-input { max-width: 320px; }
.erp-list-toolbar a { margin-left: auto; }
</style>
