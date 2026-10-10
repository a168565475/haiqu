<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { AxiosError } from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRouter } from 'vue-router'

import {
  deleteSampleInventoryReceipt,
  fetchSampleInventory,
  fetchSampleInventoryOptions,
  fetchSampleInventorySummary,
} from '@/api/samples'
import SampleInventoryReceiptDialog from '@/components/samples/SampleInventoryReceiptDialog.vue'
import { useAuthStore } from '@/stores/auth'
import type {
  SampleInventoryOptions,
  SampleInventoryQuery,
  SampleInventoryRow,
  SampleInventorySummary,
} from '@/types/sample'

const loading = ref(false)
const router = useRouter()
const authStore = useAuthStore()
const summaryLoading = ref(false)
const optionsLoading = ref(false)
const errorMessage = ref('')
const summaryError = ref('')
const optionsError = ref('')
let listRequest = 0
let summaryRequest = 0
let optionsRequest = 0
const rows = ref<SampleInventoryRow[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(50)
const summary = ref<SampleInventorySummary | null>(null)
const options = ref<SampleInventoryOptions>({ product_categories: [], locations: [] })
const receiptDialogVisible = ref(false)
const dialogMounted = ref(false)
watch(receiptDialogVisible, visible => { if (visible) dialogMounted.value = true })
const deletingReceiptIds = ref<Set<string>>(new Set())
const filters = reactive({
  keyword: '',
  categoryName: '',
  location: '',
  inventoryStatus: 'AVAILABLE' as NonNullable<SampleInventoryQuery['inventory_status']>,
})
const inventoryStatusOptions: Array<{
  value: NonNullable<SampleInventoryQuery['inventory_status']>
  label: string
}> = [
  { value: 'AVAILABLE', label: '有库存（>0）' },
  { value: 'DEPLETED', label: '无库存（=0）' },
]

const inventoryHint = computed(() => (
  filters.inventoryStatus === 'DEPLETED'
    ? '仅显示剩余库存等于 0 的入库明细'
    : '仅显示剩余库存大于 0 的入库明细'
))
const inventoryEmptyText = computed(() => {
  if (errorMessage.value) return '列表加载失败'
  return filters.inventoryStatus === 'DEPLETED'
    ? '暂无剩余库存为 0 的记录。'
    : '暂无有库存记录。完成样品入库后将在这里显示。'
})
const canDeleteReceipt = computed(() => (
  authStore.hasPermission('samples.delete_sampleinventoryreceipt')
))
const canCreateReceipt = computed(() => authStore.hasPermission('samples.add_sampleinventoryreceipt'))
const canViewOutbound = computed(() => authStore.hasPermission('samples.view_sampleinventoryoutboundline'))
const canViewLoans = computed(() => authStore.hasPermission('samples.view_sampleinventoryloanline'))

const statCards = computed(() => [
  { key: 'available', label: '当前可用库存', value: summary.value?.current_available, icon: '✓', tone: 'green' },
  { key: 'borrowed', label: '借出中', value: summary.value?.borrowed, icon: '↗', tone: 'orange' },
  { key: 'inbound', label: '今日入库', value: summary.value?.inbound_today, icon: '＋', tone: 'blue' },
  { key: 'outbound', label: '今日出库', value: summary.value?.outbound_today, icon: '−', tone: 'red' },
])

function getErrorMessage(error: unknown): string {
  if (!(error instanceof AxiosError)) return '请求失败，请稍后重试。'
  if (!error.response) return '网络连接异常，请检查后端服务后重试。'
  const data = error.response.data as { error?: { message?: string }; detail?: string }
  if (error.response.status === 401) return '登录状态已失效，请重新登录。'
  if (error.response.status === 403) return '当前账号没有查看样品库存的权限。'
  if (error.response.status >= 500) return '样品库存服务暂时异常，请稍后重试。'
  return data?.error?.message || data?.detail || '请求失败，请检查筛选条件。'
}

function getDeleteErrorMessage(error: unknown): string {
  if (!(error instanceof AxiosError)) return '删除失败，请稍后重试。'
  if (!error.response) return '网络连接异常，请检查后端服务后重试。'
  const data = error.response.data as { error?: { message?: string }; detail?: string }
  if (error.response.status === 403) return '当前账号没有删除样品入库单的权限。'
  if (error.response.status >= 500) return '删除服务暂时异常，请稍后重试。'
  return data?.error?.message || data?.detail || '删除失败，请刷新列表后重试。'
}

function buildQuery(): SampleInventoryQuery {
  const query: SampleInventoryQuery = {
    page: page.value,
    page_size: pageSize.value,
    ordering: '-receipt__submitted_at',
  }
  if (filters.keyword.trim()) query.q = filters.keyword.trim()
  if (filters.categoryName) query.category_name = filters.categoryName
  if (filters.location) query.location = filters.location
  query.inventory_status = filters.inventoryStatus
  return query
}

async function loadRows() {
  const request = ++listRequest
  loading.value = true
  errorMessage.value = ''
  try {
    const result = await fetchSampleInventory(buildQuery())
    if (request !== listRequest) return
    rows.value = result.data
    total.value = result.meta.total
  } catch (error) {
    if (request !== listRequest) return
    rows.value = []
    total.value = 0
    errorMessage.value = getErrorMessage(error)
  } finally {
    if (request === listRequest) loading.value = false
  }
}

async function loadSummary() {
  const request = ++summaryRequest
  summaryError.value = ''
  summaryLoading.value = true
  try {
    const result = await fetchSampleInventorySummary()
    if (request !== summaryRequest) return
    summary.value = result
  } catch (error) {
    if (request !== summaryRequest) return
    summary.value = null
    summaryError.value = `库存统计加载失败：${getErrorMessage(error)}`
  } finally {
    if (request === summaryRequest) summaryLoading.value = false
  }
}

async function loadOptions() {
  const request = ++optionsRequest
  optionsError.value = ''
  optionsLoading.value = true
  try {
    const result = await fetchSampleInventoryOptions()
    if (request !== optionsRequest) return
    options.value = result
  } catch (error) {
    if (request !== optionsRequest) return
    optionsError.value = `筛选选项加载失败：${getErrorMessage(error)}`
  } finally {
    if (request === optionsRequest) optionsLoading.value = false
  }
}

function searchInventory() {
  page.value = 1
  void loadRows()
}

function resetFilters() {
  Object.assign(filters, {
    keyword: '',
    categoryName: '',
    location: '',
    inventoryStatus: 'AVAILABLE',
  })
  page.value = 1
  void loadRows()
}

function refreshPage() {
  void Promise.all([loadRows(), loadSummary(), loadOptions()])
}

function handleReceiptCreated() {
  refreshPage()
}

function openOutboundList() {
  if (!canViewOutbound.value) return
  void router.push({ name: 'sample-outbound' })
}

function openLoanList() {
  if (!canViewLoans.value) return
  void router.push({ name: 'sample-loans' })
}

function openReceiptDetail(receiptId: string) {
  void router.push({ name: 'sample-inventory-receipt-detail', params: { receiptId } })
}

async function deleteReceipt(row: SampleInventoryRow) {
  if (!canDeleteReceipt.value || loading.value || deletingReceiptIds.value.has(row.receipt_id)) return
  deletingReceiptIds.value = new Set([...deletingReceiptIds.value, row.receipt_id])
  try {
    try { await ElMessageBox.confirm(
      `确认删除入库单 ${row.receipt_number} 及其全部明细吗？已有出库或借出记录的入库单不能删除。`,
      '删除样品入库单',
      {
        type: 'warning',
        confirmButtonText: '确认删除',
        cancelButtonText: '取消',
      },
    ) } catch { return }
    if (!canDeleteReceipt.value) return
    await deleteSampleInventoryReceipt(row.receipt_id)
    const removedCurrentPage = rows.value.every((item) => item.receipt_id === row.receipt_id)
    if (removedCurrentPage && page.value > 1) page.value -= 1
    ElMessage.success('样品入库单已删除。')
    refreshPage()
  } catch (error) {
    ElMessage.error(getDeleteErrorMessage(error))
  } finally {
    const nextIds = new Set(deletingReceiptIds.value)
    nextIds.delete(row.receipt_id)
    deletingReceiptIds.value = nextIds
  }
}

function formatDateTime(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  const pad = (part: number) => String(part).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

onMounted(() => {
  refreshPage()
})
</script>

<template>
  <section class="sample-inventory-page" data-figma-node="810:8933" aria-labelledby="sample-inventory-title">
    <header class="page-heading">
      <div class="title-line">
        <h1 id="sample-inventory-title">样品库</h1>
        <span>统一管理样品库存、出库与借出记录</span>
      </div>
      <div class="heading-actions">
        <ElButton type="primary" :disabled="!canCreateReceipt" @click="canCreateReceipt && (receiptDialogVisible = true)">样品入库</ElButton>
        <ElButton :disabled="!canViewOutbound" @click="openOutboundList">样品出库</ElButton>
        <ElButton :disabled="!canViewLoans" @click="openLoanList">样品借出</ElButton>
      </div>
    </header>

    <nav class="inventory-tabs" aria-label="样品库分类">
      <button type="button" class="inventory-tab is-active" aria-current="page">样品库存</button>
      <button type="button" class="inventory-tab" :disabled="!canViewOutbound" @click="openOutboundList">样品出库</button>
      <button type="button" class="inventory-tab" :disabled="!canViewLoans" @click="openLoanList">样品借出</button>
    </nav>

    <div v-loading="summaryLoading" class="stats-grid">
      <article v-for="card in statCards" :key="card.key" class="stat-card">
        <div class="stat-copy">
          <span>{{ card.label }}</span>
          <strong>{{ card.value ?? '—' }}</strong>
        </div>
        <span class="stat-icon" :class="`is-${card.tone}`" aria-hidden="true">
          {{ card.icon }}
        </span>
      </article>
    </div>

    <div v-if="summaryError" class="load-error" role="alert">{{ summaryError }} <ElButton link @click="loadSummary">重试统计</ElButton></div>
    <div v-if="optionsError" class="load-error" role="alert">{{ optionsError }} <ElButton link @click="loadOptions">重试选项</ElButton></div>

    <ElCard class="filter-card" shadow="never">
      <ElForm class="filter-grid" label-position="top" @submit.prevent="searchInventory">
        <ElFormItem label="关键词">
          <ElInput
            v-model="filters.keyword"
            clearable
            placeholder="输入入库编号、打样单号或产品名称"
            aria-label="库存关键词"
            maxlength="100"
          />
        </ElFormItem>
        <ElFormItem label="产品类别">
          <ElSelect v-model="filters.categoryName" aria-label="产品类别" clearable placeholder="全部" :loading="optionsLoading">
            <ElOption v-for="item in options.product_categories" :key="item" :label="item" :value="item" />
          </ElSelect>
        </ElFormItem>
        <ElFormItem label="入库位置">
          <ElSelect v-model="filters.location" aria-label="入库位置" clearable placeholder="全部" :loading="optionsLoading">
            <ElOption v-for="item in options.locations" :key="item" :label="item" :value="item" />
          </ElSelect>
        </ElFormItem>
        <ElFormItem label="库存状态">
          <ElSelect v-model="filters.inventoryStatus" aria-label="库存状态" placeholder="请选择库存状态">
            <ElOption
              v-for="item in inventoryStatusOptions"
              :key="item.value"
              :label="item.label"
              :value="item.value"
            />
          </ElSelect>
        </ElFormItem>
        <div class="filter-actions">
          <ElButton type="primary" native-type="submit">查询</ElButton>
          <ElButton @click="resetFilters">重置</ElButton>
        </div>
      </ElForm>
    </ElCard>

    <div class="table-toolbar">
      <span>{{ inventoryHint }}</span>
      <ElButton :loading="loading" @click="refreshPage">刷新</ElButton>
    </div>

    <ElAlert
      v-if="errorMessage"
      class="list-error"
      type="error"
      :title="errorMessage"
      show-icon
      :closable="false"
    >
      <template #default><ElButton link type="primary" @click="refreshPage">重新加载</ElButton></template>
    </ElAlert>

    <ElCard class="table-card" shadow="never">
      <ElTable
        v-loading="loading"
        :data="rows"
        height="100%"
        row-key="id"
        :empty-text="inventoryEmptyText"
      >
        <ElTableColumn prop="receipt_number" label="样品入库编号" width="180" fixed="left">
          <template #default="{ row }">
            <button class="receipt-link" type="button" @click="openReceiptDetail(row.receipt_id)">{{ row.receipt_number }}</button>
          </template>
        </ElTableColumn>
        <ElTableColumn prop="inbound_time" label="入库时间" width="150">
          <template #default="{ row }">{{ formatDateTime(row.inbound_time) }}</template>
        </ElTableColumn>
        <ElTableColumn prop="sample_request_number" label="打样单号" width="170" show-overflow-tooltip />
        <ElTableColumn prop="product_category" label="产品类别" width="110" show-overflow-tooltip />
        <ElTableColumn prop="product_name" label="产品名称" min-width="160" show-overflow-tooltip />
        <ElTableColumn prop="specification" label="规格" min-width="170" show-overflow-tooltip />
        <ElTableColumn prop="color" label="颜色" width="90" show-overflow-tooltip />
        <ElTableColumn prop="sampling_quantity" label="打样数量" width="82" align="center" />
        <ElTableColumn prop="received_quantity" label="入库数量" width="82" align="center" />
        <ElTableColumn prop="available_quantity" label="剩余库存" width="88" align="center" />
        <ElTableColumn prop="location" label="入库位置" width="120" align="center" show-overflow-tooltip />
        <ElTableColumn label="操作" width="110" align="center" fixed="right">
          <template #default="{ row }">
            <ElButton link type="primary" :disabled="deletingReceiptIds.has(row.receipt_id)" @click="openReceiptDetail(row.receipt_id)">查看</ElButton>
            <ElButton
              v-if="canDeleteReceipt"
              link
              type="danger"
              :loading="deletingReceiptIds.has(row.receipt_id)"
              :disabled="loading || deletingReceiptIds.has(row.receipt_id)"
              @click="deleteReceipt(row)"
            >删除</ElButton>
          </template>
        </ElTableColumn>
      </ElTable>
      <footer class="table-footer">
        <span>共 {{ total }} 条</span>
        <ElPagination
          v-model:current-page="page"
          v-model:page-size="pageSize"
          background
          layout="sizes, prev, pager, next"
          :page-sizes="[20, 50, 100]"
          :total="total"
          @current-change="loadRows"
          @size-change="() => { page = 1; void loadRows() }"
        />
      </footer>
    </ElCard>
  </section>

  <SampleInventoryReceiptDialog
    v-if="canCreateReceipt && dialogMounted"
    v-model="receiptDialogVisible"
    @created="handleReceiptCreated"
  />
</template>

<style scoped lang="scss" src="./sampleInventory.scss"></style>
