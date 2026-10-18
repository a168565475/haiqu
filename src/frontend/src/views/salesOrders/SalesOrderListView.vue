<script setup lang="ts">
import { onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { MoreFilled, Plus, Search } from '@element-plus/icons-vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

import { fetchSalesOrders, fetchSalesOrderOptions } from '@/api/salesOrders'
import { vGlassSpotlight } from '@/directives/glassSpotlight'
import CustomerCountryCell from '@/components/customers/CustomerCountryCell.vue'
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
  <section class="order-page erp-glass-list">
    <section v-glass-spotlight class="filter-panel erp-list-filter" aria-label="销售订单筛选">
    <header class="page-heading erp-list-heading">
      <div class="heading-copy"><h1>销售订单</h1><span>共{{ total }}条</span></div>
    </header>
      <form class="filter-grid erp-list-filters" @submit.prevent="searchOrders">
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
      <div class="erp-list-filter-actions"><el-button class="erp-button-motion" @click="reset">重置</el-button><el-button class="erp-button-motion" type="primary" @click="searchOrders">应用筛选</el-button></div>
      </form>
    </section>

    <el-alert v-if="errorMessage" class="load-error" type="error" :title="errorMessage" show-icon :closable="false"><template #default><el-button link type="danger" @click="load">重新加载</el-button></template></el-alert>
    <section class="table-panel erp-list-data">
      <div v-if="!authStore.user?.sales_access_enabled || authStore.hasPermission('sales_orders.add_salesorder')" class="order-actions erp-list-toolbar">
        <el-button class="primary-action erp-button-motion" type="primary" :icon="Plus" @click="router.push({ name: 'sales-order-create' })">新建销售订单</el-button>
      </div>
      <div class="erp-list-table-frame">
      <el-table v-loading="loading" :data="rows" height="100%" empty-text="暂无销售订单">
        <el-table-column label="销售订单号" min-width="210" fixed>
          <template #default="{ row }">
            <button class="order-link" type="button" @click="openOrder(row)">{{ row.order_number }}</button>
          </template>
        </el-table-column>
        <el-table-column prop="source_type_display" label="订单来源" min-width="170" show-overflow-tooltip />
        <el-table-column label="客户" min-width="200">
          <template #default="{ row }"><CustomerCountryCell :country-code="row.customer_country_code || ''" :country-name="row.customer_name" /></template>
        </el-table-column>
        <el-table-column prop="customer_po_number" label="客户PO" min-width="150" />
        <el-table-column label="订单金额" min-width="160"><template #default="{ row }">{{ money(row.total_amount, row.currency_code) }}</template></el-table-column>
        <el-table-column label="产品/批次" width="140"><template #default="{ row }">{{ row.line_count }}种 / {{ row.delivery_batch_count }}批</template></el-table-column>
        <el-table-column prop="next_delivery_date" label="下次交期" width="140" />
        <el-table-column label="业务员" min-width="120" show-overflow-tooltip><template #default="{ row }">{{ row.salesperson?.display_name || '—' }}</template></el-table-column>
        <el-table-column label="跟单员" min-width="120" show-overflow-tooltip><template #default="{ row }">{{ row.merchandiser?.display_name || '未指定' }}</template></el-table-column>
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
      </div>
      <footer class="pagination erp-list-footer"><span class="pagination-total">共 {{ total }} 条</span><el-pagination v-model:current-page="page" v-model:page-size="pageSize" :page-sizes="[20, 50, 100]" :pager-count="5" layout="sizes, prev, pager, next" :total="total" @change="load" /></footer>
    </section>
  </section>
</template>

<style scoped lang="scss">
.heading-copy {
  display: flex;
  min-width: 0;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 12px;

  > span { color: var(--erp-color-text-secondary); font-size: 12px; }
}

.filter-control { flex: none; }
.filter-control--search { width: min(250px, 100%); min-width: 0; }
.filter-control--status { width: 160px; }
.filter-control--source { width: 176px; }
.primary-action { width: 140px; }
.load-error { flex: none; }

.order-search-button {
  display: inline-flex;
  width: 24px;
  height: 30px;
  align-items: center;
  justify-content: center;
  padding: 0;
  border: 0;
  color: var(--erp-input-placeholder);
  background: transparent;
  cursor: pointer;
}

.order-search-button:focus-visible,
.order-link:focus-visible {
  outline: 2px solid var(--erp-color-focus);
  outline-offset: 2px;
}

.order-link {
  max-width: 100%;
  overflow: hidden;
  padding: 0;
  border: 0;
  color: var(--erp-table-text);
  background: transparent;
  cursor: pointer;
  font: inherit;
  text-align: left;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.order-link:hover { text-decoration: underline; text-underline-offset: 3px; }

.status-tag {
  display: inline-flex;
  min-width: 56px;
  height: 24px;
  align-items: center;
  justify-content: center;
  padding: 0 8px;
  border: 1px solid transparent;
  border-radius: var(--erp-radius-pill);
  font-size: 12px;
  font-weight: 500;
  line-height: 18px;

  @each $tone in neutral, success, info, warning, danger {
    &.is-#{$tone} {
      color: var(--erp-tag-#{$tone}-text);
      border-color: var(--erp-tag-#{$tone}-border);
      background: var(--erp-tag-#{$tone}-background);
    }
  }
}

.more-action { width: 48px; color: var(--erp-table-text); }
.pagination-total { color: var(--erp-color-text-secondary); font-size: 12px; white-space: nowrap; }
</style>
