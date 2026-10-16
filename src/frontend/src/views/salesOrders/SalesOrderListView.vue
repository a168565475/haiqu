<script setup lang="ts">
import { onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { MoreFilled, Plus, Search } from '@element-plus/icons-vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

import { fetchSalesOrders, fetchSalesOrderOptions } from '@/api/salesOrders'
import type { SalesOrderListItem, SalesOrderOptions } from '@/types/salesOrder'

const router = useRouter()
const authStore = useAuthStore()
let requestId = 0
let disposed = false
const loading = ref(false)
const errorMessage = ref('')
const rows = ref<SalesOrderListItem[]>([])
const options = ref<SalesOrderOptions | null>(null)
const page = ref(1)
const pageSize = ref(50)
const total = ref(0)
const filters = reactive({ q: '', status: '', source_type: '' })

function apiError(error: unknown): string {
  const data = (error as { response?: { data?: { detail?: string; error?: { message?: string } } } })?.response?.data
  return data?.error?.message || data?.detail || '销售订单加载失败，请稍后重试。'
}
function money(value: string, currency: string): string {
  const number = Number(value)
  return Number.isFinite(number) ? `${currency} ${number.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 4 })}` : `${currency} ${value}`
}
function statusClass(status: string) {
  if (status === 'CONFIRMED' || status === 'COMPLETED') return 'is-success'
  if (status === 'FULFILLING') return 'is-info'
  if (status === 'PAUSED') return 'is-warning'
  if (status === 'CANCELLED') return 'is-danger'
  return 'is-neutral'
}
function openOrder(row: SalesOrderListItem) {
  void router.push({ name: 'sales-order-detail', params: { orderId: row.id } })
}
function editOrder(row: SalesOrderListItem) {
  void router.push({ name: 'sales-order-edit', params: { orderId: row.id } })
}
async function load() {
  const request = ++requestId
  loading.value = true
  errorMessage.value = ''
  try {
    const result = await fetchSalesOrders({
      page: page.value,
      page_size: pageSize.value,
      q: filters.q.trim() || undefined,
      status: filters.status || undefined,
      source_type: filters.source_type || undefined,
    })
    if (disposed || request !== requestId) return
    rows.value = result.data
    total.value = result.meta.total
  } catch (error) {
    if (disposed || request !== requestId) return
    rows.value = []
    total.value = 0
    errorMessage.value = apiError(error)
  } finally {
    if (!disposed && request === requestId) loading.value = false
  }
}
function searchOrders() {
  page.value = 1
  void load()
}
function handleSearchEnter(event: KeyboardEvent) {
  if (event.isComposing || event.keyCode === 229) return
  event.preventDefault()
  searchOrders()
}
function reset() {
  Object.assign(filters, { q: '', status: '', source_type: '' })
  searchOrders()
}
onBeforeUnmount(() => { disposed = true; requestId++ })
onMounted(async () => {
  await Promise.all([
    load(),
    fetchSalesOrderOptions()
      .then((value) => { options.value = value })
      .catch((error) => {
        if (!errorMessage.value) errorMessage.value = `筛选选项加载失败：${apiError(error)}`
      }),
  ])
})
</script>

<template>
  <section class="order-page">
    <header class="page-heading">
      <div class="heading-copy"><h1>销售订单</h1><span>共{{ total }}条</span></div>
    </header>

    <section class="filter-panel" aria-label="销售订单筛选">
      <form class="filter-grid" @submit.prevent="searchOrders">
      <el-input
        v-model="filters.q"
        class="filter-control filter-control--search"
        aria-label="搜索销售订单"
        title="支持订单号、客户PO、合同号、客户名称/编号、产品名称/编号"
        clearable
        placeholder="搜索订单号、客户、产品"
        @keydown.enter="handleSearchEnter"
        @clear="searchOrders"
      >
        <template #suffix>
          <button type="button" class="order-search-button" aria-label="搜索销售订单列表" @click="searchOrders"><el-icon><Search /></el-icon></button>
        </template>
      </el-input>
      <el-select v-model="filters.status" class="filter-control filter-control--status" clearable placeholder="订单状态：全部" @change="searchOrders">
          <el-option v-for="item in options?.statuses || []" :key="item.value" :label="item.label" :value="item.value" />
      </el-select>
      <el-select v-model="filters.source_type" class="filter-control filter-control--source" clearable placeholder="订单来源：全部" @change="searchOrders">
          <el-option v-for="item in options?.source_types || []" :key="item.value" :label="item.label" :value="item.value" />
      </el-select>
      <el-button class="reset-action" @click="reset">重置</el-button>
      <div class="order-actions">
        <el-button v-if="!authStore.user?.sales_access_enabled || authStore.hasPermission('sales_orders.add_salesorder')" class="primary-action" type="primary" :icon="Plus" @click="router.push({ name: 'sales-order-create' })">新建销售订单</el-button>
      </div>
      </form>
    </section>

    <el-alert v-if="errorMessage" class="load-error" type="error" :title="errorMessage" show-icon :closable="false"><template #default><el-button link type="danger" @click="load">重新加载</el-button></template></el-alert>
    <section class="table-panel">
      <el-table v-loading="loading" :data="rows" height="100%" empty-text="暂无销售订单">
        <el-table-column label="销售订单号" min-width="210" fixed>
          <template #default="{ row }">
            <button class="order-link" type="button" @click="openOrder(row)">{{ row.order_number }}</button>
            <div class="muted">V{{ row.version_number }} | {{ row.source_type_display }}</div>
          </template>
        </el-table-column>
        <el-table-column label="客户" min-width="200">
          <template #default="{ row }"><span>{{ row.customer_name }}</span><div class="muted">{{ row.customer_code }}</div></template>
        </el-table-column>
        <el-table-column prop="customer_po_number" label="客户PO" min-width="150" />
        <el-table-column label="订单金额" min-width="160"><template #default="{ row }">{{ money(row.total_amount, row.currency_code) }}</template></el-table-column>
        <el-table-column label="产品/批次" width="140"><template #default="{ row }">{{ row.line_count }}种 / {{ row.delivery_batch_count }}批</template></el-table-column>
        <el-table-column prop="next_delivery_date" label="下次交期" width="140" />
        <el-table-column label="跟进人员" min-width="150"><template #default="{ row }">{{ row.salesperson?.display_name || '—' }}<div class="muted">跟单员{{ row.merchandiser?.display_name || '未指定' }}</div></template></el-table-column>
        <el-table-column label="订单状态" width="140"><template #default="{ row }"><span class="status-tag" :class="statusClass(row.status)">{{ row.status_display }}</span></template></el-table-column>
        <el-table-column label="操作" width="100" fixed="right" align="center">
          <template #default="{ row }">
            <el-dropdown :persistent="false" trigger="click">
              <el-button class="more-action" text :icon="MoreFilled" aria-label="打开订单操作" />
              <template #dropdown><el-dropdown-menu><el-dropdown-item @click="openOrder(row)">查看详情</el-dropdown-item><el-dropdown-item v-if="row.status === 'DRAFT' && (!authStore.user?.sales_access_enabled || authStore.canFor('sales_orders.change_salesorder', row))" @click="editOrder(row)">编辑草稿</el-dropdown-item></el-dropdown-menu></template>
            </el-dropdown>
          </template>
        </el-table-column>
      </el-table>
      <footer class="pagination"><span class="pagination-total">共 {{ total }} 条</span><el-pagination v-model:current-page="page" v-model:page-size="pageSize" :page-sizes="[20, 50, 100]" :pager-count="5" layout="sizes, prev, pager, next" :total="total" @change="load" /></footer>
    </section>
  </section>
</template>

<style scoped lang="scss">
@use '@/styles/crm/tokens' as token;

.order-page{display:flex;height:100%;min-width:0;flex-direction:column;padding:14px;background:token.$crm-color-page;color:token.$crm-text-primary;font-family:token.$crm-font-body}.page-heading{display:flex;min-height:68px;align-items:flex-start;justify-content:space-between}.heading-copy{display:flex;align-items:baseline;gap:46px}.page-heading h1{margin:0;font-family:token.$crm-font-display;font-size:34px;font-weight:600;line-height:44px}.heading-copy span{color:token.$crm-text-secondary;font-size:16px}.primary-action{width:140px;height:36px;border-color:token.$crm-primary;border-radius:token.$crm-radius-2;background:token.$crm-primary}.filter-panel{height:38px;margin:17px 0 0;padding:0;border:0;background:transparent}.filter-grid{display:flex;height:38px;align-items:stretch;gap:14px}.filter-control{height:38px;flex:none}.filter-control--status{width:160px}.filter-control--source{width:176px}.filter-control :deep(.el-input__wrapper),.filter-control :deep(.el-select__wrapper){min-height:38px;box-sizing:border-box;padding:0 12px;border-radius:token.$crm-radius-2;background:token.$crm-color-surface;box-shadow:0 0 0 1px token.$crm-border-default inset}.filter-control :deep(.el-input__wrapper:hover),.filter-control :deep(.el-select__wrapper:hover){box-shadow:0 0 0 1px token.$crm-border-strong inset}.filter-control :deep(.el-input__wrapper.is-focus),.filter-control :deep(.el-select__wrapper.is-focused){box-shadow:0 0 0 1px token.$crm-focus inset,0 0 0 2px rgba(56,152,236,.18)}.filter-control :deep(.el-input__inner),.filter-control :deep(.el-select__placeholder),.filter-control :deep(.el-select__selected-item){color:token.$crm-text-secondary;font-size:12px;line-height:18px}.reset-action{height:38px;margin:0!important;border-radius:token.$crm-radius-2}.reset-action{width:72px}.load-error{margin-bottom:12px}.table-panel{display:flex;min-height:0;flex:1;flex-direction:column;overflow:hidden;border:1px solid #ddd6c9;border-radius:5px;background:#fcfbf7}.table-panel :deep(.el-table){flex:1;min-height:0;--el-table-border-color:#ddd6c9;--el-table-header-bg-color:#f0eadf;--el-table-row-hover-bg-color:#f7f3eb;color:#1f1d18}.table-panel :deep(.el-table__header th.el-table__cell){height:44px;background:#f0eadf;color:#6f6a61;font-weight:500}.table-panel :deep(.el-table__body td.el-table__cell){height:53px}.table-panel :deep(.el-table__inner-wrapper::before){display:none}.order-link{padding:0;border:0;color:#1f1d18;background:transparent;cursor:pointer;font:inherit}.order-link:hover{color:#c84e28}.muted{margin-top:3px;color:#6f6a61;font-size:12px}.status-tag{display:inline-flex;min-width:56px;height:24px;align-items:center;justify-content:center;padding:0 8px;border-radius:999px;color:#faf9f5;font-size:12px;font-weight:500;line-height:18px}.status-tag.is-neutral{background:#65635e}.status-tag.is-success{background:#4e8750}.status-tag.is-info{background:#2f97df}.status-tag.is-warning{background:#b87818}.status-tag.is-danger{background:#b8442c}.more-action{width:48px;height:28px;color:#4d4942}.pagination{display:flex;min-height:60px;flex:none;align-items:center;justify-content:flex-end;padding:0 30px;border-top:1px solid #ddd6c9}.pagination :deep(.el-pagination){--el-pagination-hover-color:#c84e28}.pagination :deep(.el-select__wrapper),.pagination :deep(.btn-prev),.pagination :deep(.btn-next),.pagination :deep(.el-pager li){min-width:80px;height:32px;border:1px solid #e2ddd4;border-radius:4px;background:#fff}.pagination :deep(.el-pager li){min-width:48px}.pagination :deep(.el-pager li.is-active){color:#c84e28}

.order-page .page-heading { height: 46px; min-height: 46px; flex: none; }
.order-page .heading-copy { gap: 16px; }
.order-page .primary-action { height: 32px; }
.order-page .filter-panel { height: 32px; flex: none; margin-top: 17px; }
.order-page .filter-grid, .order-page .filter-control { height: 32px; }
.order-page .filter-control :deep(.el-input__wrapper),
.order-page .filter-control :deep(.el-select__wrapper) { height: 32px; min-height: 32px; }
.order-page .reset-action { height: 32px; margin: 0 !important; }
.order-page .table-panel { margin-top: 14px; }
.order-page .pagination { min-height: 48px; flex-wrap: wrap; justify-content: space-between; gap: 8px; padding: 8px 14px; }
.order-page .pagination-total { color: token.$crm-text-secondary; font-size: 12px; white-space: nowrap; }
.order-page .pagination :deep(.el-pagination) {
  height: auto;
  min-width: 0;
  max-width: 100%;
  flex-wrap: wrap;
  justify-content: flex-end;
  margin-left: auto;
  gap: 8px;
  --el-pagination-button-width: 38px;
  --el-pagination-button-height: 32px;
}
.order-page .pagination :deep(.el-pagination__sizes) { width: 136px; margin-right: 16px; }
.order-page .pagination :deep(.el-pagination__sizes .el-select) { width: 136px; }
.order-page .pagination :deep(.el-pagination__sizes .el-select__wrapper) { min-width: 136px; min-height: 32px; }
.order-page .pagination :deep(.btn-prev),
.order-page .pagination :deep(.btn-next),
.order-page .pagination :deep(.el-pager li) { width: 38px; min-width: 38px; height: 32px; }
.order-page .pagination :deep(.el-pager) { gap: 8px; }
.order-page .pagination :deep(.el-pager li.is-active) { border-color: token.$crm-primary; color: token.$crm-text-primary; }

.order-page .filter-panel,
.order-page .filter-grid { height: auto; }
.order-page .filter-grid { flex-wrap: wrap; row-gap: 10px; }
.order-page .filter-control--search { width: 250px; min-width: 250px; flex: none; }
.order-actions { display: flex; flex: none; align-items: center; margin-left: auto; }
.order-search-button { display: inline-flex; width: 20px; height: 24px; align-items: center; justify-content: center; padding: 0; border: 0; background: transparent; color: token.$crm-text-secondary; cursor: pointer; }
.order-search-button:focus-visible { outline: 2px solid token.$crm-focus; outline-offset: 2px; }
</style>
